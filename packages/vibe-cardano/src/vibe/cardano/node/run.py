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

from vibe.core.multiplexer import Bearer, MiniProtocolChannel, Multiplexer, MuxClosedError

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

    __slots__ = ("_config", "_chain_db", "_node_kernel", "_peers", "_stopped", "_tasks")

    def __init__(self, config: NodeConfig, chain_db: Any = None, node_kernel: Any = None) -> None:
        self._config = config
        self._chain_db = chain_db
        self._node_kernel = node_kernel
        self._peers: dict[str, _PeerConnection] = {}
        self._stopped = False
        self._tasks: list[asyncio.Task[None]] = []

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

        import cbor2

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
            bf_channel = channels[BLOCK_FETCH_N2N_ID]
            _blocks_stored = 0

            while not stop_event.is_set():
                # Collect a batch of points (up to 100, or whatever's available)
                batch: list[Point] = []
                try:
                    # Wait for at least one point
                    point = await asyncio.wait_for(
                        fetch_queue.get(), timeout=1.0
                    )
                    batch.append(point)
                    # Drain up to 99 more without blocking
                    while len(batch) < 100:
                        try:
                            batch.append(fetch_queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                except TimeoutError:
                    continue

                if not batch or stop_event.is_set():
                    continue

                # Build range: (first_point, last_point)
                ranges = [(batch[0], batch[-1])]

                async def _on_block(block_cbor: bytes) -> None:
                    nonlocal _blocks_stored
                    try:
                        # Parse block header for storage metadata.
                        block_data = cbor2.loads(block_cbor)
                        hdr = block_data[0]  # [header_body, kes_sig]
                        hdr_body = hdr[0]
                        block_number = hdr_body[0]
                        slot = hdr_body[1]
                        prev_hash = hdr_body[2] or b"\x00" * 32
                        hdr_cbor = cbor2.dumps(hdr)
                        block_hash = hashlib.blake2b(
                            hdr_cbor, digest_size=32
                        ).digest()

                        # TODO(M5.20): Full block validation through
                        # era-aware validate_block() once the block
                        # deserialization pipeline is wired. For now
                        # we store all received blocks (the Haskell
                        # node already validated them).

                        # Store in ChainDB.
                        if chain_db is not None:
                            await chain_db.add_block(
                                slot=slot,
                                block_hash=block_hash,
                                predecessor_hash=prev_hash,
                                block_number=block_number,
                                cbor_bytes=block_cbor,
                            )

                        # Add to NodeKernel for serving to peers.
                        if node_kernel is not None:
                            node_kernel.add_block(
                                slot=slot,
                                block_hash=block_hash,
                                block_number=block_number,
                                header_cbor=hdr_cbor,
                                block_cbor=block_cbor,
                            )

                        _blocks_stored += 1
                        if _blocks_stored % 100 == 1 or _blocks_stored <= 5:
                            logger.info(
                                "Peer %s: stored block #%d slot=%d hash=%s "
                                "[%d total]",
                                peer.address, block_number, slot,
                                block_hash.hex()[:16], _blocks_stored,
                            )
                    except Exception as exc:
                        logger.debug(
                            "Peer %s: block store error: %s",
                            peer.address, exc,
                        )

                try:
                    await run_block_fetch(
                        bf_channel,
                        ranges=ranges,
                        on_block_received=_on_block,
                        stop_event=stop_event,
                    )
                except Exception as exc:
                    logger.debug(
                        "Peer %s: block-fetch error: %s", peer.address, exc
                    )

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
        import cbor2 as _cbor2
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

    # Pool3 has 1/3 relative stake in the devnet genesis.
    # In production this comes from the stake distribution snapshot.
    relative_stake = 1.0 / 3.0

    # Track chain tip for prev_hash linkage.
    prev_block_number = 0
    prev_header_hash: bytes | None = None
    blocks_forged = 0

    logger.info(
        "Forge loop started — pool VRF vk=%s, KES vk=%s, stake=%.2f%%",
        pool_keys.vrf_vk.hex()[:16],
        kes_vk.hex()[:16],
        relative_stake * 100,
    )

    while not shutdown_event.is_set():
        try:
            slot = await slot_clock.wait_for_next_slot()
        except asyncio.CancelledError:
            return

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

        # Elected! Forge the block.
        try:
            forged = forge_block(
                leader_proof=proof,
                prev_block_number=prev_block_number,
                prev_header_hash=prev_header_hash,
                mempool_txs=[],  # Empty blocks for now
                kes_sk=kes_sk,
                kes_period=0,
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
                    header_cbor=forged.block.header_cbor,
                    block_cbor=forged.cbor,
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

            # Launch keep-alive server (echo pings back).
            asyncio.create_task(
                run_keep_alive_server(
                    channels[KEEP_ALIVE_PROTOCOL_ID], stop_event=stop,
                ),
                name=f"ka-server-{peer_info}",
            )

            # Launch chain-sync server (serve our headers to the peer).
            if node_kernel is not None:
                asyncio.create_task(
                    run_chain_sync_server(
                        channels[CHAIN_SYNC_N2N_ID],
                        chain_provider=node_kernel,
                        stop_event=stop,
                    ),
                    name=f"cs-server-{peer_info}",
                )

                # Launch block-fetch server (serve full blocks to the peer).
                asyncio.create_task(
                    run_block_fetch_server(
                        channels[BLOCK_FETCH_N2N_ID],
                        block_provider=node_kernel,
                        stop_event=stop,
                    ),
                    name=f"bf-server-{peer_info}",
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
            # Requires a validate_tx callback. Provide a stub that rejects
            # all txs until the mempool is wired up.
            async def _stub_validate_tx(era_id: int, tx_bytes: bytes) -> bytes | None:
                logger.warning(
                    "N2C local tx-submission: rejecting tx (mempool not wired)"
                )
                return b"mempool not available"

            asyncio.create_task(
                run_local_tx_submission_server(
                    channels[LOCAL_TX_SUBMISSION_ID],
                    validate_tx=_stub_validate_tx,
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
            # Requires mempool callbacks. Provide stubs until mempool is wired.
            async def _stub_acquire_snapshot() -> int:
                return 0

            async def _stub_get_next_tx() -> tuple[int, bytes] | None:
                return None

            async def _stub_has_tx(tx_id: bytes) -> bool:
                return False

            async def _stub_mempool_sizes() -> tuple[int, int, int]:
                return (0, 0, 0)

            asyncio.create_task(
                run_local_tx_monitor_server(
                    channels[LOCAL_TX_MONITOR_ID],
                    acquire_snapshot=_stub_acquire_snapshot,
                    get_next_tx=_stub_get_next_tx,
                    has_tx_in_snapshot=_stub_has_tx,
                    get_mempool_sizes=_stub_mempool_sizes,
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

    tip = await chain_db.get_tip()
    if tip is not None:
        logger.info("ChainDB loaded: tip at slot %d (hash=%s)", tip[0], tip[1].hex()[:16])
    else:
        logger.info("ChainDB loaded: empty (starting from genesis)")

    # --- NodeKernel: shared state for protocol servers ---
    node_kernel = NodeKernel()
    nonce_seed = config.genesis_hash or hashlib.blake2b(
        config.network_magic.to_bytes(4, "big"), digest_size=32
    ).digest()
    node_kernel.init_nonce(nonce_seed, config.epoch_length)

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
                node_kernel, shutdown_event,
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
                _forge_loop(config, slot_clock, shutdown_event, chain_db, node_kernel),
                name="forge-loop",
            )
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
