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

from vibe.cardano.consensus.slot_arithmetic import SlotConfig, slot_to_wall_clock, wall_clock_to_slot

from .config import NodeConfig, PeerAddress
from .forge_loop import forge_loop as _forge_loop
from .inbound_server import (
    N2N_PROTOCOL_IDS,
    N2C_PROTOCOL_IDS,
    setup_n2n_mux as _setup_n2n_mux,
    setup_n2c_mux as _setup_n2c_mux,
    run_n2n_server as _run_n2n_server,
    run_n2c_server as _run_n2c_server,
)
from .peer_manager import PeerManager, _PeerConnection

__all__ = ["PeerManager", "SlotClock", "run_node"]

logger = logging.getLogger(__name__)


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
# Periodic ledger snapshots
# ---------------------------------------------------------------------------


async def _snapshot_loop(
    ledger_db: Any,
    slot_clock: Any,
    interval_slots: int,
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically snapshot the ledger for crash recovery.

    Takes a snapshot every ``interval_slots`` slots of progress.
    Failures are logged but do not crash the loop.
    """
    interval_secs = interval_slots * getattr(
        getattr(slot_clock, "slot_config", None), "slot_length", 1.0
    )
    last_slot = 0
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(interval_secs)
        except asyncio.CancelledError:
            return
        if shutdown_event.is_set():
            return
        current = slot_clock.current_slot() if callable(getattr(slot_clock, "current_slot", None)) else 0
        if current - last_slot >= interval_slots:
            try:
                await ledger_db.snapshot()
                last_slot = current
                utxo_count = getattr(ledger_db, "utxo_count", 0)
                logger.info("Ledger snapshot at slot %d (%d UTxOs)", current, utxo_count, extra={"event": "ledger.snapshot", "slot": current, "utxo_count": utxo_count})
            except Exception as exc:
                logger.warning("Snapshot failed: %s", exc)


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
        logger.info("Received %s — shutting down", sig.name, extra={"event": "node.signal", "signal": sig.name})
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

    logger.info("Starting vibe-node (magic=%d, %s:%d, producer=%s, %d peers)", config.network_magic, config.host, config.port, config.is_block_producer, len(config.peers), extra={"event": "node.starting", "network_magic": config.network_magic, "host": config.host, "port": config.port, "block_producer": config.is_block_producer, "peer_count": len(config.peers)})

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
            logger.info("Importing Mithril snapshot from %s", config.mithril_snapshot_path, extra={"event": "mithril.import.start", "path": str(config.mithril_snapshot_path)})
            try:
                from vibe.cardano.sync import import_mithril_snapshot
                await import_mithril_snapshot(
                    snapshot_dir=config.mithril_snapshot_path,
                    immutable_db=immutable_db,
                )
                logger.info("Mithril snapshot import complete", extra={"event": "mithril.import.done"})
            except Exception as exc:
                logger.warning("Mithril import failed: %s", exc)
        else:
            logger.info("ChainDB has data, skipping Mithril import", extra={"event": "mithril.import.skip"})

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
                logger.info("Ledger restored from snapshot (%d UTxOs)", ledger_db.utxo_count, extra={"event": "ledger.restored", "utxo_count": ledger_db.utxo_count})
            except Exception as exc:
                logger.warning("Snapshot restore failed: %s", exc)

    if tip is not None:
        logger.info("ChainDB loaded: tip at slot %d (hash=%s)", tip[0], tip[1].hex()[:16], extra={"event": "chaindb.loaded", "slot": tip[0], "hash": tip[1].hex()[:16]})
    else:
        logger.info("ChainDB loaded: empty (starting from genesis)", extra={"event": "chaindb.loaded", "slot": 0, "empty": True})

    # --- Mempool ---
    from vibe.cardano.mempool import Mempool, MempoolConfig
    from vibe.cardano.mempool.validator import LedgerTxValidator

    tx_validator = LedgerTxValidator(ledger_db)
    mempool = Mempool(
        config=MempoolConfig(),
        validator=tx_validator,
        current_slot=0,
    )
    logger.info("Mempool initialised (capacity=%d bytes)", mempool.capacity_bytes, extra={"event": "mempool.init", "capacity_bytes": mempool.capacity_bytes})

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
    logger.info("Current slot: %d", current_slot, extra={"event": "node.slot", "slot": current_slot})

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
    snapshot_interval = getattr(config, 'snapshot_interval_slots', 2000)
    tasks.append(
        asyncio.create_task(
            _snapshot_loop(ledger_db, slot_clock, snapshot_interval, shutdown_event),
            name="snapshot-loop",
        )
    )

    logger.info("Node started — waiting for shutdown signal", extra={"event": "node.started"})

    # --- Wait for shutdown ---
    try:
        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    # --- Graceful shutdown ---
    logger.info("Shutting down...", extra={"event": "node.shutdown"})

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
    logger.info("Node stopped", extra={"event": "node.stopped"})
