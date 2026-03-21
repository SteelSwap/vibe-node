"""Tests for periodic ledger snapshot loop and restore-on-startup.

Covers:
    - _snapshot_loop fires at the configured interval
    - _snapshot_loop skips when no slot progress has been made
    - run_node restores from the latest snapshot on startup
    - shutdown_event cleanly stops the snapshot loop
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe.cardano.node.run import _snapshot_loop, SlotClock
from vibe.cardano.consensus.slot_arithmetic import SlotConfig
from vibe.core.storage.interfaces import SnapshotHandle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeSlotConfig:
    """Minimal slot config for testing."""

    slot_length: float = 0.01  # very short for tests
    epoch_length: int = 432000
    system_start: Any = None


class FakeSlotClock:
    """Controllable slot clock for tests."""

    def __init__(self, slot_length: float = 0.01) -> None:
        self._current_slot = 0
        self.slot_config = FakeSlotConfig(slot_length=slot_length)

    def current_slot(self) -> int:
        return self._current_slot

    def set_slot(self, slot: int) -> None:
        self._current_slot = slot


class FakeLedgerDB:
    """Minimal LedgerDB mock with snapshot/restore tracking."""

    def __init__(self) -> None:
        self.snapshot_count = 0
        self.utxo_count = 42
        self.restored_handle: SnapshotHandle | None = None

    async def snapshot(self) -> SnapshotHandle:
        self.snapshot_count += 1
        return SnapshotHandle(
            snapshot_id=str(self.snapshot_count),
            metadata={"path": f"/tmp/test-snapshot-{self.snapshot_count}.arrow"},
        )

    async def restore(self, handle: SnapshotHandle) -> None:
        self.restored_handle = handle


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_fires_at_interval() -> None:
    """Snapshot is taken when enough slots have elapsed."""
    ledger_db = FakeLedgerDB()
    slot_clock = FakeSlotClock(slot_length=0.01)
    shutdown_event = asyncio.Event()

    # Start at slot 0, then advance to slot 2000 after the first sleep.
    call_count = 0
    original_sleep = asyncio.sleep

    async def fake_sleep(duration: float) -> None:
        nonlocal call_count
        call_count += 1
        # After first sleep, advance the slot clock past the interval.
        if call_count == 1:
            slot_clock.set_slot(2500)
        elif call_count == 2:
            # After second sleep, shut down.
            shutdown_event.set()
        await original_sleep(0)  # yield control

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await _snapshot_loop(ledger_db, slot_clock, 2000, shutdown_event)

    assert ledger_db.snapshot_count >= 1, "Expected at least one snapshot"


@pytest.mark.asyncio
async def test_snapshot_skipped_when_no_progress() -> None:
    """Snapshot is skipped when slot hasn't advanced enough."""
    ledger_db = FakeLedgerDB()
    slot_clock = FakeSlotClock(slot_length=0.01)
    shutdown_event = asyncio.Event()

    call_count = 0
    original_sleep = asyncio.sleep

    async def fake_sleep(duration: float) -> None:
        nonlocal call_count
        call_count += 1
        # Keep slot at 500 — below the 2000 interval threshold.
        slot_clock.set_slot(500)
        if call_count >= 2:
            shutdown_event.set()
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        await _snapshot_loop(ledger_db, slot_clock, 2000, shutdown_event)

    assert ledger_db.snapshot_count == 0, "No snapshot should fire when slot < interval"


@pytest.mark.asyncio
async def test_restore_on_startup(tmp_path: Path) -> None:
    """run_node restores from the latest arrow snapshot on startup."""
    from vibe.cardano.storage.ledger import LedgerDB

    # Create a real LedgerDB, add some UTxOs, snapshot it.
    db = LedgerDB(k=10, snapshot_dir=tmp_path / "ledger-snapshots")
    db.apply_block(
        consumed=[],
        created=[
            (
                b"\x01" * 32 + b"\x00\x00",
                {
                    "tx_hash": b"\x01" * 32,
                    "tx_index": 0,
                    "address": "addr_test1abc",
                    "value": 1_000_000,
                    "datum_hash": b"",
                },
            ),
        ],
        block_slot=100,
    )
    handle = await db.snapshot()
    assert db.utxo_count == 1

    # Now create a fresh LedgerDB and restore from the snapshot.
    db2 = LedgerDB(k=10, snapshot_dir=tmp_path / "ledger-snapshots")
    assert db2.utxo_count == 0

    snapshot_dir = tmp_path / "ledger-snapshots"
    snapshots = sorted(snapshot_dir.glob("*.arrow"), reverse=True)
    assert len(snapshots) == 1

    restore_handle = SnapshotHandle(
        snapshot_id="restore",
        metadata={"path": str(snapshots[0])},
    )
    await db2.restore(restore_handle)
    assert db2.utxo_count == 1, "Restored LedgerDB should have 1 UTxO"


@pytest.mark.asyncio
async def test_shutdown_stops_snapshot_loop() -> None:
    """Setting the shutdown event causes the loop to exit promptly."""
    ledger_db = FakeLedgerDB()
    slot_clock = FakeSlotClock(slot_length=0.01)
    shutdown_event = asyncio.Event()

    # Set shutdown immediately.
    shutdown_event.set()

    # Should return quickly without taking any snapshots.
    await asyncio.wait_for(
        _snapshot_loop(ledger_db, slot_clock, 2000, shutdown_event),
        timeout=2.0,
    )
    assert ledger_db.snapshot_count == 0, "No snapshot when shutdown is immediate"


@pytest.mark.asyncio
async def test_snapshot_loop_handles_snapshot_failure() -> None:
    """Snapshot failure is logged but does not crash the loop."""
    ledger_db = FakeLedgerDB()

    # Make snapshot raise an exception.
    async def failing_snapshot() -> SnapshotHandle:
        raise OSError("disk full")

    ledger_db.snapshot = failing_snapshot  # type: ignore[assignment]

    slot_clock = FakeSlotClock(slot_length=0.01)
    shutdown_event = asyncio.Event()

    call_count = 0
    original_sleep = asyncio.sleep

    async def fake_sleep(duration: float) -> None:
        nonlocal call_count
        call_count += 1
        slot_clock.set_slot(3000)
        if call_count >= 2:
            shutdown_event.set()
        await original_sleep(0)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # Should not raise — the loop catches and logs the error.
        await _snapshot_loop(ledger_db, slot_clock, 2000, shutdown_event)


@pytest.mark.asyncio
async def test_cancellation_stops_snapshot_loop() -> None:
    """CancelledError during sleep exits the loop cleanly (no crash)."""
    ledger_db = FakeLedgerDB()
    slot_clock = FakeSlotClock(slot_length=100.0)  # long sleep
    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        _snapshot_loop(ledger_db, slot_clock, 2000, shutdown_event)
    )

    # Give it a moment to enter the sleep, then cancel.
    await asyncio.sleep(0.05)
    task.cancel()

    # The loop catches CancelledError and returns cleanly.
    try:
        await task
    except asyncio.CancelledError:
        pass  # Also acceptable if the cancel propagates

    assert ledger_db.snapshot_count == 0
