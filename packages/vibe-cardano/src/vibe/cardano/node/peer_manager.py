"""Peer connection management with automatic reconnect.

Manages outbound N2N peer connections: TCP connect, multiplexer setup,
handshake, miniprotocol launch, and reconnect with exponential backoff.

Haskell references:
    - Ouroboros.Network.Diffusion.P2P -- P2P governor for outbound connections
    - Ouroboros.Network.PeerSelection.Governor.ActivePeers -- backoff logic
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID
from vibe.cardano.network.handshake import HANDSHAKE_PROTOCOL_ID
from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
from vibe.core.multiplexer import (
    Bearer,
    BearerClosedError,
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
)

from .config import NodeConfig, PeerAddress

__all__ = ["PeerManager", "_RangeTracker"]

logger = logging.getLogger(__name__)


@dataclass
class _PeerConnection:
    """Internal tracking for a single peer connection."""

    address: PeerAddress
    bearer: Bearer | None = None
    mux: Multiplexer | None = None
    mux_task: asyncio.Task[None] | None = None
    task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None
    reconnect_delay: float = 1.0
    reconnect_attempt: int = 0
    connected: bool = False
    protocol_tasks: list = None  # type: ignore[assignment]  # asyncio.Task refs

    def __post_init__(self) -> None:
        if self.protocol_tasks is None:
            self.protocol_tasks = []


class _RangeTracker:
    """Track in-flight ranges per peer for re-enqueue on disconnect."""

    def __init__(self, range_queue: asyncio.Queue) -> None:
        self._range_queue = range_queue
        self._in_flight: dict[str, list[tuple]] = {}

    def on_range_sent(self, peer_addr: str, range_tuple: tuple) -> None:
        self._in_flight.setdefault(peer_addr, []).append(range_tuple)

    def on_range_complete(self, peer_addr: str, range_tuple: tuple) -> None:
        if peer_addr in self._in_flight:
            try:
                self._in_flight[peer_addr].remove(range_tuple)
            except ValueError:
                pass

    def on_peer_disconnect(self, peer_addr: str) -> None:
        ranges = self._in_flight.pop(peer_addr, [])
        for r in ranges:
            self._range_queue.put_nowait(r)

    def on_no_blocks(self, range_tuple: tuple) -> None:
        self._range_queue.put_nowait(range_tuple)


class PeerManager:
    """Manages outbound N2N peer connections with automatic reconnect.

    For each configured peer, the PeerManager:
    1. Opens a TCP connection
    2. Wraps it in a Bearer + Multiplexer
    3. Registers the N2N miniprotocol bundle
    4. Runs the multiplexer
    5. On disconnect, waits with exponential backoff and reconnects

    Haskell ref:
        ``Ouroboros.Network.Diffusion.P2P`` -- the P2P governor manages
        outbound connections with warm/hot/cold state transitions and
        backoff on failure.  Our implementation is simpler: connect,
        run mux, reconnect on failure.

    Args:
        config: Node configuration (for network_magic and peer list).
        chain_db: ChainDB instance for storing received blocks.
    """

    __slots__ = (
        "_config",
        "_chain_db",
        "_node_kernel",
        "_peers",
        "_stopped",
        "_tasks",
        "_known_points",
        "_block_received_event",
        "_shared_range_queue",
        "_shared_block_queue",
        "_processor_task",
        "_nonce_worker_task",
        "_range_tracker",
        "_chain_sync_peer",
        "_block_notify",
        "peer_tip_block_no_tvar",
    )

    def __init__(
        self,
        config: NodeConfig,
        chain_db: Any = None,
        node_kernel: Any = None,
        block_received_event: Any = None,
    ) -> None:
        self._config = config
        self._chain_db = chain_db
        self._node_kernel = node_kernel
        self._peers: dict[str, _PeerConnection] = {}
        self._stopped = False
        self._tasks: list[asyncio.Task[None]] = []
        self._known_points: list[Any] = []
        # threading.Event — set when a new block is processed,
        # wakes the forge thread to check leadership immediately.
        self._block_received_event = block_received_event
        # Multi-peer shared state
        self._shared_range_queue: asyncio.Queue | None = None
        self._shared_block_queue: asyncio.Queue | None = None
        self._processor_task: asyncio.Task | None = None
        self._nonce_worker_task: asyncio.Task | None = None
        self._range_tracker: _RangeTracker | None = None
        self._chain_sync_peer: str | None = None
        self._block_notify = asyncio.Event()
        # Best known peer tip block number — updated by chain-sync client
        # when it receives headers. Read by forge loop to avoid forging
        # on a chain that's behind the peer tip (would be orphaned).
        from vibe.core.stm import TVar
        self.peer_tip_block_no_tvar: TVar = TVar(0)

    @property
    def known_points(self) -> list[Any]:
        """Known chain points for chain-sync intersection (from snapshot or chain tip)."""
        return self._known_points

    def set_known_points(self, points: list[Any]) -> None:
        """Set known points for chain-sync to start from (instead of Origin)."""
        self._known_points = points

    def _ensure_shared_queues(self) -> tuple[asyncio.Queue, asyncio.Queue]:
        """Lazily create shared range_queue and block_queue for multi-peer fetch."""
        if self._shared_range_queue is None:
            self._shared_range_queue = asyncio.Queue()
            self._shared_block_queue = asyncio.Queue(maxsize=500)
            self._range_tracker = _RangeTracker(self._shared_range_queue)
        return self._shared_range_queue, self._shared_block_queue

    @property
    def connected_count(self) -> int:
        """Number of currently connected peers."""
        return sum(1 for p in self._peers.values() if p.connected)

    @property
    def peer_ids(self) -> list[str]:
        """List of all tracked peer IDs (host:port strings)."""
        return list(self._peers.keys())

    def add_peer(self, address: PeerAddress) -> None:
        """Register a peer for connection management.

        Args:
            address: The peer's network address.
        """
        peer_id = str(address)
        if peer_id not in self._peers:
            self._peers[peer_id] = _PeerConnection(address=address)

    async def start(self) -> None:
        """Start connection tasks for all registered peers."""
        for peer_id, peer in self._peers.items():
            task = asyncio.create_task(self._peer_loop(peer), name=f"peer-{peer_id}")
            self._tasks.append(task)
            peer.task = task

    async def stop(self) -> None:
        """Disconnect all peers and cancel reconnect loops."""
        self._stopped = True
        for peer in self._peers.values():
            await self._disconnect_peer(peer)
            if peer.task is not None and not peer.task.done():
                peer.task.cancel()
                try:
                    await peer.task
                except (asyncio.CancelledError, Exception):
                    pass

    async def _peer_loop(self, peer: _PeerConnection) -> None:
        """Connection loop for a single peer -- connect, run, reconnect.

        Implements exponential backoff on connection failures:
        1s -> 2s -> 4s -> ... -> 60s (capped).

        On successful reconnection the backoff delay and attempt counter
        reset to their initial values so transient errors don't
        permanently degrade reconnect speed.

        Haskell ref:
            Ouroboros.Network.PeerSelection.Governor.ActivePeers -- the
            governor uses exponential backoff with a cap for peer
            reconnection delays after connection failures.
        """
        while not self._stopped:
            try:
                await self._connect_peer(peer)
                # Reset backoff on successful connection.
                peer.reconnect_delay = 1.0
                peer.reconnect_attempt = 0

                # Mux is already running (started in _connect_peer after
                # handshake). Await the mux task until disconnect.
                if peer.mux_task is not None:
                    await peer.mux_task

            except (MuxClosedError, BearerClosedError) as exc:
                # Multiplexer or bearer closed -- normal disconnect path.
                # Log at INFO rather than WARNING since this is expected
                # during peer disconnects and node shutdowns.
                logger.info(
                    "Peer %s: connection closed: %s",
                    peer.address,
                    exc,
                )
            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "Peer %s: connection failed: %s",
                    peer.address,
                    exc,
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error(
                    "Peer %s: unexpected error: %s",
                    peer.address,
                    exc,
                    exc_info=True,
                )
            finally:
                peer.connected = False
                await self._disconnect_peer(peer)

            if self._stopped:
                return

            # Backoff before reconnect.
            peer.reconnect_attempt += 1
            logger.info(
                "Reconnecting to peer %s in %.1fs (attempt %d)",
                peer.address,
                peer.reconnect_delay,
                peer.reconnect_attempt,
            )
            await asyncio.sleep(peer.reconnect_delay)
            peer.reconnect_delay = min(peer.reconnect_delay * 2, 60.0)

    async def _connect_peer(self, peer: _PeerConnection) -> None:
        """Open TCP connection, set up multiplexer, and run N2N handshake.

        The handshake must complete before any other miniprotocol can run.
        We start the mux sender/receiver in the background (they handle
        wire framing), run the handshake on channel 0, then return — the
        caller continues with mux.run() which blocks until disconnect.

        Haskell ref:
            Ouroboros.Network.Protocol.Handshake.Client — client peer
            The Haskell node runs the handshake as the first action on a
            new connection before activating other miniprotocols.
        """
        from vibe.cardano.network.handshake_protocol import (
            HandshakeError,
            run_handshake_client,
        )

        logger.info(
            "Peer %s connecting",
            peer.address,
            extra={"event": "peer.connect", "peer": str(peer.address)},
        )
        reader, writer = await asyncio.open_connection(peer.address.host, peer.address.port)
        # Disable Nagle's algorithm for low-latency segment delivery.
        # Haskell uses Socket.sendAll per segment; without NODELAY our
        # small chain-sync headers get buffered for up to 200ms.
        sock = writer.transport.get_extra_info('socket')
        if sock is not None:
            import socket
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=True)

        # Register N2N miniprotocol channels with dual (init+resp) support.
        # Handshake is single-direction (initiator only for outbound).
        # All other protocols get both initiator and responder channels
        # so we can serve data back to the peer on the same connection.
        init_channels: dict[int, MiniProtocolChannel] = {}
        resp_channels: dict[int, MiniProtocolChannel] = {}

        init_channels[HANDSHAKE_PROTOCOL_ID] = mux.add_protocol(HANDSHAKE_PROTOCOL_ID)

        for proto_id in [CHAIN_SYNC_N2N_ID, BLOCK_FETCH_N2N_ID, TX_SUBMISSION_N2N_ID, KEEP_ALIVE_PROTOCOL_ID]:
            init_ch, resp_ch = mux.add_protocol_pair(proto_id)
            init_channels[proto_id] = init_ch
            resp_channels[proto_id] = resp_ch

        # Alias: existing code uses `channels[X]` for initiator protocols.
        channels = init_channels

        peer.bearer = bearer
        peer.mux = mux

        # The mux must be running for channels to work (sender/receiver
        # loops handle the wire framing). Start it, run the handshake,
        # then let the caller's mux.run() take over.
        #
        # We use a task for the mux and run the handshake concurrently.
        # After handshake completes, we stop the mux task — the caller
        # will call mux.run() again which restarts the loops.
        #
        # Actually, mux.run() can only be called once. So instead, we
        # need to run the handshake as part of the mux lifetime. The
        # approach: start the mux in a background task, do the handshake,
        # then return. The peer_loop will NOT call mux.run() again —
        # instead, we await the background mux task.

        # Start mux sender/receiver loops in background.
        mux_task = asyncio.create_task(mux.run(), name=f"mux-{peer.address}")

        try:
            # Run N2N handshake on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            result = await run_handshake_client(hs_channel, self._config.network_magic)
            peer.connected = True
            logger.info(
                "Peer %s connected (v%d, magic %d)",
                peer.address,
                result.version_number,
                result.version_data.network_magic,
                extra={
                    "event": "peer.connected",
                    "peer": str(peer.address),
                    "version": result.version_number,
                    "magic": result.version_data.network_magic,
                },
            )
        except (HandshakeError, Exception) as exc:
            # Handshake failed — tear down the mux and propagate.
            await mux.close()
            try:
                await mux_task
            except Exception:
                pass
            raise ConnectionError(f"Handshake with {peer.address} failed: {exc}") from exc

        # --- Launch miniprotocol runners on their channels ---
        # Each runs as a background task for the lifetime of the connection.
        # The mux routes bytes between the bearer and these channel tasks.

        from vibe.cardano.network.chainsync_protocol import run_chain_sync
        from vibe.cardano.network.keepalive_protocol import run_keep_alive_client
        from vibe.cardano.network.txsubmission_protocol import run_tx_submission_client

        stop_event = asyncio.Event()
        peer.stop_event = stop_event
        peer.protocol_tasks = []  # clear from previous connection

        async def _safe_run(coro, name: str) -> None:
            """Run a miniprotocol coroutine, suppressing MuxClosedError on shutdown."""
            try:
                await coro
            except MuxClosedError:
                logger.debug("Peer %s: %s channel closed", peer.address, name)
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Peer %s: %s error: %s", peer.address, name, exc)

        # --- Multi-peer sync pipeline ---
        # Chain-sync runs on the FIRST connected peer only.
        # ALL peers run block-fetch, sharing range_queue and block_queue.
        # A single processor task stores blocks from the shared block_queue.

        import hashlib

        import cbor2pure as cbor2

        from vibe.cardano.network.chainsync import Point

        shared_range_queue, shared_block_queue = self._ensure_shared_queues()
        chain_db = self._chain_db
        node_kernel = self._node_kernel
        peer_addr = str(peer.address)

        # --- Chain-sync (first peer only) ---
        if self._chain_sync_peer is None:
            self._chain_sync_peer = peer_addr

        if peer_addr == self._chain_sync_peer:
            fetch_queue: asyncio.Queue[Point] = asyncio.Queue(maxsize=1000)
            _headers_received = 0

            async def _on_roll_forward(header: object, tip: object) -> None:
                nonlocal _headers_received
                _headers_received += 1

                from vibe.cardano.serialization.block import (
                    Era,
                    decode_block_header_raw,
                )
                from vibe.cardano.serialization.block import (
                    block_hash as compute_block_hash,
                )

                try:
                    if isinstance(header, (list, tuple)) and len(header) >= 2:
                        era_tag = header[0]
                        wrapped = header[1]
                        header_bytes = wrapped.value if hasattr(wrapped, "value") else wrapped

                        hdr_block_number = 0
                        try:
                            era = Era(era_tag)
                            hdr = decode_block_header_raw(header_bytes, era)
                            slot = hdr.slot
                            blk_hash = hdr.hash
                            hdr_block_number = getattr(hdr, "block_number", 0) or 0
                        except (NotImplementedError, ValueError):
                            inner = cbor2.loads(header_bytes)
                            hdr_body = inner[0]
                            slot = hdr_body[1] if isinstance(hdr_body, list) else 0
                            blk_hash = compute_block_hash(header_bytes)
                            # Extract block_number from header_body[0]
                            if isinstance(hdr_body, list) and len(hdr_body) > 0:
                                hdr_block_number = hdr_body[0] if isinstance(hdr_body[0], int) else 0

                        point = Point(slot=slot, hash=blk_hash)
                        await fetch_queue.put(point)

                        # Haskell-matching chain-sync header event for log correlation
                        if _headers_received % 1000 == 0:
                            logger.info(
                                "ChainSync.Client.DownloadedHeader: slot=%d hash=%s peer=%s",
                                slot, blk_hash.hex()[:16], str(peer.address),
                            )
                        else:
                            logger.debug(
                                "ChainSync.Client.DownloadedHeader: slot=%d hash=%s peer=%s",
                                slot, blk_hash.hex()[:16], str(peer.address),
                            )

                        # Track best known peer tip for forge loop
                        tip_block_no = getattr(tip, "block_number", 0) or 0
                        if tip_block_no > self.peer_tip_block_no_tvar.value:
                            self.peer_tip_block_no_tvar._write(tip_block_no)

                        if _headers_received % 1000 == 1 or _headers_received <= 5:
                            tip_block = tip_block_no
                            # Use the header's block_number (not session count)
                            # for accurate sync percentage when resuming
                            current_block = hdr_block_number
                            sync_pct = min(
                                (current_block / tip_block * 100)
                                if tip_block > 0
                                else 0.0,
                                100.0,
                            )
                            if _headers_received % 10000 == 1:
                                logger.info(
                                    "Chain-sync: %d headers (block #%d, %.1f%% synced) from %s",
                                    _headers_received,
                                    current_block,
                                    sync_pct,
                                    peer.address,
                                )
                            else:
                                logger.debug(
                                    "Chain-sync header #%d at slot %d block #%d (%.2f%% synced) from %s",
                                    _headers_received,
                                    slot,
                                    current_block,
                                    sync_pct,
                                    peer.address,
                                    extra={
                                        "event": "chainsync.header",
                                        "peer": str(peer.address),
                                        "header_num": _headers_received,
                                        "slot": slot,
                                        "block_number": current_block,
                                        "hash": blk_hash.hex()[:16],
                                        "sync_pct": round(sync_pct, 2),
                                        "tip_block": tip_block,
                                    },
                                )
                    else:
                        if _headers_received % 100 == 1:
                            logger.debug(
                                "Peer %s: header #%d (unparsed, tip=%s)",
                                peer.address,
                                _headers_received,
                                tip,
                            )
                except Exception as exc:
                    logger.warning("Peer %s: header parse error: %s", peer.address, exc)

            async def _on_roll_backward(point: object, tip: object) -> None:
                logger.info(
                    "Chain rollback to %s (tip=%s) from %s",
                    point,
                    tip,
                    peer.address,
                    extra={
                        "event": "chainsync.rollback",
                        "peer": str(peer.address),
                        "point": str(point),
                        "tip": str(tip),
                    },
                )

            # Scale pipeline depth with peer count
            pipeline_depth = 250 * max(1, len(self._config.peers))

            peer.protocol_tasks.append(asyncio.create_task(
                _safe_run(
                    run_chain_sync(
                        channels[CHAIN_SYNC_N2N_ID],
                        known_points=self._known_points,
                        on_roll_forward=_on_roll_forward,
                        on_roll_backward=_on_roll_backward,
                        stop_event=stop_event,
                        pipeline_depth=pipeline_depth,
                    ),
                    "chain-sync",
                ),
                name=f"chainsync-{peer.address}",
            ))

            # Range builder: drain fetch_queue Points into shared range_queue
            async def _range_builder() -> None:
                while not stop_event.is_set():
                    batch: list[Point] = []
                    try:
                        point = await asyncio.wait_for(fetch_queue.get(), timeout=0.5)
                    except TimeoutError:
                        continue
                    batch.append(point)
                    # Drain any additional points already queued
                    while len(batch) < 500:
                        try:
                            batch.append(fetch_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                    if batch:
                        await shared_range_queue.put((batch[0], batch[-1]))

            peer.protocol_tasks.append(asyncio.create_task(
                _safe_run(_range_builder(), "range-builder"),
                name=f"range-builder-{peer.address}",
            ))

            # Start shared processor task (non-producer only).
            # Producers use inline _on_block for synchronous nonce updates.
            is_producer = self._config.pool_keys is not None
            if self._processor_task is None and not is_producer:
                self._processor_task = asyncio.create_task(
                    _safe_run(
                        self._shared_block_processor(stop_event),
                        "block-processor",
                    ),
                    name="shared-block-processor",
                )

            # Nonce worker disabled -- on_block_adopted is called directly
            # in the shared block processor for immediate forge loop update.
            # The nonce worker pattern will be needed when blocks truly arrive
            # out-of-order from multiple peers and need sequential reordering.

        # --- Block-fetch ---
        # When producing blocks, use inline _on_block callback (old pattern)
        # so nonce updates happen synchronously in the block-fetch task.
        # This matches the 79fb652 architecture that achieved 35% forge rate.
        # Non-producing nodes use the shared queue for parallel multi-peer.
        is_producer = self._config.pool_keys is not None
        if is_producer and peer_addr != self._chain_sync_peer:
            # Non-chain-sync peers on a producer skip block-fetch but
            # MUST run keep-alive to prevent Haskell's inbound governor
            # from demoting the idle connection to Cold.
            from vibe.cardano.network.keepalive_protocol import run_keep_alive_client

            # Keep-alive client on initiator channel.
            peer.protocol_tasks.append(asyncio.create_task(
                _safe_run(
                    run_keep_alive_client(
                        channels[KEEP_ALIVE_PROTOCOL_ID],
                        stop_event=stop_event,
                        interval=10.0,
                        peer_info=peer_addr,
                    ),
                    "keep-alive",
                ),
                name=f"keepalive-{peer.address}",
            ))

            # Responder bundle on resp_channels (bidirectional support).
            from vibe.cardano.node.miniprotocol_bundle import launch_responder_bundle
            resp_tasks = await launch_responder_bundle(
                resp_channels, chain_db, None, stop_event, peer_info=peer_addr,
            )
            for t in resp_tasks:
                peer.protocol_tasks.append(t)

            peer.mux_task = mux_task
            return

        async def _peer_block_fetch() -> None:
            from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

            bf_channel = channels[BLOCK_FETCH_N2N_ID]
            tracker = self._range_tracker

            def _on_range_sent(r: tuple) -> None:
                if tracker is not None:
                    tracker.on_range_sent(peer_addr, r)

            def _on_range_complete(r: tuple) -> None:
                if tracker is not None:
                    tracker.on_range_complete(peer_addr, r)

            if is_producer:
                # Producer mode: inline _on_block callback for synchronous
                # nonce updates (matching commit 79fb652 architecture).
                _blocks_stored = [0]

                async def _on_block(block_cbor: bytes) -> None:
                    await self._process_block_inline(
                        block_cbor, chain_db, _blocks_stored,
                    )

                try:
                    await run_block_fetch_pipelined(
                        bf_channel,
                        range_queue=shared_range_queue,
                        on_block_received=_on_block,
                        stop_event=stop_event,
                        max_in_flight=20,
                        block_queue_size=500,
                    )
                except Exception as exc:
                    logger.warning("Peer %s: block-fetch error: %s", peer.address, exc)
                finally:
                    if tracker is not None:
                        tracker.on_peer_disconnect(peer_addr)
            else:
                # Non-producer: use shared queue for parallel multi-peer
                try:
                    await run_block_fetch_pipelined(
                        bf_channel,
                        range_queue=shared_range_queue,
                        on_block_received=None,
                        stop_event=stop_event,
                        max_in_flight=20,
                        block_queue_size=500,
                        block_queue=shared_block_queue,
                        on_range_sent=_on_range_sent,
                        on_range_complete=_on_range_complete,
                    )
                except Exception as exc:
                    logger.warning("Peer %s: block-fetch error: %s", peer.address, exc)
                finally:
                    if tracker is not None:
                        tracker.on_peer_disconnect(peer_addr)

        peer.protocol_tasks.append(asyncio.create_task(
            _safe_run(_peer_block_fetch(), "block-fetch"),
            name=f"blockfetch-{peer.address}",
        ))

        # Keep-Alive (protocol 8): periodic pings to keep connection alive.
        # Reduced interval from 90s to 10s because we don't yet run the
        # responder side of keep-alive -- the Haskell node pings us but
        # we can't respond. Frequent client pings keep the connection
        # alive from our side despite the missing responder.
        peer.protocol_tasks.append(asyncio.create_task(
            _safe_run(
                run_keep_alive_client(
                    channels[KEEP_ALIVE_PROTOCOL_ID],
                    stop_event=stop_event,
                    interval=10.0,
                    peer_info=peer_addr,
                ),
                "keep-alive",
            ),
            name=f"keepalive-{peer.address}",
        ))

        # Tx-Submission (protocol 4): respond to server's tx requests.
        # Server drives this protocol (pull-based). We provide empty
        # responses until the mempool is wired in.
        async def _on_request_tx_ids(
            blocking: bool, ack_count: int, req_count: int
        ) -> list[tuple[bytes, int]] | None:
            if blocking:
                # Block until we have txs -- for now, wait for stop.
                await stop_event.wait()
                return None
            return []

        async def _on_request_txs(
            txids: list[bytes],
        ) -> list[bytes]:
            return []

        peer.protocol_tasks.append(asyncio.create_task(
            _safe_run(
                run_tx_submission_client(
                    channels[TX_SUBMISSION_N2N_ID],
                    on_request_tx_ids=_on_request_tx_ids,
                    on_request_txs=_on_request_txs,
                    stop_event=stop_event,
                ),
                "tx-submission",
            ),
            name=f"txsub-{peer.address}",
        ))

        # Launch responder bundle on resp_channels (bidirectional support).
        # This lets the peer pull headers, blocks, and txs from us, and
        # responds to keep-alive pings — preventing Haskell's inbound
        # governor from demoting us to Cold.
        from vibe.cardano.node.miniprotocol_bundle import launch_responder_bundle
        resp_tasks = await launch_responder_bundle(
            resp_channels, chain_db, None, stop_event, peer_info=peer_addr,
        )
        for t in resp_tasks:
            peer.protocol_tasks.append(t)

        # Store the mux task -- peer_loop will await it instead of mux.run().
        peer.mux_task = mux_task

    async def _process_block_inline(
        self, block_cbor: bytes, chain_db: Any, blocks_stored: list[int],
    ) -> None:
        """Process a single block inline (producer mode).

        Same logic as _shared_block_processor but called synchronously
        from the block-fetch callback. This ensures nonce updates happen
        in the same task as block processing, matching the architecture
        at commit 79fb652 that achieved 35% forge rate.
        """
        import hashlib

        import cbor2pure as cbor2

        try:
            from vibe.cardano.serialization.block import (
                Era,
                decode_block_header_from_array,
            )

            raw_wire = block_cbor
            decoded = cbor2.loads(block_cbor)

            if hasattr(decoded, "tag") and decoded.tag == 24:
                inner = decoded.value
                if isinstance(inner, bytes):
                    raw_wire = inner
                    decoded = cbor2.loads(inner)
                else:
                    decoded = inner

            if isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[0], int):
                era_tag = decoded[0]
                block_body = decoded[1]
            elif hasattr(decoded, "tag"):
                era_tag = decoded.tag
                block_body = decoded.value
            else:
                raise ValueError(f"Unexpected block format: {type(decoded)}")

            raw_block = raw_wire
            era = Era(era_tag)
            try:
                hdr = decode_block_header_from_array(block_body, era)
                slot = hdr.slot
                block_number = hdr.block_number
                prev_hash = hdr.prev_hash or b"\x00" * 32
                block_hash = hdr.hash
                hdr_cbor = hdr.header_cbor
            except NotImplementedError:
                hdr_arr = block_body[0]
                hdr_body_arr = hdr_arr[0]
                block_number = hdr_body_arr[0]
                slot = hdr_body_arr[1]
                prev_hash = hdr_body_arr[2] or b"\x00" * 32
                from vibe.cardano.serialization.transaction import _normalize_cbor_types
                hdr_cbor = cbor2.dumps(_normalize_cbor_types(hdr_arr))
                block_hash = hashlib.blake2b(hdr_cbor, digest_size=32).digest()

            # Apply delegation certs (producer path)
            tx_bodies_raw = block_body[1] if len(block_body) > 1 else []
            has_txs = hasattr(tx_bodies_raw, "__len__") and len(tx_bodies_raw) > 0
            if has_txs and self._node_kernel is not None:
                try:
                    from vibe.cardano.serialization.transaction import decode_block_body_from_array
                    body = decode_block_body_from_array(block_body, era, skip_pycardano=True)
                    if body and body.transactions:
                        epoch = slot // self._config.epoch_length
                        self._node_kernel.apply_delegation_certs(body.transactions, epoch)
                except Exception:
                    pass

            # Detect epoch boundary and recompute stake distribution
            epoch = slot // self._config.epoch_length
            if not hasattr(self, '_last_inline_epoch'):
                self._last_inline_epoch = epoch
            if epoch > self._last_inline_epoch:
                self._last_inline_epoch = epoch
                if self._node_kernel is not None:
                    self._node_kernel.update_stake_distribution({})
                    logger.info(
                        "Epoch %d: stake distribution updated (%d pools)",
                        epoch, len(self._node_kernel.stake_distribution),
                    )

            if chain_db is not None:
                header_cbor_wrapped = [
                    max(0, era_tag - 1) if era_tag >= 2 else 0,
                    cbor2.CBORTag(24, hdr_cbor),
                ]
                hdr_vrf_out = getattr(hdr, "vrf_output", None)
                result = await chain_db.add_block_async(
                    slot=slot,
                    block_hash=block_hash,
                    predecessor_hash=prev_hash,
                    block_number=block_number,
                    cbor_bytes=raw_block,
                    header_cbor=header_cbor_wrapped,
                    vrf_output=hdr_vrf_out,
                )

                if result.adopted and self._block_received_event is not None:
                    self._block_received_event.set()

            blocks_stored[0] += 1
            tx_count = (
                len(block_body[1])
                if len(block_body) > 1 and isinstance(block_body[1], list)
                else 0
            )
            # Haskell-matching block-fetch event for log correlation
            if blocks_stored[0] % 1000 == 0:
                logger.info(
                    "BlockFetch.Client.CompletedBlockFetch: hash=%s slot=%d peer=inline",
                    block_hash.hex()[:16], slot,
                )
            else:
                logger.debug(
                    "BlockFetch.Client.CompletedBlockFetch: hash=%s slot=%d peer=inline",
                    block_hash.hex()[:16], slot,
                )
            if blocks_stored[0] % 1000 == 0:
                logger.info(
                    "Block-fetch: %d blocks stored (block #%d at slot %d, %s)",
                    blocks_stored[0], block_number, slot, era.name,
                )
            elif blocks_stored[0] % 100 == 1 or blocks_stored[0] <= 5:
                logger.debug(
                    "Block #%d stored at slot %d (%s, %d txs, %d bytes) [%d total]",
                    block_number, slot, era.name, tx_count,
                    len(raw_block), blocks_stored[0],
                )
        except Exception as exc:
            logger.error("Block process error: %s", exc, exc_info=True)

    async def _shared_block_processor(self, stop_event: asyncio.Event) -> None:
        """Pull blocks from shared_block_queue, decode, validate, and store.

        Single processor for all peers — blocks arrive in any order,
        ChainDB handles out-of-order chain selection.
        """
        import hashlib

        import cbor2pure as cbor2

        from vibe.cardano.consensus.hfc import validate_block
        from vibe.cardano.serialization.block import (
            Era,
            decode_block_header_from_array,
        )
        from vibe.cardano.serialization.transaction import (
            decode_block_body_from_array,
        )

        chain_db = self._chain_db
        block_queue = self._shared_block_queue
        _blocks_stored = 0

        while not stop_event.is_set():
            try:
                block_cbor = await asyncio.wait_for(block_queue.get(), timeout=0.5)
            except TimeoutError:
                continue

            try:
                raw_wire = block_cbor
                decoded = cbor2.loads(block_cbor)

                if hasattr(decoded, "tag") and decoded.tag == 24:
                    inner = decoded.value
                    if isinstance(inner, bytes):
                        raw_wire = inner
                        decoded = cbor2.loads(inner)
                    else:
                        decoded = inner

                if (
                    isinstance(decoded, list)
                    and len(decoded) >= 2
                    and isinstance(decoded[0], int)
                ):
                    era_tag = decoded[0]
                    block_body = decoded[1]
                elif hasattr(decoded, "tag"):
                    era_tag = decoded.tag
                    block_body = decoded.value
                else:
                    raise ValueError(f"Unexpected block format: {type(decoded)}")

                raw_block = raw_wire

                era = Era(era_tag)
                try:
                    hdr = decode_block_header_from_array(block_body, era)
                    slot = hdr.slot
                    block_number = hdr.block_number
                    prev_hash = hdr.prev_hash or b"\x00" * 32
                    block_hash = hdr.hash
                    hdr_cbor = hdr.header_cbor
                except NotImplementedError:
                    hdr_arr = block_body[0]
                    hdr_body_arr = hdr_arr[0]
                    block_number = hdr_body_arr[0]
                    slot = hdr_body_arr[1]
                    prev_hash = hdr_body_arr[2] or b"\x00" * 32
                    from vibe.cardano.serialization.transaction import (
                        _normalize_cbor_types,
                    )

                    hdr_cbor = cbor2.dumps(_normalize_cbor_types(hdr_arr))
                    block_hash = hashlib.blake2b(hdr_cbor, digest_size=32).digest()

                # Decode body only if block has transactions
                tx_bodies_raw = block_body[1] if len(block_body) > 1 else []
                has_txs = hasattr(tx_bodies_raw, "__len__") and len(tx_bodies_raw) > 0
                body = (
                    decode_block_body_from_array(block_body, era, skip_pycardano=True)
                    if has_txs
                    else None
                )
                if body and body.transactions:
                    errors = validate_block(
                        era=era,
                        block=body.transactions,
                        ledger_state=(chain_db.ledger_db if chain_db else None),
                        protocol_params=self._config.protocol_params,
                        current_slot=slot,
                    )
                    if errors:
                        if self._config.permissive_validation:
                            logger.warning(
                                "Block #%d slot=%d has %d validation errors (permissive): %s",
                                block_number, slot, len(errors), errors[:3],
                            )
                        else:
                            logger.warning(
                                "REJECTING block #%d slot=%d: %d errors: %s",
                                block_number, slot, len(errors), errors[:3],
                            )
                            continue

                # Apply ledger state (UTxO mutations)
                if body and chain_db is not None and chain_db.ledger_db is not None:
                    consumed: list[bytes] = []
                    created: list[tuple[bytes, dict]] = []
                    for tx in body.transactions:
                        if not tx.valid:
                            continue
                        tb = tx.body
                        inputs = getattr(tb, "inputs", None)
                        if inputs:
                            for inp in inputs:
                                tx_id = getattr(inp, "transaction_id", None)
                                tx_idx = getattr(inp, "index", None)
                                if tx_id is not None and tx_idx is not None:
                                    payload = getattr(tx_id, "payload", tx_id)
                                    if isinstance(payload, bytes) and len(payload) == 32:
                                        key = payload + tx_idx.to_bytes(2, "big")
                                        consumed.append(key)
                        outputs = getattr(tb, "outputs", None)
                        if outputs:
                            for idx, out in enumerate(outputs):
                                key = tx.tx_hash + idx.to_bytes(2, "big")
                                addr = str(getattr(out, "address", ""))
                                amount = getattr(out, "amount", 0)
                                if isinstance(amount, int):
                                    value = amount
                                else:
                                    value = getattr(amount, "coin", 0) or 0
                                datum_hash = getattr(out, "datum_hash", b"") or b""
                                if hasattr(datum_hash, "payload"):
                                    datum_hash = datum_hash.payload
                                created.append(
                                    (
                                        key,
                                        {
                                            "tx_hash": tx.tx_hash,
                                            "tx_index": idx,
                                            "address": addr,
                                            "value": int(value),
                                            "datum_hash": (
                                                datum_hash
                                                if isinstance(datum_hash, bytes)
                                                else b""
                                            ),
                                        },
                                    )
                                )
                    if consumed or created:
                        try:
                            chain_db.ledger_db.apply_block(
                                consumed, created, block_slot=slot,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Ledger apply error at slot %d: %s", slot, exc,
                            )

                # Apply delegation certificates for stake distribution.
                # Haskell tracks these in the ledger state and computes
                # a PoolDistr at each epoch boundary (mark/set/go rotation).
                # We apply certs to NodeKernel's delegation state and
                # recompute the stake distribution at epoch boundaries.
                if body and body.transactions and self._node_kernel is not None:
                    try:
                        epoch = slot // self._config.epoch_length
                        self._node_kernel.apply_delegation_certs(
                            body.transactions, epoch,
                        )
                    except Exception as exc:
                        logger.debug(
                            "Delegation cert error at slot %d: %s", slot, exc,
                        )

                # Detect epoch boundary and recompute stake distribution.
                # Haskell uses nesPd = ssStakeMarkPoolDistr from the NEWEPOCH
                # rule. We approximate by recomputing from delegation state
                # + UTxO at each epoch transition.
                epoch = slot // self._config.epoch_length
                if not hasattr(self, '_last_sync_epoch'):
                    self._last_sync_epoch = epoch
                if epoch > self._last_sync_epoch:
                    self._last_sync_epoch = epoch
                    if self._node_kernel is not None:
                        utxo_stakes = {}
                        if chain_db is not None and chain_db.ledger_db is not None:
                            try:
                                utxo_stakes = chain_db.ledger_db.get_stake_by_address()
                            except Exception:
                                pass
                        self._node_kernel.update_stake_distribution(utxo_stakes)
                        logger.info(
                            "Epoch %d: stake distribution updated (%d pools)",
                            epoch, len(self._node_kernel.stake_distribution),
                        )

                # Store in ChainDB (chain selection handles out-of-order)
                if chain_db is not None:
                    header_cbor_wrapped = [
                        max(0, era_tag - 1) if era_tag >= 2 else 0,
                        cbor2.CBORTag(24, hdr_cbor),
                    ]
                    hdr_vrf_out = getattr(hdr, "vrf_output", None)
                    result = await chain_db.add_block_async(
                        slot=slot,
                        block_hash=block_hash,
                        predecessor_hash=prev_hash,
                        block_number=block_number,
                        cbor_bytes=raw_block,
                        header_cbor=header_cbor_wrapped,
                        vrf_output=hdr_vrf_out,
                    )

                    if result.adopted and self._block_received_event is not None:
                        self._block_received_event.set()

                _blocks_stored += 1
                tx_count = (
                    len(block_body[1])
                    if len(block_body) > 1 and isinstance(block_body[1], list)
                    else 0
                )
                # Haskell-matching block-fetch event for log correlation
                if _blocks_stored % 1000 == 0:
                    logger.info(
                        "BlockFetch.Client.CompletedBlockFetch: hash=%s slot=%d peer=shared",
                        block_hash.hex()[:16], slot,
                    )
                else:
                    logger.debug(
                        "BlockFetch.Client.CompletedBlockFetch: hash=%s slot=%d peer=shared",
                        block_hash.hex()[:16], slot,
                    )
                if _blocks_stored % 1000 == 0:
                    logger.info(
                        "Block-fetch: %d blocks stored (block #%d at slot %d, %s)",
                        _blocks_stored, block_number, slot, era.name,
                    )
                elif _blocks_stored % 100 == 1 or _blocks_stored <= 5:
                    logger.debug(
                        "Block #%d stored at slot %d (%s, %d txs, %d bytes) [%d total]",
                        block_number, slot, era.name, tx_count,
                        len(raw_block), _blocks_stored,
                        extra={
                            "event": "block.stored",
                            "block_number": block_number,
                            "slot": slot,
                            "era": era.name,
                            "tx_count": tx_count,
                            "size_bytes": len(raw_block),
                            "hash": block_hash.hex()[:16],
                            "total_stored": _blocks_stored,
                        },
                    )
            except Exception as exc:
                logger.error(
                    "Block process error: %s", exc, exc_info=True,
                )
                import os

                if os.environ.get("VIBE_STRICT_SYNC", "").lower() in (
                    "1", "true", "yes",
                ):
                    raise

    async def _nonce_worker(self, stop_event: asyncio.Event) -> None:
        """No-op stub — nonce is now tracked atomically inside ChainDB.add_block().

        Retained to avoid attribute errors from existing task references.
        """
        return

    async def _disconnect_peer(self, peer: _PeerConnection) -> None:
        """Tear down a peer's multiplexer and bearer."""
        logger.info(
            "Peer %s disconnected",
            peer.address,
            extra={"event": "peer.disconnect", "peer": str(peer.address)},
        )
        # If this was the chain-sync peer, clear so next connecting peer takes over
        if self._chain_sync_peer == str(peer.address):
            logger.info(
                "Chain-sync peer %s disconnected — next peer will take over",
                peer.address,
            )
            self._chain_sync_peer = None
            # Reset processor/nonce tasks so they restart with the new chain-sync peer
            self._processor_task = None
            self._nonce_worker_task = None
        # Signal miniprotocol runners to stop.
        if peer.stop_event is not None:
            peer.stop_event.set()
            peer.stop_event = None
        # Cancel all tracked protocol tasks to prevent orphaned coroutines
        for t in peer.protocol_tasks:
            if not t.done():
                t.cancel()
        for t in peer.protocol_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        peer.protocol_tasks = []
        if peer.mux is not None:
            try:
                await peer.mux.close()
            except Exception:
                pass
            peer.mux = None
        if peer.mux_task is not None and not peer.mux_task.done():
            peer.mux_task.cancel()
            try:
                await peer.mux_task
            except (asyncio.CancelledError, Exception):
                pass
            peer.mux_task = None
        if peer.bearer is not None:
            try:
                await peer.bearer.close()
            except Exception:
                pass
            peer.bearer = None
        peer.connected = False
