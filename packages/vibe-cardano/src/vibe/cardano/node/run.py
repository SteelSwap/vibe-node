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

from vibe.core.multiplexer import Bearer, Multiplexer

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
    task: asyncio.Task[None] | None = None
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
    """

    __slots__ = ("_config", "_peers", "_stopped", "_tasks")

    def __init__(self, config: NodeConfig) -> None:
        self._config = config
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

                # Run the multiplexer -- blocks until disconnect.
                if peer.mux is not None:
                    await peer.mux.run()

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
        """Open TCP connection and set up multiplexer with N2N bundle."""
        logger.info("Connecting to peer %s", peer.address)
        reader, writer = await asyncio.open_connection(
            peer.address.host, peer.address.port
        )
        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=True)

        # Register N2N miniprotocol channels.
        for proto_id in N2N_PROTOCOL_IDS:
            mux.add_protocol(proto_id)

        peer.bearer = bearer
        peer.mux = mux
        peer.connected = True

        logger.info("Connected to peer %s", peer.address)

    async def _disconnect_peer(self, peer: _PeerConnection) -> None:
        """Tear down a peer's multiplexer and bearer."""
        if peer.mux is not None:
            try:
                await peer.mux.close()
            except Exception:
                pass
            peer.mux = None
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

    from vibe.cardano.forge.leader import check_leadership

    pool_keys = config.pool_keys

    logger.info("Forge loop started — checking leadership each slot")

    while not shutdown_event.is_set():
        try:
            slot = await slot_clock.wait_for_next_slot()
        except asyncio.CancelledError:
            return

        if shutdown_event.is_set():
            return

        # Leader check requires the epoch nonce and relative stake.
        # For now we use placeholder values -- these will be wired to
        # the real PraosState and stake distribution in integration.
        #
        # The forge loop structure is correct: wait for slot -> check
        # leadership -> forge if elected.  The actual VRF check and
        # block construction are delegated to the forge package.
        logger.debug("Slot %d: checking leadership", slot)

        # TODO(M5.8): Wire epoch_nonce from PraosState
        # TODO(M5.8): Wire relative_stake from stake distribution
        # TODO(M5.8): Wire mempool.get_txs_for_block() for block body
        # TODO(M5.8): Wire ChainDB.add_block() for storage
        # TODO(M5.8): Announce new block via chain-sync to peers


# ---------------------------------------------------------------------------
# Server listeners
# ---------------------------------------------------------------------------


async def _run_n2n_server(
    host: str,
    port: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the TCP listener for inbound N2N peer connections.

    For each incoming connection:
    1. Wrap in a Bearer
    2. Set up N2N mux with miniprotocol bundle
    3. Run the mux (blocks until disconnect)

    Haskell ref:
        ``Ouroboros.Network.Server2.run`` -- the server side of the
        connection manager that accepts inbound connections.

    Args:
        host: Bind address.
        port: Bind port.
        shutdown_event: Set when the node is shutting down.
    """
    mux_tasks: list[asyncio.Task[None]] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_info = writer.get_extra_info("peername")
        logger.info("N2N inbound connection from %s", peer_info)

        bearer = Bearer(reader, writer)
        mux = _setup_n2n_mux(bearer, is_initiator=False)

        try:
            await mux.run()
        except Exception as exc:
            logger.debug("N2N connection from %s ended: %s", peer_info, exc)
        finally:
            await mux.close()

    try:
        server = await asyncio.start_server(handle_connection, host, port)
        addrs = [s.getsockname() for s in server.sockets]
        logger.info("N2N server listening on %s", addrs)

        # Wait for shutdown signal.
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if "server" in locals():
            server.close()
            await server.wait_closed()
        # Cancel any active connection tasks.
        for task in mux_tasks:
            if not task.done():
                task.cancel()


async def _run_n2c_server(
    socket_path: str,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the Unix socket listener for N2C local client connections.

    Haskell ref:
        ``Ouroboros.Network.Snocket.localSnocket`` -- the local (Unix
        socket) snocket used for node-to-client connections.

    Args:
        socket_path: Path to the Unix domain socket.
        shutdown_event: Set when the node is shutting down.
    """

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        logger.info("N2C client connected via %s", socket_path)

        bearer = Bearer(reader, writer)
        mux = _setup_n2c_mux(bearer)

        try:
            await mux.run()
        except Exception as exc:
            logger.debug("N2C connection ended: %s", exc)
        finally:
            await mux.close()

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

    1. Creates the slot clock from genesis parameters
    2. Initialises the PeerManager with configured peers
    3. Starts the N2N TCP server for inbound connections
    4. Starts the N2C Unix socket server (if configured)
    5. Connects to outbound peers
    6. Runs the forge loop (if block-producing)
    7. Waits for shutdown signal (SIGTERM/SIGINT)
    8. Tears down all connections and servers gracefully

    Haskell ref:
        ``Ouroboros.Consensus.Node.run``
        ``Ouroboros.Consensus.NodeKernel.initNodeKernel``

    Args:
        config: The full node configuration.
    """
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
    peer_manager = PeerManager(config)
    for peer_addr in config.peers:
        peer_manager.add_peer(peer_addr)

    # --- Collect background tasks ---
    tasks: list[asyncio.Task[None]] = []

    # N2N TCP server
    tasks.append(
        asyncio.create_task(
            _run_n2n_server(config.host, config.port, shutdown_event),
            name="n2n-server",
        )
    )

    # N2C Unix socket server (if configured)
    if config.socket_path is not None:
        tasks.append(
            asyncio.create_task(
                _run_n2c_server(config.socket_path, shutdown_event),
                name="n2c-server",
            )
        )

    # Outbound peer connections
    await peer_manager.start()

    # Forge loop (block-producing nodes only)
    if config.is_block_producer:
        tasks.append(
            asyncio.create_task(
                _forge_loop(config, slot_clock, shutdown_event),
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

    logger.info("Node stopped")
