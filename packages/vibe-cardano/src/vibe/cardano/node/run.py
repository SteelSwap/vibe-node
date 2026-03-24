"""Node main loop -- three-thread orchestration for the vibe Cardano node.

Three OS threads:
    Thread 1 (main): Forge loop — slot-by-slot leadership + block forging
    Thread 2 (daemon): Receive — peer connections, chain-sync/block-fetch clients
    Thread 3 (daemon): Serve — inbound connections, chain-sync/block-fetch servers

Shared state (ChainDB, NodeKernel) is protected by RWLock.
The forge thread wakes on slot boundaries OR block arrival (threading.Event).

Haskell references:
    - Ouroboros.Consensus.Node (run, NodeKernel)
    - The Haskell node uses per-concern OS threads with STM coordination.
    - Our 3-thread model consolidates per-peer threads into two asyncio
      event loops. See docs/superpowers/specs/2026-03-24-threading-design.md.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
from datetime import datetime, timezone
from typing import Any

from vibe.cardano.consensus.slot_arithmetic import SlotConfig, slot_to_wall_clock, wall_clock_to_slot
from vibe.core.rwlock import RWLock

from .config import NodeConfig, PeerAddress
from .forge_loop import forge_loop
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
# SlotClock (still used by receive/serve threads for slot queries)
# ---------------------------------------------------------------------------


class SlotClock:
    """Slot clock for wall-clock to slot conversion.

    The forge thread uses its own slot timing via threading.Event.
    This class is retained for the receive/serve threads' slot queries.
    """

    __slots__ = ("_config", "_stopped")

    def __init__(self, config: SlotConfig) -> None:
        self._config = config
        self._stopped = False

    @property
    def slot_config(self) -> SlotConfig:
        return self._config

    def current_slot(self) -> int:
        now = datetime.now(timezone.utc)
        return wall_clock_to_slot(now, self._config)

    async def wait_for_slot(self, target_slot: int) -> int:
        target_time = slot_to_wall_clock(target_slot, self._config)
        now = datetime.now(timezone.utc)
        delay = (target_time - now).total_seconds()
        if delay > 0 and not self._stopped:
            await asyncio.sleep(delay)
        return target_slot

    async def wait_for_next_slot(self) -> int:
        current = self.current_slot()
        return await self.wait_for_slot(current + 1)

    def stop(self) -> None:
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
    """Periodically snapshot the ledger for crash recovery."""
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
                logger.info("Ledger snapshot at slot %d (%d UTxOs)", current, utxo_count)
            except Exception as exc:
                logger.warning("Snapshot failed: %s", exc)


# ---------------------------------------------------------------------------
# Thread 2: RECEIVE — block reception from peers
# ---------------------------------------------------------------------------


def _run_receive_thread(
    config: NodeConfig,
    chain_db: Any,
    node_kernel: Any,
    block_received_event: threading.Event,
    shutdown_event: threading.Event,
    slot_clock: Any,
    ledger_db: Any,
) -> None:
    """Thread 2: block reception (peer_manager + outbound connections).

    Creates its own asyncio event loop. Runs peer_manager which
    connects to Haskell peers, runs chain-sync clients, and
    block-fetch clients. Sets block_received_event when a new
    block is adopted.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _main() -> None:
        # Asyncio shutdown event for this thread's tasks
        async_shutdown = asyncio.Event()

        # Watch the threading.Event and bridge to asyncio
        async def _watch_shutdown():
            while not shutdown_event.is_set():
                await asyncio.sleep(0.1)
            async_shutdown.set()

        asyncio.create_task(_watch_shutdown(), name="shutdown-watcher")

        peer_manager = PeerManager(
            config,
            chain_db=chain_db,
            node_kernel=node_kernel,
            block_received_event=block_received_event,
        )
        for peer_addr in config.peers:
            peer_manager.add_peer(peer_addr)

        await peer_manager.start()

        # Snapshot loop runs on receive thread (needs slot_clock)
        snapshot_interval = getattr(config, "snapshot_interval_slots", 2000)
        asyncio.create_task(
            _snapshot_loop(ledger_db, slot_clock, snapshot_interval, async_shutdown),
            name="snapshot-loop",
        )

        # Wait for shutdown
        await async_shutdown.wait()
        await peer_manager.stop()

    try:
        loop.run_until_complete(_main())
    except Exception as exc:
        logger.error("Receive thread error: %s", exc, exc_info=True)
    finally:
        loop.close()
        logger.info("Receive thread stopped")


# ---------------------------------------------------------------------------
# Thread 3: SERVE — block serving to peers
# ---------------------------------------------------------------------------


def _run_serve_thread(
    config: NodeConfig,
    chain_db: Any,
    node_kernel: Any,
    mempool: Any,
    shutdown_event: threading.Event,
) -> None:
    """Thread 3: block serving (inbound N2N + N2C servers).

    Creates its own asyncio event loop. Runs the TCP listener for
    inbound peer connections and the Unix socket for local clients.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _main() -> None:
        async_shutdown = asyncio.Event()

        async def _watch_shutdown():
            while not shutdown_event.is_set():
                await asyncio.sleep(0.1)
            async_shutdown.set()

        asyncio.create_task(_watch_shutdown(), name="shutdown-watcher")

        tasks: list[asyncio.Task[None]] = []

        # N2N TCP server
        tasks.append(
            asyncio.create_task(
                _run_n2n_server(
                    config.host, config.port, config.network_magic,
                    node_kernel, mempool, async_shutdown,
                    chain_db=chain_db,
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
                        getattr(chain_db, "ledger_db", None),
                        mempool,
                        async_shutdown,
                    ),
                    name="n2c-server",
                )
            )

        # Wait for shutdown
        await async_shutdown.wait()

        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    try:
        loop.run_until_complete(_main())
    except Exception as exc:
        logger.error("Serve thread error: %s", exc, exc_info=True)
    finally:
        loop.close()
        logger.info("Serve thread stopped")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_node(config: NodeConfig) -> None:
    """Top-level node entry point — initialise storage, spawn 3 threads.

    Storage initialisation is async (Mithril import, ledger restore).
    After init, the node runs on 3 OS threads:
        Thread 1 (main): Forge loop
        Thread 2 (daemon): Block reception
        Thread 3 (daemon): Block serving

    Haskell ref: Ouroboros.Consensus.Node.run
    """
    import hashlib

    from vibe.cardano.storage import ChainDB, ImmutableDB, LedgerDB, VolatileDB

    from .kernel import NodeKernel

    logger.info(
        "Starting vibe-node (magic=%d, %s:%d, producer=%s, %d peers)",
        config.network_magic, config.host, config.port,
        config.is_block_producer, len(config.peers),
    )

    # --- Storage (async init for Mithril/snapshots) ---
    db_path = config.db_path
    db_path.mkdir(parents=True, exist_ok=True)

    # Create shared locks
    chaindb_lock = RWLock()
    kernel_lock = RWLock()

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
        lock=chaindb_lock,
    )

    # Mithril snapshot import
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
            except Exception as exc:
                logger.warning("Mithril import failed: %s", exc)

    tip = await chain_db.get_tip()
    # Ledger restore
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
                logger.info("Ledger restored from snapshot (%d UTxOs)", ledger_db.utxo_count)
            except Exception as exc:
                logger.warning("Snapshot restore failed: %s", exc)

    if tip is not None:
        logger.info("ChainDB loaded: tip at slot %d", tip[0])
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

    # --- NodeKernel ---
    node_kernel = NodeKernel(chain_db=chain_db, lock=kernel_lock)
    nonce_seed = config.genesis_hash or hashlib.blake2b(
        config.network_magic.to_bytes(4, "big"), digest_size=32
    ).digest()
    node_kernel.init_nonce(
        nonce_seed, config.epoch_length,
        security_param=config.security_param,
        active_slot_coeff=config.active_slot_coeff,
    )
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
    logger.info("Current slot: %d", slot_clock.current_slot())

    # --- Threading primitives ---
    block_received = threading.Event()
    shutdown = threading.Event()

    # --- Thread 2: RECEIVE ---
    receive_thread = threading.Thread(
        target=_run_receive_thread,
        args=(config, chain_db, node_kernel, block_received, shutdown,
              slot_clock, ledger_db),
        daemon=True,
        name="vibe-receive",
    )

    # --- Thread 3: SERVE ---
    serve_thread = threading.Thread(
        target=_run_serve_thread,
        args=(config, chain_db, node_kernel, mempool, shutdown),
        daemon=True,
        name="vibe-serve",
    )

    # Install signal handlers on main thread
    def _handle_signal(signum, frame):
        logger.info("Received signal %s — shutting down", signum)
        shutdown.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Start daemon threads
    receive_thread.start()
    serve_thread.start()
    logger.info("Node started — 3 threads (forge, receive, serve)")

    # --- Thread 1: FORGE (runs on main thread) ---
    if config.is_block_producer:
        forge_loop(
            config=config,
            slot_config=slot_config,
            shutdown_event=shutdown,
            block_received_event=block_received,
            chain_db=chain_db,
            node_kernel=node_kernel,
            mempool=mempool,
        )
    else:
        # Relay-only: wait for shutdown
        shutdown.wait()

    # --- Graceful shutdown ---
    logger.info("Shutting down...")
    shutdown.set()
    receive_thread.join(timeout=5)
    serve_thread.join(timeout=5)
    chain_db.close()
    logger.info("Node stopped")
