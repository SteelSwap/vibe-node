"""Node main loop -- top-level orchestration for the vibe Cardano node.

Ties together all subsystems: multiplexer, miniprotocols (N2N + N2C),
storage, mempool, consensus, and block forging into a single ``run_node``
entry point.

The architecture follows the Haskell node's ``Ouroboros.Consensus.Node.run``:

1. Initialise storage (ChainDB backed by ImmutableDB + VolatileDB + LedgerDB)
2. Initialise the mempool
3. Start TCP listener for inbound N2N peers
4. Start Unix socket listener for N2C local clients
5. Connect to configured outbound peers
6. For each connection, run the multiplexer with the appropriate miniprotocol bundle
7. Run the slot clock loop (block-producing nodes only):
   - Wait for next slot boundary
   - Check VRF leader eligibility
   - If elected: forge block, add to ChainDB, announce to peers
8. Handle SIGTERM/SIGINT for graceful shutdown

Haskell references:
    - Ouroboros.Consensus.Node (run, NodeKernel)
    - Ouroboros.Consensus.NodeKernel (initNodeKernel)
    - Ouroboros.Network.Diffusion (run)
    - Ouroboros.Consensus.BlockchainTime.WallClock.Default (defaultSystemTime)

Spec references:
    - Ouroboros Praos paper, Section 4 -- protocol execution
    - Ouroboros network spec, Chapter 2 -- connection management
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from vibe.core.multiplexer import Bearer, BearerClosedError, MiniProtocolChannel, Multiplexer, MuxClosedError

from vibe.cardano.consensus.slot_arithmetic import SlotConfig, slot_to_wall_clock, wall_clock_to_slot
from vibe.cardano.network.handshake import HANDSHAKE_PROTOCOL_ID
from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID, CHAIN_SYNC_N2C_ID
from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
from vibe.cardano.network.local_txsubmission import LOCAL_TX_SUBMISSION_ID
from vibe.cardano.network.local_statequery import LOCAL_STATE_QUERY_PROTOCOL_ID
from vibe.cardano.network.local_txmonitor import LOCAL_TX_MONITOR_ID

from .config import NodeConfig, PeerAddress

__all__ = ["PeerManager", "SlotClock", "run_node"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Miniprotocol ID constants -- collected here for the bundle builders
# ---------------------------------------------------------------------------

# N2N miniprotocol IDs (from the individual codec modules):
#   0 = Handshake
#   2 = Chain-Sync (N2N)
#   3 = Block-Fetch
#   4 = Tx-Submission (N2N)
#   8 = Keep-Alive
N2N_PROTOCOL_IDS: list[int] = [
    HANDSHAKE_PROTOCOL_ID,  # 0
    CHAIN_SYNC_N2N_ID,      # 2
    BLOCK_FETCH_N2N_ID,     # 3
    TX_SUBMISSION_N2N_ID,   # 4
    KEEP_ALIVE_PROTOCOL_ID, # 8
]

# N2C miniprotocol IDs:
#   0 = Handshake
#   5 = Local Chain-Sync (N2C)
#   6 = Local Tx-Submission
#   7 = Local State-Query
#   9 = Local Tx-Monitor
N2C_PROTOCOL_IDS: list[int] = [
    HANDSHAKE_PROTOCOL_ID,          # 0
    CHAIN_SYNC_N2C_ID,              # 5
    LOCAL_TX_SUBMISSION_ID,         # 6
    LOCAL_STATE_QUERY_PROTOCOL_ID,  # 7
    LOCAL_TX_MONITOR_ID,            # 9
]


# ---------------------------------------------------------------------------
# SlotClock
# ---------------------------------------------------------------------------


class SlotClock:
    """Asyncio-based slot clock that fires at each slot boundary.

    Uses ``slot_to_wall_clock`` from the consensus slot arithmetic module
    to compute the wall-clock time of each slot boundary, then sleeps
    until that time.

    Haskell ref:
        ``Ouroboros.Consensus.BlockchainTime.WallClock.Default.defaultSystemTime``
        The Haskell node uses STM's ``threadDelay`` between slot boundaries.

    Args:
        config: Slot configuration (system_start, slot_length, epoch_length).
    """

    __slots__ = ("_config", "_stopped")

    def __init__(self, config: SlotConfig) -> None:
        self._config = config
        self._stopped = False

    @property
    def slot_config(self) -> SlotConfig:
        """The underlying slot configuration."""
        return self._config

    def current_slot(self) -> int:
        """Return the current slot based on wall-clock time."""
        now = datetime.now(timezone.utc)
        return wall_clock_to_slot(now, self._config)

    async def wait_for_slot(self, target_slot: int) -> int:
        """Sleep until the start of ``target_slot``.

        If ``target_slot`` is in the past, returns immediately.

        Args:
            target_slot: The slot to wait for.

        Returns:
            The target slot number (for convenience in chaining).
        """
        target_time = slot_to_wall_clock(target_slot, self._config)
        now = datetime.now(timezone.utc)
        delay = (target_time - now).total_seconds()

        if delay > 0 and not self._stopped:
            await asyncio.sleep(delay)

        return target_slot

    async def wait_for_next_slot(self) -> int:
        """Sleep until the next slot boundary and return its slot number.

        Returns:
            The slot number of the slot we just entered.
        """
        current = self.current_slot()
        next_slot = current + 1
        return await self.wait_for_slot(next_slot)

    def stop(self) -> None:
        """Signal the clock to stop waiting."""
        self._stopped = True


# ---------------------------------------------------------------------------
# PeerManager
# ---------------------------------------------------------------------------


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
    connected: bool = False


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

    __slots__ = ("_config", "_chain_db", "_node_kernel", "_peers", "_stopped", "_tasks", "_known_points")

    def __init__(self, config: NodeConfig, chain_db: Any = None, node_kernel: Any = None) -> None:
        self._config = config
        self._chain_db = chain_db
        self._node_kernel = node_kernel
        self._peers: dict[str, _PeerConnection] = {}
        self._stopped = False
        self._tasks: list[asyncio.Task[None]] = []
        self._known_points: list[Any] = []

    @property
    def known_points(self) -> list[Any]:
        """Known chain points for chain-sync intersection (from snapshot or chain tip)."""
        return self._known_points

    def set_known_points(self, points: list[Any]) -> None:
        """Set known points for chain-sync to start from (instead of Origin)."""
        self._known_points = points

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
            task = asyncio.create_task(
                self._peer_loop(peer), name=f"peer-{peer_id}"
            )
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
        """
        while not self._stopped:
            try:
                await self._connect_peer(peer)
                # Reset backoff on successful connection.
                peer.reconnect_delay = 1.0

                # Mux is already running (started in _connect_peer after
                # handshake). Await the mux task until disconnect.
                if peer.mux_task is not None:
                    await peer.mux_task

            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "Peer %s: connection failed: %s (retry in %.1fs)",
                    peer.address,
                    exc,
                    peer.reconnect_delay,
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error(
                    "Peer %s: unexpected error: %s (retry in %.1fs)",
                    peer.address,
                    exc,
                    peer.reconnect_delay,
                    exc_info=True,
                )
            finally:
                peer.connected = False

            if self._stopped:
                return

            # Backoff before reconnect.
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

        logger.info("Connecting to peer %s", peer.address)
        reader, writer = await asyncio.open_connection(
            peer.address.host, peer.address.port
        )
        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=True)

        # Register N2N miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2N_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

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
            result = await run_handshake_client(
                hs_channel, self._config.network_magic
            )
            peer.connected = True
            logger.info(
                "Handshake with %s: version %d, magic %d",
                peer.address,
                result.version_number,
                result.version_data.network_magic,
            )
        except (HandshakeError, Exception) as exc:
            # Handshake failed — tear down the mux and propagate.
            await mux.close()
            try:
                await mux_task
            except Exception:
                pass
            raise ConnectionError(
                f"Handshake with {peer.address} failed: {exc}"
            ) from exc

        # --- Launch miniprotocol runners on their channels ---
        # Each runs as a background task for the lifetime of the connection.
        # The mux routes bytes between the bearer and these channel tasks.

        from vibe.cardano.network.chainsync_protocol import run_chain_sync
        from vibe.cardano.network.keepalive_protocol import run_keep_alive_client
        from vibe.cardano.network.txsubmission_protocol import run_tx_submission_client

        stop_event = asyncio.Event()
        peer.stop_event = stop_event

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

        # --- Sync pipeline: chain-sync → block-fetch → store ---
        # Chain-sync receives headers, extracts Point(slot, hash),
        # queues them for block-fetch. Block-fetch downloads full
        # block bodies and stores them in ChainDB.

        import hashlib

        import cbor2pure as cbor2

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch
        from vibe.cardano.network.chainsync import Point

        # Queue of points discovered by chain-sync, consumed by block-fetch.
        fetch_queue: asyncio.Queue[Point] = asyncio.Queue(maxsize=1000)
        chain_db = self._chain_db
        node_kernel = self._node_kernel
        _headers_received = 0

        async def _on_roll_forward(header: object, tip: object) -> None:
            nonlocal _headers_received
            _headers_received += 1

            # header = [era_tag, CBORTag(24, header_cbor)]
            # Extract slot and block hash from the wrapped header.
            try:
                if isinstance(header, (list, tuple)) and len(header) >= 2:
                    wrapped = header[1]  # CBORTag(24, inner_bytes)
                    header_bytes = wrapped.value if hasattr(wrapped, "value") else wrapped
                    inner = cbor2.loads(header_bytes)
                    hdr_body = inner[0]  # [block_number, slot, prev_hash, ...]
                    slot = hdr_body[1]
                    block_hash = hashlib.blake2b(
                        header_bytes, digest_size=32
                    ).digest()
                    point = Point(slot=slot, hash=block_hash)

                    # Queue for block-fetch
                    try:
                        fetch_queue.put_nowait(point)
                    except asyncio.QueueFull:
                        pass  # Drop if queue full — backpressure

                    if _headers_received % 100 == 1 or _headers_received <= 5:
                        logger.info(
                            "Peer %s: header #%d slot=%d hash=%s (tip=%s)",
                            peer.address,
                            _headers_received,
                            slot,
                            block_hash.hex()[:16],
                            tip,
                        )
                else:
                    if _headers_received % 100 == 1:
                        logger.debug(
                            "Peer %s: header #%d (unparsed, tip=%s)",
                            peer.address, _headers_received, tip,
                        )
            except Exception as exc:
                logger.debug("Peer %s: header parse error: %s", peer.address, exc)

        async def _on_roll_backward(point: object, tip: object) -> None:
            logger.info(
                "Peer %s: roll backward to %s (tip=%s)",
                peer.address, point, tip,
            )
            # TODO: ChainDB rollback to point

        asyncio.create_task(
            _safe_run(
                run_chain_sync(
                    channels[CHAIN_SYNC_N2N_ID],
                    known_points=[],  # Start from Origin
                    on_roll_forward=_on_roll_forward,
                    on_roll_backward=_on_roll_backward,
                    stop_event=stop_event,
                ),
                "chain-sync",
            ),
            name=f"chainsync-{peer.address}",
        )

        # Block-fetch worker: batches points from the queue into ranges,
        # fetches full block bodies, and stores them in ChainDB.
        async def _block_fetch_worker() -> None:
            from vibe.cardano.network.blockfetch_protocol import run_block_fetch_continuous

            bf_channel = channels[BLOCK_FETCH_N2N_ID]
            _blocks_stored = 0

            # Use a queue for block-fetch ranges. The chain-sync
            # _on_roll_forward fills fetch_queue with Points; we
            # convert to (from, to) range tuples for block-fetch.
            range_queue: asyncio.Queue[tuple] = asyncio.Queue()

            # Background task: drain fetch_queue Points into ranges
            async def _range_builder() -> None:
                while not stop_event.is_set():
                    batch: list[Point] = []
                    try:
                        point = await asyncio.wait_for(
                            fetch_queue.get(), timeout=1.0
                        )
                        batch.append(point)
                        while len(batch) < 100:
                            try:
                                batch.append(fetch_queue.get_nowait())
                            except asyncio.QueueEmpty:
                                break
                    except TimeoutError:
                        continue
                    if batch:
                        await range_queue.put((batch[0], batch[-1]))

            builder_task = asyncio.create_task(_range_builder())

            async def _on_block(block_cbor: bytes) -> None:
                nonlocal _blocks_stored
                logger.info(
                    "BLOCK-FETCH: received %d bytes, hex[:8]=%s",
                    len(block_cbor), block_cbor[:4].hex() if block_cbor else "empty",
                )

                from vibe.cardano.serialization.block import (
                    decode_block_header,
                    detect_era,
                )
                from vibe.cardano.serialization.transaction import (
                    decode_block_body,
                )
                from vibe.cardano.consensus.hfc import validate_block

                try:
                    # --- Parse block from block-fetch wire format ---
                    # Block-fetch delivers CBORTag(24, raw_bytes) or re-encoded
                    # CBOR. We need to get to the block array [header, ...].
                    decoded = cbor2.loads(block_cbor)

                    # Unwrap tag-24 if present
                    if hasattr(decoded, 'tag') and decoded.tag == 24:
                        inner = decoded.value
                        if isinstance(inner, bytes):
                            decoded = cbor2.loads(inner)
                        else:
                            decoded = inner

                    # Block-fetch format: [era_int, block_body]
                    # where block_body = [header, tx_bodies, tx_witnesses, aux, invalid_txs]
                    if isinstance(decoded, list) and len(decoded) >= 2 and isinstance(decoded[0], int):
                        era_tag = decoded[0]
                        block_body = decoded[1]
                    elif hasattr(decoded, 'tag'):
                        era_tag = decoded.tag
                        block_body = decoded.value
                    else:
                        raise ValueError(f"Unexpected block format: {type(decoded)}")

                    # block_body = [header, tx_bodies, tx_witnesses, aux, ...]
                    hdr = block_body[0]  # [header_body, kes_sig]
                    hdr_body = hdr[0]
                    block_number = hdr_body[0]
                    slot = hdr_body[1]
                    prev_hash = hdr_body[2] or b"\x00" * 32
                    hdr_cbor = cbor2.dumps(hdr)
                    block_hash = hashlib.blake2b(hdr_cbor, digest_size=32).digest()

                    # Build raw_block for storage (era-tagged CBOR)
                    raw_block = cbor2.dumps(cbor2.CBORTag(era_tag, block_body))

                    from vibe.cardano.serialization.block import Era
                    era = Era(era_tag)

                    # --- Validate block transactions ---
                    body = decode_block_body(raw_block)
                    if body.transactions:
                        errors = validate_block(
                            era=era,
                            block=body.transactions,
                            ledger_state=(
                                chain_db.ledger_db if chain_db else None
                            ),
                            protocol_params=self._config.protocol_params,
                            current_slot=slot,
                        )
                        if errors:
                            if self._config.permissive_validation:
                                logger.warning(
                                    "Peer %s: block #%d slot=%d has %d "
                                    "validation errors (permissive): %s",
                                    peer.address, block_number, slot,
                                    len(errors), errors[:3],
                                )
                            else:
                                logger.warning(
                                    "Peer %s: REJECTING block #%d "
                                    "slot=%d: %d errors: %s",
                                    peer.address, block_number, slot,
                                    len(errors), errors[:3],
                                )
                                return  # Don't store invalid blocks

                    # --- Apply ledger state (UTxO mutations) ---
                    if chain_db is not None and chain_db.ledger_db is not None:
                        consumed: list[bytes] = []
                        created: list[tuple[bytes, dict]] = []
                        for tx in body.transactions:
                            if not tx.valid:
                                continue
                            tb = tx.body
                            # Extract consumed inputs
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
                            # Extract created outputs
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
                                    created.append((key, {
                                        "tx_hash": tx.tx_hash,
                                        "tx_index": idx,
                                        "address": addr,
                                        "value": int(value),
                                        "datum_hash": datum_hash if isinstance(datum_hash, bytes) else b"",
                                    }))
                        if consumed or created:
                            try:
                                chain_db.ledger_db.apply_block(
                                    consumed, created, block_slot=slot,
                                )
                            except Exception as exc:
                                logger.debug(
                                    "Peer %s: ledger apply error: %s",
                                    peer.address, exc,
                                )

                    # --- Store in ChainDB ---
                    if chain_db is not None:
                        await chain_db.add_block(
                            slot=slot,
                            block_hash=block_hash,
                            predecessor_hash=prev_hash,
                            block_number=block_number,
                            cbor_bytes=raw_block,
                        )

                    # --- Add to NodeKernel for serving to peers ---
                    if node_kernel is not None:
                        node_kernel.add_block(
                            slot=slot,
                            block_hash=block_hash,
                            block_number=block_number,
                            # HFC N-ary sum index: Byron=0, Shelley=1, ..., Conway=6
                            # CBOR era tags: Byron_Main=0, Byron_EBB=1, Shelley=2, ..., Conway=7
                            # Mapping: cbor_tag >= 2 → hfc_index = cbor_tag - 1
                            #          cbor_tag 0 or 1 → hfc_index = 0 (Byron)
                            header_cbor=[max(0, era_tag - 1) if era_tag >= 2 else 0, cbor2.CBORTag(24, hdr_cbor)],
                            block_cbor=raw_block,
                            predecessor_hash=prev_hash,
                        )

                    _blocks_stored += 1
                    if _blocks_stored % 100 == 1 or _blocks_stored <= 5:
                        logger.info(
                            "Peer %s: stored block #%d slot=%d era=%s "
                            "txs=%d hash=%s [%d total]",
                            peer.address, block_number, slot,
                            era.name, len(block_body[1]) if len(block_body) > 1 and isinstance(block_body[1], list) else 0,
                            block_hash.hex()[:16], _blocks_stored,
                        )
                except Exception as exc:
                    logger.error(
                        "Peer %s: block process error: %s",
                        peer.address, exc, exc_info=True,
                    )

            try:
                await run_block_fetch_continuous(
                    bf_channel,
                    range_queue=range_queue,
                    on_block_received=_on_block,
                    stop_event=stop_event,
                )
            except Exception as exc:
                logger.debug(
                    "Peer %s: block-fetch error: %s", peer.address, exc
                )
            finally:
                builder_task.cancel()

        asyncio.create_task(
            _safe_run(_block_fetch_worker(), "block-fetch"),
            name=f"blockfetch-{peer.address}",
        )

        # Keep-Alive (protocol 8): periodic pings to keep connection alive.
        asyncio.create_task(
            _safe_run(
                run_keep_alive_client(
                    channels[KEEP_ALIVE_PROTOCOL_ID],
                    stop_event=stop_event,
                ),
                "keep-alive",
            ),
            name=f"keepalive-{peer.address}",
        )

        # Tx-Submission (protocol 4): respond to server's tx requests.
        # Server drives this protocol (pull-based). We provide empty
        # responses until the mempool is wired in.
        async def _on_request_tx_ids(
            blocking: bool, ack_count: int, req_count: int
        ) -> list[tuple[bytes, int]] | None:
            if blocking:
                # Block until we have txs — for now, wait for stop.
                await stop_event.wait()
                return None
            return []

        async def _on_request_txs(
            txids: list[bytes],
        ) -> list[bytes]:
            return []

        asyncio.create_task(
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
        )

        # Store the mux task — peer_loop will await it instead of mux.run().
        peer.mux_task = mux_task

    async def _disconnect_peer(self, peer: _PeerConnection) -> None:
        """Tear down a peer's multiplexer and bearer."""
        # Signal miniprotocol runners to stop.
        if peer.stop_event is not None:
            peer.stop_event.set()
            peer.stop_event = None
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


# ---------------------------------------------------------------------------
# Inbound connection handlers
# ---------------------------------------------------------------------------


def _setup_n2n_mux(bearer: Bearer, is_initiator: bool) -> Multiplexer:
    """Create a Multiplexer with the N2N miniprotocol bundle registered.

    Args:
        bearer: The TCP bearer for this connection.
        is_initiator: True if we initiated the connection.

    Returns:
        A configured Multiplexer ready to run().
    """
    mux = Multiplexer(bearer, is_initiator=is_initiator)
    for proto_id in N2N_PROTOCOL_IDS:
        mux.add_protocol(proto_id)
    return mux


def _setup_n2c_mux(bearer: Bearer) -> Multiplexer:
    """Create a Multiplexer with the N2C miniprotocol bundle registered.

    N2C connections are always responder-side (we are the node, the
    client connects to us via Unix socket).

    Args:
        bearer: The Unix socket bearer for this connection.

    Returns:
        A configured Multiplexer ready to run().
    """
    mux = Multiplexer(bearer, is_initiator=False)
    for proto_id in N2C_PROTOCOL_IDS:
        mux.add_protocol(proto_id)
    return mux


# ---------------------------------------------------------------------------
# Forge loop
# ---------------------------------------------------------------------------


async def _forge_loop(
    config: NodeConfig,
    slot_clock: SlotClock,
    shutdown_event: asyncio.Event,
    chain_db: Any = None,
    node_kernel: Any = None,
    mempool: Any = None,
) -> None:
    """Slot-by-slot leader check and block forging loop.

    For each slot:
    1. Wait for the slot boundary
    2. Check VRF leader eligibility
    3. If elected: forge a block from mempool, add to ChainDB, announce

    This function runs only on block-producing nodes (config.pool_keys is set).

    Haskell ref:
        ``Ouroboros.Consensus.Node.forgeBlock``
        ``Ouroboros.Consensus.Shelley.Node.Forging.forgeShelleyBlock``

    Args:
        config: Node configuration with pool keys.
        slot_clock: The slot clock for timing.
        shutdown_event: Set when the node is shutting down.
    """
    if config.pool_keys is None:
        return

    import hashlib

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import cbor2pure as cbor2

    from vibe.cardano.crypto.kes import (
        CARDANO_KES_DEPTH,
        kes_derive_vk,
        kes_keygen,
    )
    from vibe.cardano.crypto.ocert import OperationalCert, ocert_signed_payload
    from vibe.cardano.forge.block import forge_block
    from vibe.cardano.forge.leader import check_leadership

    pool_keys = config.pool_keys

    # --- Initialise forge credentials ---
    # Prefer deserialized KES key from cardano-cli skey file; fall back to
    # fresh random keygen (for testing without real key files).
    if pool_keys.kes_sk:
        from vibe.cardano.crypto.kes_serialization import deserialize_kes_sk
        try:
            kes_sk = deserialize_kes_sk(pool_keys.kes_sk, CARDANO_KES_DEPTH)
            kes_vk = kes_derive_vk(kes_sk)
            logger.info("Loaded KES key from pool configuration (%d bytes)", len(pool_keys.kes_sk))
        except Exception as exc:
            logger.warning("Failed to deserialize KES key (%s), generating fresh", exc)
            kes_sk = kes_keygen(CARDANO_KES_DEPTH)
            kes_vk = kes_derive_vk(kes_sk)
    else:
        kes_sk = kes_keygen(CARDANO_KES_DEPTH)
        kes_vk = kes_derive_vk(kes_sk)

    # Load opcert from pool_keys if available, otherwise sign a fresh one.
    if pool_keys.ocert:
        import cbor2pure as _cbor2
        try:
            ocert_data = _cbor2.loads(pool_keys.ocert)
            # opcert = [[kes_vk, cert_count, kes_period, cold_sig], vrf_keyhash]
            inner = ocert_data[0] if isinstance(ocert_data, list) else ocert_data
            ocert = OperationalCert(
                kes_vk=bytes(inner[0]),
                cert_count=inner[1],
                kes_period_start=inner[2],
                cold_sig=bytes(inner[3]),
            )
            logger.info("Loaded operational certificate (cert_count=%d)", ocert.cert_count)
        except Exception as exc:
            logger.warning("Failed to parse opcert (%s), signing fresh", exc)
            ocert_payload = ocert_signed_payload(kes_vk, cert_count=0, kes_period_start=0)
            cold_sk_ed = Ed25519PrivateKey.from_private_bytes(pool_keys.cold_sk)
            cold_sig = cold_sk_ed.sign(ocert_payload)
            ocert = OperationalCert(kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig)
    elif pool_keys.cold_sk:
        ocert_payload = ocert_signed_payload(kes_vk, cert_count=0, kes_period_start=0)
        cold_sk_ed = Ed25519PrivateKey.from_private_bytes(pool_keys.cold_sk)
        cold_sig = cold_sk_ed.sign(ocert_payload)
        ocert = OperationalCert(kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig)
    else:
        logger.error("No opcert or cold signing key — cannot forge blocks")
        return

    # Epoch nonce from NodeKernel (seeded from genesis hash) or fallback.
    epoch_nonce = (
        node_kernel.epoch_nonce.value
        if node_kernel is not None
        else hashlib.blake2b(config.network_magic.to_bytes(4, "big"), digest_size=32).digest()
    )

    # Compute pool ID (Blake2b-224 of cold VK) for stake lookup.
    pool_id = hashlib.blake2b(pool_keys.cold_vk, digest_size=28).digest()
    if node_kernel is not None and node_kernel.stake_distribution:
        pool_stake = node_kernel.stake_distribution.get(pool_id, 0)
        total_stake = sum(node_kernel.stake_distribution.values())
        relative_stake = pool_stake / total_stake if total_stake > 0 else 0.0
        logger.info("Pool stake from distribution: %.4f%%", relative_stake * 100)
    else:
        relative_stake = 1.0 / 3.0  # Fallback for testing

    # --- KES key evolution to current period ---
    from vibe.cardano.crypto.kes import kes_update
    from vibe.cardano.crypto.ocert import slot_to_kes_period

    slots_per_kes = config.slots_per_kes_period
    current_kes_period = slot_to_kes_period(
        slot_clock.current_slot(), slots_per_kes_period=slots_per_kes
    ) - ocert.kes_period_start

    if current_kes_period < 0:
        current_kes_period = 0
    if current_kes_period > 0:
        for p in range(current_kes_period):
            evolved = kes_update(kes_sk, p)
            if evolved is None:
                logger.error("KES key expired at period %d", p)
                return
            kes_sk = evolved
        logger.info("KES key evolved to period %d", current_kes_period)

    _current_kes_period = current_kes_period

    # Track chain tip for prev_hash linkage.
    # Read from ChainDB or NodeKernel so we build on the received chain.
    prev_block_number = 0
    prev_header_hash: bytes | None = None
    if chain_db is not None:
        try:
            tip = await chain_db.get_tip()
            if tip is not None:
                prev_header_hash = tip[1]  # (slot, hash, block_number)
                prev_block_number = tip[2]  # Real block number
                logger.info("Forge: building on chain tip slot=%d block=%d", tip[0], tip[2])
        except Exception:
            pass
    blocks_forged = 0

    logger.info(
        "Forge loop started — pool VRF vk=%s, KES vk=%s, stake=%.2f%%, kes_period=%d",
        pool_keys.vrf_vk.hex()[:16],
        kes_vk.hex()[:16],
        relative_stake * 100,
        _current_kes_period,
    )

    while not shutdown_event.is_set():
        try:
            slot = await slot_clock.wait_for_next_slot()
        except asyncio.CancelledError:
            return

        # Evolve KES key if period has advanced
        new_kes_period = slot_to_kes_period(slot, slots_per_kes_period=slots_per_kes) - ocert.kes_period_start
        if new_kes_period > _current_kes_period:
            for p in range(_current_kes_period, new_kes_period):
                evolved = kes_update(kes_sk, p)
                if evolved is None:
                    logger.error("KES key expired at period %d", p)
                    return
                kes_sk = evolved
            _current_kes_period = new_kes_period
            logger.info("KES key evolved to period %d", _current_kes_period)

        if shutdown_event.is_set():
            return

        # VRF leader check
        proof = check_leadership(
            slot=slot,
            vrf_sk=pool_keys.vrf_sk,
            pool_vrf_vk=pool_keys.vrf_vk,
            relative_stake=relative_stake,
            active_slot_coeff=config.active_slot_coeff,
            epoch_nonce=epoch_nonce,
        )

        if proof is None:
            continue

        # --- Read current chain state (per-slot, not cached) ---
        # Haskell: mkCurrentBlockContext reads ChainDB.getCurrentChain each slot
        if chain_db is not None:
            try:
                tip = await chain_db.get_tip()
                if tip is not None:
                    tip_slot, tip_hash, tip_block_number = tip
                    if slot - tip_slot > 10:
                        # Still syncing — too far behind (like forecast failure)
                        continue
                    prev_header_hash = tip_hash
                    prev_block_number = tip_block_number  # Real block number, not slot
                elif slot > 10:
                    continue
            except Exception:
                pass

        # Re-read epoch nonce from kernel (evolves at epoch boundaries)
        if node_kernel is not None:
            epoch_nonce = node_kernel.epoch_nonce.value

        # Re-read stake distribution (changes at epoch boundaries)
        if node_kernel is not None and node_kernel.stake_distribution:
            pool_stake = node_kernel.stake_distribution.get(pool_id, 0)
            total_stake = sum(node_kernel.stake_distribution.values())
            relative_stake = pool_stake / total_stake if total_stake > 0 else relative_stake

        # Elected! Forge the block.
        try:
            forged = forge_block(
                leader_proof=proof,
                prev_block_number=prev_block_number,
                prev_header_hash=prev_header_hash,
                mempool_txs=[
                    vtx.tx_cbor
                    for vtx in (await mempool.get_txs_for_block(65536))
                ] if mempool is not None else [],
                kes_sk=kes_sk,
                kes_period=_current_kes_period,
                ocert=ocert,
                pool_vk=pool_keys.cold_vk,
                vrf_vk=pool_keys.vrf_vk,
            )

            blocks_forged += 1
            prev_block_number = forged.block.block_number
            prev_header_hash = forged.block.block_hash

            # Store in ChainDB
            if chain_db is not None:
                try:
                    await chain_db.add_block(
                        slot=forged.block.slot,
                        block_hash=forged.block.block_hash,
                        predecessor_hash=prev_header_hash if prev_block_number > 1 else b"\x00" * 32,
                        block_number=forged.block.block_number,
                        cbor_bytes=forged.cbor,
                    )
                except Exception as exc:
                    logger.warning("Failed to store forged block: %s", exc)

            # Add to NodeKernel so chain-sync/block-fetch servers
            # can serve this block to connected peers.
            if node_kernel is not None:
                node_kernel.add_block(
                    slot=forged.block.slot,
                    block_hash=forged.block.block_hash,
                    block_number=forged.block.block_number,
                    header_cbor=[6, cbor2.CBORTag(24, forged.block.header_cbor)],  # HFC index 6=Conway
                    block_cbor=forged.cbor,
                    predecessor_hash=prev_header_hash or b"\x00" * 32,
                    is_forged=True,
                )

            logger.info(
                "FORGED BLOCK %d at slot %d (%d bytes, hash=%s) "
                "[%d total]",
                forged.block.block_number,
                forged.block.slot,
                len(forged.cbor),
                forged.block.block_hash.hex()[:16],
                blocks_forged,
            )
        except Exception as exc:
            logger.error("Failed to forge block at slot %d: %s", slot, exc)


# ---------------------------------------------------------------------------
# Server listeners
# ---------------------------------------------------------------------------


async def _run_n2n_server(
    host: str,
    port: int,
    network_magic: int,
    node_kernel: Any,
    mempool: Any,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the TCP listener for inbound N2N peer connections.

    For each incoming connection:
    1. Wrap in a Bearer + Multiplexer
    2. Run handshake responder on channel 0
    3. Launch chain-sync server, keep-alive server, block-fetch server
    4. Run until disconnect or shutdown

    Haskell ref:
        ``Ouroboros.Network.Server2.run`` -- the server side of the
        connection manager that accepts inbound connections.

    Args:
        host: Bind address.
        port: Bind port.
        network_magic: Network magic for handshake negotiation.
        shutdown_event: Set when the node is shutting down.
    """
    from vibe.cardano.network.blockfetch_protocol import run_block_fetch_server
    from vibe.cardano.network.chainsync_protocol import run_chain_sync_server
    from vibe.cardano.network.handshake_protocol import (
        HandshakeError,
        run_handshake_server,
    )
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_server

    conn_tasks: list[asyncio.Task[None]] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_info = writer.get_extra_info("peername")
        logger.info("N2N inbound connection from %s", peer_info)

        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=False)

        # Register N2N miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2N_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

        # Start the mux in background.
        mux_task = asyncio.create_task(mux.run(), name=f"mux-inbound-{peer_info}")
        stop = asyncio.Event()

        try:
            # Run handshake responder on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            result = await run_handshake_server(hs_channel, network_magic)
            logger.info(
                "N2N inbound %s: handshake accepted v%d",
                peer_info, result.version_number,
            )

            # Helper: wrap server coroutines so MuxClosedError on
            # peer disconnect doesn't produce "Task exception never retrieved"
            async def _safe_server(coro, name: str) -> None:
                try:
                    await coro
                except (MuxClosedError, BearerClosedError):
                    logger.debug("N2N inbound %s: %s disconnected", peer_info, name)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.debug("N2N inbound %s: %s error: %s", peer_info, name, exc)

            # Launch keep-alive server (echo pings back).
            asyncio.create_task(
                _safe_server(
                    run_keep_alive_server(
                        channels[KEEP_ALIVE_PROTOCOL_ID], stop_event=stop,
                    ),
                    "keep-alive",
                ),
                name=f"ka-server-{peer_info}",
            )

            # Launch chain-sync server (serve our headers to the peer).
            if node_kernel is not None:
                asyncio.create_task(
                    _safe_server(
                        run_chain_sync_server(
                            channels[CHAIN_SYNC_N2N_ID],
                            chain_provider=node_kernel,
                            stop_event=stop,
                        ),
                        "chain-sync",
                    ),
                    name=f"cs-server-{peer_info}",
                )

                # Launch block-fetch server (serve full blocks to the peer).
                asyncio.create_task(
                    _safe_server(
                        run_block_fetch_server(
                            channels[BLOCK_FETCH_N2N_ID],
                            block_provider=node_kernel,
                            stop_event=stop,
                        ),
                        "block-fetch",
                    ),
                    name=f"bf-server-{peer_info}",
                )

            # Launch tx-submission server (pull txs from peer into mempool).
            if mempool is not None:
                from vibe.cardano.network.txsubmission_protocol import (
                    run_tx_submission_server,
                )

                async def _on_tx_ids(txids: list[tuple[bytes, int]]) -> None:
                    logger.debug(
                        "N2N inbound %s: received %d tx IDs",
                        peer_info, len(txids),
                    )

                async def _on_txs(txs: list[bytes]) -> None:
                    for tx_cbor in txs:
                        try:
                            await mempool.add_tx(tx_cbor)
                            logger.info(
                                "N2N inbound %s: added tx to mempool (%d bytes)",
                                peer_info, len(tx_cbor),
                            )
                        except Exception as exc:
                            logger.debug(
                                "N2N inbound %s: tx rejected: %s",
                                peer_info, exc,
                            )

                asyncio.create_task(
                    _safe_server(
                        run_tx_submission_server(
                            channels[TX_SUBMISSION_N2N_ID],
                            on_tx_ids_received=_on_tx_ids,
                            on_txs_received=_on_txs,
                            stop_event=stop,
                        ),
                        "tx-submission",
                    ),
                    name=f"txsub-server-{peer_info}",
                )

            # Wait for mux to end (peer disconnect) or shutdown.
            done, _ = await asyncio.wait(
                [mux_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

        except (HandshakeError, ConnectionError, MuxClosedError) as exc:
            logger.debug("N2N inbound %s: %s", peer_info, exc)
        except Exception as exc:
            logger.debug("N2N inbound %s ended: %s", peer_info, exc)
        finally:
            stop.set()
            await mux.close()
            if not mux_task.done():
                mux_task.cancel()
                try:
                    await mux_task
                except (asyncio.CancelledError, Exception):
                    pass

    try:
        server = await asyncio.start_server(handle_connection, host, port)
        addrs = [s.getsockname() for s in server.sockets]
        logger.info("N2N server listening on %s", addrs)

        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if "server" in locals():
            server.close()
            await server.wait_closed()
        for task in conn_tasks:
            if not task.done():
                task.cancel()


async def _run_n2c_server(
    socket_path: str,
    network_magic: int,
    chain_db: Any,
    ledger_db: Any,
    mempool: Any,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the Unix socket listener for N2C local client connections.

    For each incoming connection:
    1. Wrap in a Bearer + Multiplexer
    2. Run N2C handshake responder on channel 0
    3. Launch all 4 N2C miniprotocol servers on their channels
    4. Run until disconnect or shutdown

    Haskell ref:
        ``Ouroboros.Network.Snocket.localSnocket`` -- the local (Unix
        socket) snocket used for node-to-client connections.

    Args:
        socket_path: Path to the Unix domain socket.
        network_magic: Network magic for handshake negotiation.
        chain_db: The ChainDB instance (for local chain-sync).
        ledger_db: The LedgerDB instance (for local state-query).
        shutdown_event: Set when the node is shutting down.
    """
    from vibe.cardano.network.handshake_protocol import (
        HandshakeError,
        run_handshake_server_n2c,
    )
    from vibe.cardano.network.local_chainsync_protocol import create_local_chainsync_server
    from vibe.cardano.network.local_statequery_protocol import run_local_state_query_server
    from vibe.cardano.network.local_txmonitor_protocol import run_local_tx_monitor_server
    from vibe.cardano.network.local_txsubmission_protocol import run_local_tx_submission_server

    conn_tasks: list[asyncio.Task[None]] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        logger.info("N2C client connected via %s", socket_path)

        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=False)

        # Register N2C miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2C_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

        # Start the mux in background.
        mux_task = asyncio.create_task(mux.run(), name="mux-n2c")
        stop = asyncio.Event()

        try:
            # Run N2C handshake responder on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            hs_result = await run_handshake_server_n2c(hs_channel, network_magic)
            logger.info(
                "N2C handshake accepted v%d (query=%s)",
                hs_result.version_number,
                hs_result.version_data.query,
            )

            # Launch local chain-sync server (protocol 5).
            if chain_db is not None:
                cs_server = create_local_chainsync_server(
                    channels[CHAIN_SYNC_N2C_ID], chain_db,
                )
                asyncio.create_task(
                    cs_server.run(),
                    name="n2c-local-chainsync",
                )
            else:
                logger.warning(
                    "N2C local chain-sync: skipped (no ChainDB available)"
                )

            # Launch local tx-submission server (protocol 6).
            async def _validate_and_add_tx(era_id: int, tx_bytes: bytes) -> bytes | None:
                if mempool is not None:
                    try:
                        await mempool.add_tx(tx_bytes)
                        return None  # None = accepted
                    except Exception as exc:
                        return str(exc).encode()  # Error bytes = rejected
                return b"mempool not available"

            asyncio.create_task(
                run_local_tx_submission_server(
                    channels[LOCAL_TX_SUBMISSION_ID],
                    validate_tx=_validate_and_add_tx,
                ),
                name="n2c-local-txsubmission",
            )

            # Launch local state-query server (protocol 7).
            if ledger_db is not None:
                asyncio.create_task(
                    run_local_state_query_server(
                        channels[LOCAL_STATE_QUERY_PROTOCOL_ID],
                        ledgerdb=ledger_db,
                    ),
                    name="n2c-local-statequery",
                )
            else:
                logger.warning(
                    "N2C local state-query: skipped (no LedgerDB available)"
                )

            # Launch local tx-monitor server (protocol 9).
            _monitor_snapshot = None
            _monitor_idx = 0

            async def _acquire_snapshot() -> int:
                nonlocal _monitor_snapshot, _monitor_idx
                if mempool is not None:
                    _monitor_snapshot = await mempool.get_snapshot()
                    _monitor_idx = 0
                    return _monitor_snapshot.slot if _monitor_snapshot else 0
                return 0

            async def _get_next_tx() -> tuple[int, bytes] | None:
                nonlocal _monitor_idx
                if _monitor_snapshot and _monitor_idx < len(_monitor_snapshot.tickets):
                    ticket = _monitor_snapshot.tickets[_monitor_idx]
                    _monitor_idx += 1
                    return (ticket.validated_tx.tx_size, ticket.validated_tx.tx_cbor)
                return None

            async def _has_tx(tx_id: bytes) -> bool:
                if mempool is not None:
                    return await mempool.has_tx(tx_id)
                return False

            async def _mempool_sizes() -> tuple[int, int, int]:
                if mempool is not None:
                    return (mempool.size, mempool.total_size_bytes, mempool.capacity_bytes)
                return (0, 0, 0)

            asyncio.create_task(
                run_local_tx_monitor_server(
                    channels[LOCAL_TX_MONITOR_ID],
                    acquire_snapshot=_acquire_snapshot,
                    get_next_tx=_get_next_tx,
                    has_tx_in_snapshot=_has_tx,
                    get_mempool_sizes=_mempool_sizes,
                ),
                name="n2c-local-txmonitor",
            )

            # Wait for mux to end (client disconnect) or shutdown.
            done, _ = await asyncio.wait(
                [mux_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

        except (HandshakeError, ConnectionError, MuxClosedError) as exc:
            logger.debug("N2C connection ended: %s", exc)
        except Exception as exc:
            logger.debug("N2C connection ended: %s", exc)
        finally:
            stop.set()
            await mux.close()
            if not mux_task.done():
                mux_task.cancel()
                try:
                    await mux_task
                except (asyncio.CancelledError, Exception):
                    pass

    try:
        server = await asyncio.start_unix_server(handle_connection, socket_path)
        logger.info("N2C server listening on %s", socket_path)

        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if "server" in locals():
            server.close()
            await server.wait_closed()
        for task in conn_tasks:
            if not task.done():
                task.cancel()


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _install_signal_handlers(
    shutdown_event: asyncio.Event,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Install SIGTERM and SIGINT handlers for graceful shutdown.

    Haskell ref:
        ``Ouroboros.Consensus.Node`` uses async exceptions (throwTo)
        for shutdown.  We use asyncio Events instead -- cleaner in
        Python's cooperative concurrency model.

    Args:
        shutdown_event: The event to set on signal receipt.
        loop: The running event loop.
    """

    def _signal_handler(sig: signal.Signals) -> None:
        logger.info("Received signal %s — initiating graceful shutdown", sig.name)
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler, sig)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler.
            pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_node(config: NodeConfig) -> None:
    """Top-level node entry point -- start everything and run until shutdown.

    This is the Python equivalent of ``Ouroboros.Consensus.Node.run`` from
    the Haskell node.  It:

    1. Initialises storage (ChainDB = ImmutableDB + VolatileDB + LedgerDB)
    2. Creates the slot clock from genesis parameters
    3. Initialises the PeerManager with configured peers
    4. Starts the N2N TCP server for inbound connections
    5. Starts the N2C Unix socket server (if configured)
    6. Connects to outbound peers
    7. Runs the forge loop (if block-producing)
    8. Waits for shutdown signal (SIGTERM/SIGINT)
    9. Tears down all connections and servers gracefully

    Haskell ref:
        ``Ouroboros.Consensus.Node.run``
        ``Ouroboros.Consensus.NodeKernel.initNodeKernel``

    Args:
        config: The full node configuration.
    """
    import hashlib

    from vibe.cardano.storage import ChainDB, ImmutableDB, LedgerDB, VolatileDB

    from .kernel import NodeKernel

    logger.info(
        "Starting vibe-node (network_magic=%d, host=%s:%d, "
        "block_producer=%s, peers=%d)",
        config.network_magic,
        config.host,
        config.port,
        config.is_block_producer,
        len(config.peers),
    )

    # --- Shutdown event and signal handlers ---
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(shutdown_event, loop)

    # --- Storage ---
    db_path = config.db_path
    db_path.mkdir(parents=True, exist_ok=True)

    immutable_db = ImmutableDB(
        base_dir=db_path / "immutable",
        epoch_size=config.epoch_length,
    )
    volatile_db = VolatileDB(db_dir=db_path / "volatile")
    ledger_db = LedgerDB(
        k=config.security_param,
        snapshot_dir=db_path / "ledger-snapshots",
    )
    chain_db = ChainDB(
        immutable_db=immutable_db,
        volatile_db=volatile_db,
        ledger_db=ledger_db,
        k=config.security_param,
    )

    # --- Mithril snapshot import (if configured and chain is empty) ---
    if config.mithril_snapshot_path is not None:
        tip = await chain_db.get_tip()
        if tip is None:
            logger.info("Importing Mithril snapshot from %s", config.mithril_snapshot_path)
            try:
                from vibe.cardano.sync import import_mithril_snapshot
                await import_mithril_snapshot(
                    snapshot_dir=config.mithril_snapshot_path,
                    immutable_db=immutable_db,
                )
                logger.info("Mithril snapshot import complete")
            except Exception as exc:
                logger.warning("Mithril import failed: %s", exc)
        else:
            logger.info("ChainDB has data, skipping Mithril import")

    tip = await chain_db.get_tip()
    # Try to restore ledger state from latest snapshot
    snapshot_dir = db_path / "ledger-snapshots"
    if snapshot_dir.exists():
        snapshots = sorted(snapshot_dir.glob("*.arrow"), reverse=True)
        if snapshots:
            try:
                from vibe.cardano.storage.ledger import SnapshotHandle
                handle = SnapshotHandle(
                    snapshot_id="restore",
                    metadata={"path": str(snapshots[0])},
                )
                await ledger_db.restore(handle)
                logger.info("Restored ledger from snapshot: %d UTxOs", ledger_db.utxo_count)
            except Exception as exc:
                logger.warning("Snapshot restore failed: %s", exc)

    if tip is not None:
        logger.info("ChainDB loaded: tip at slot %d (hash=%s)", tip[0], tip[1].hex()[:16])
    else:
        logger.info("ChainDB loaded: empty (starting from genesis)")

    # --- Mempool ---
    from vibe.cardano.mempool import Mempool, MempoolConfig
    from vibe.cardano.mempool.validator import LedgerTxValidator

    tx_validator = LedgerTxValidator(ledger_db)
    mempool = Mempool(
        config=MempoolConfig(),
        validator=tx_validator,
        current_slot=0,
    )
    logger.info("Mempool initialised (capacity=%d bytes)", mempool.capacity_bytes)

    # --- NodeKernel: shared state for protocol servers ---
    node_kernel = NodeKernel()
    nonce_seed = config.genesis_hash or hashlib.blake2b(
        config.network_magic.to_bytes(4, "big"), digest_size=32
    ).digest()
    node_kernel.init_nonce(nonce_seed, config.epoch_length)
    if config.initial_pool_stakes:
        node_kernel.update_stake_distribution(config.initial_pool_stakes)
    if config.protocol_params:
        node_kernel.init_protocol_params(config.protocol_params)

    # --- Slot clock ---
    slot_config = SlotConfig(
        system_start=config.system_start,
        slot_length=config.slot_length,
        epoch_length=config.epoch_length,
    )
    slot_clock = SlotClock(slot_config)

    current_slot = slot_clock.current_slot()
    logger.info("Current slot: %d", current_slot)

    # --- Peer manager ---
    peer_manager = PeerManager(config, chain_db=chain_db, node_kernel=node_kernel)
    for peer_addr in config.peers:
        peer_manager.add_peer(peer_addr)

    # --- Collect background tasks ---
    tasks: list[asyncio.Task[None]] = []

    # N2N TCP server
    tasks.append(
        asyncio.create_task(
            _run_n2n_server(
                config.host, config.port, config.network_magic,
                node_kernel, mempool, shutdown_event,
            ),
            name="n2n-server",
        )
    )

    # N2C Unix socket server (if configured)
    if config.socket_path is not None:
        tasks.append(
            asyncio.create_task(
                _run_n2c_server(
                    config.socket_path,
                    config.network_magic,
                    chain_db,
                    ledger_db,
                    mempool,
                    shutdown_event,
                ),
                name="n2c-server",
            )
        )

    # Outbound peer connections
    await peer_manager.start()

    # Forge loop (block-producing nodes only)
    if config.is_block_producer:
        tasks.append(
            asyncio.create_task(
                _forge_loop(config, slot_clock, shutdown_event, chain_db, node_kernel, mempool),
                name="forge-loop",
            )
        )

    # Periodic ledger snapshots for crash recovery
    async def _snapshot_loop() -> None:
        interval = getattr(config, 'snapshot_interval_slots', 2000)
        interval_secs = interval * config.slot_length
        last_slot = 0
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(interval_secs)
            except asyncio.CancelledError:
                return
            if shutdown_event.is_set():
                return
            current = slot_clock.current_slot()
            if current - last_slot >= interval:
                try:
                    handle = await ledger_db.snapshot()
                    last_slot = current
                    logger.info(
                        "Ledger snapshot at slot %d: %d UTxOs",
                        current, ledger_db.utxo_count,
                    )
                except Exception as exc:
                    logger.warning("Snapshot failed: %s", exc)

    tasks.append(
        asyncio.create_task(_snapshot_loop(), name="snapshot-loop")
    )

    logger.info("Node started — waiting for shutdown signal")

    # --- Wait for shutdown ---
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    # --- Graceful shutdown ---
    logger.info("Shutting down...")

    slot_clock.stop()
    await peer_manager.stop()

    for task in tasks:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # Close storage
    chain_db.close()
    logger.info("Node stopped")
