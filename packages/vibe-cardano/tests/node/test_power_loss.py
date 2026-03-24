"""Power-loss recovery test harness.

Tests that the recovery subsystem (snapshot + diff replay) correctly
restores LedgerDB state after simulated power loss / crash scenarios.

Covers:
    - Recovery from a single snapshot (no diffs)
    - Recovery from snapshot + diff replay
    - UTxO count preservation across crash/recovery
    - Recovery time stays under 5-second threshold
    - Recovery from empty state (no snapshots at all)
    - Multiple snapshots: recovery uses the latest one

Haskell reference:
    Ouroboros.Consensus.Storage.LedgerDB.Snapshots
    Ouroboros.Consensus.Storage.LedgerDB.DiskPolicy
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from vibe.cardano.storage import BlockDiff, LedgerDB
from vibe.cardano.storage.recovery import (
    recover,
    write_diff_log_entry,
    write_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_utxo_key(tx_hash_seed: int, tx_index: int) -> bytes:
    """Create a 34-byte TxIn key from a seed and index."""
    tx_hash = tx_hash_seed.to_bytes(32, "big")
    return tx_hash + tx_index.to_bytes(2, "big")


def _make_col_vals(
    tx_hash_seed: int,
    tx_index: int,
    address: str = "addr_test1qz",
    value: int = 2_000_000,
) -> dict[str, Any]:
    """Create column values dict for a UTxO entry."""
    return {
        "tx_hash": tx_hash_seed.to_bytes(32, "big"),
        "tx_index": tx_index,
        "address": address,
        "value": value,
        "datum_hash": b"",
    }


def _populate_ledger(
    ledger: LedgerDB, count: int, start_seed: int = 1
) -> list[tuple[bytes, dict[str, Any]]]:
    """Insert `count` UTxOs into the ledger, returning (key, col_vals) list."""
    entries: list[tuple[bytes, dict[str, Any]]] = []
    for i in range(count):
        seed = start_seed + i
        key = _make_utxo_key(seed, 0)
        cols = _make_col_vals(seed, 0)
        entries.append((key, cols))
    ledger.apply_block(consumed=[], created=entries, block_slot=start_seed)
    return entries


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecoveryFromSnapshot:
    """test_recovery_from_snapshot — create state, snapshot, corrupt, recover."""

    def test_recovery_from_snapshot(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"

        # 1. Build ledger with 100 UTxOs.
        ledger = LedgerDB(k=100)
        entries = _populate_ledger(ledger, 100)
        assert ledger.utxo_count == 100

        # 2. Write snapshot at slot 1000.
        write_snapshot(ledger, snapshot_dir, slot=1000, block_hash=b"\xaa" * 32)

        # 3. Simulate crash: create a fresh (empty) LedgerDB.
        crashed = LedgerDB(k=100)
        assert crashed.utxo_count == 0

        # 4. Recover from snapshot.
        tip_slot = recover(snapshot_dir, crashed)

        assert tip_slot == 1000
        assert crashed.utxo_count == 100

        # Verify every UTxO is present.
        for key, _ in entries:
            assert key in crashed


class TestRecoveryFromDiffReplay:
    """test_recovery_from_diff_replay — snapshot + diffs after snapshot."""

    def test_recovery_from_diff_replay(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"

        # 1. Build ledger with 50 UTxOs at slot 1000.
        ledger = LedgerDB(k=100)
        initial_entries = _populate_ledger(ledger, 50, start_seed=1)
        assert ledger.utxo_count == 50

        # 2. Snapshot at slot 1000.
        write_snapshot(ledger, snapshot_dir, slot=1000)

        # 3. Apply more blocks AFTER the snapshot (slots 1001, 1002).
        block_1001_created = []
        for i in range(10):
            key = _make_utxo_key(1000 + i, 1)
            cols = _make_col_vals(1000 + i, 1)
            block_1001_created.append((key, cols))

        diff_1001 = BlockDiff(consumed=[], created=block_1001_created, block_slot=1001)
        ledger.apply_block(consumed=[], created=block_1001_created, block_slot=1001)

        # Consume 5 from initial + create 5 new at slot 1002.
        consumed_keys_1002 = [k for k, _ in initial_entries[:5]]
        consumed_with_data_1002 = [
            (k, ledger.get_utxo(k)) for k in consumed_keys_1002 if k in ledger
        ]
        block_1002_created = []
        for i in range(5):
            key = _make_utxo_key(2000 + i, 0)
            cols = _make_col_vals(2000 + i, 0)
            block_1002_created.append((key, cols))

        diff_1002 = BlockDiff(
            consumed=consumed_with_data_1002,
            created=block_1002_created,
            block_slot=1002,
        )
        ledger.apply_block(
            consumed=consumed_keys_1002,
            created=block_1002_created,
            block_slot=1002,
        )

        expected_count = ledger.utxo_count  # 50 + 10 - 5 + 5 = 60

        # 4. Write diffs to replay log.
        log_path = snapshot_dir / "diff-replay.log"
        write_diff_log_entry(diff_1001, log_path)
        write_diff_log_entry(diff_1002, log_path)

        # 5. Simulate crash: fresh LedgerDB.
        crashed = LedgerDB(k=100)

        # 6. Recover.
        tip_slot = recover(snapshot_dir, crashed)

        assert tip_slot == 1002
        assert crashed.utxo_count == expected_count

        # Verify consumed UTxOs are gone.
        for key in consumed_keys_1002:
            assert key not in crashed

        # Verify new UTxOs exist.
        for key, _ in block_1002_created:
            assert key in crashed


class TestRecoveryPreservesUtxoCount:
    """test_recovery_preserves_utxo_count — count matches pre-crash state."""

    @pytest.mark.parametrize("utxo_count", [1, 10, 100, 500, 1000])
    def test_recovery_preserves_utxo_count(self, tmp_path: Path, utxo_count: int) -> None:
        snapshot_dir = tmp_path / "snapshots"

        ledger = LedgerDB(k=100)
        _populate_ledger(ledger, utxo_count)
        pre_crash_count = ledger.utxo_count
        assert pre_crash_count == utxo_count

        write_snapshot(ledger, snapshot_dir, slot=500)

        recovered = LedgerDB(k=100)
        recover(snapshot_dir, recovered)

        assert recovered.utxo_count == pre_crash_count


class TestRecoveryTimeUnderThreshold:
    """test_recovery_time_under_threshold — recovery < 5 seconds."""

    def test_recovery_time_under_threshold(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"

        # Build a reasonably sized ledger (5000 UTxOs) to stress the path.
        ledger = LedgerDB(k=100)
        _populate_ledger(ledger, 5000)
        write_snapshot(ledger, snapshot_dir, slot=10000)

        # Add 50 diffs to the replay log.
        log_path = snapshot_dir / "diff-replay.log"
        for slot in range(10001, 10051):
            created = []
            for j in range(5):
                key = _make_utxo_key(slot * 100 + j, 0)
                cols = _make_col_vals(slot * 100 + j, 0)
                created.append((key, cols))
            diff = BlockDiff(consumed=[], created=created, block_slot=slot)
            write_diff_log_entry(diff, log_path)

        # Measure recovery time.
        crashed = LedgerDB(k=100)
        t0 = time.monotonic()
        tip_slot = recover(snapshot_dir, crashed)
        elapsed = time.monotonic() - t0

        assert tip_slot == 10050
        assert elapsed < 5.0, f"Recovery took {elapsed:.2f}s, exceeding 5s threshold"
        assert crashed.utxo_count == 5000 + 50 * 5  # 5250


class TestRecoveryFromEmptyState:
    """test_recovery_from_empty_state — no snapshots recovers cleanly."""

    def test_no_snapshot_dir(self, tmp_path: Path) -> None:
        """No snapshot directory at all -> returns -1."""
        snapshot_dir = tmp_path / "nonexistent"
        ledger = LedgerDB(k=100)
        tip_slot = recover(snapshot_dir, ledger)

        assert tip_slot == -1
        assert ledger.utxo_count == 0

    def test_empty_snapshot_dir(self, tmp_path: Path) -> None:
        """Empty snapshot directory -> returns -1."""
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()
        ledger = LedgerDB(k=100)
        tip_slot = recover(snapshot_dir, ledger)

        assert tip_slot == -1
        assert ledger.utxo_count == 0

    def test_only_diff_log_no_snapshot(self, tmp_path: Path) -> None:
        """Diff log exists but no snapshot -> returns -1 (diffs ignored)."""
        snapshot_dir = tmp_path / "snapshots"
        snapshot_dir.mkdir()

        # Write a diff log entry with no corresponding snapshot.
        log_path = snapshot_dir / "diff-replay.log"
        created = [
            (_make_utxo_key(99, 0), _make_col_vals(99, 0)),
        ]
        diff = BlockDiff(consumed=[], created=created, block_slot=100)
        write_diff_log_entry(diff, log_path)

        ledger = LedgerDB(k=100)
        tip_slot = recover(snapshot_dir, ledger)

        # No snapshot found -> -1, diffs alone cannot bootstrap.
        assert tip_slot == -1
        assert ledger.utxo_count == 0


class TestMultipleSnapshotsUsesLatest:
    """test_multiple_snapshots_uses_latest — latest snapshot wins."""

    def test_multiple_snapshots_uses_latest(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshots"

        # Snapshot 1: 20 UTxOs at slot 500.
        ledger_v1 = LedgerDB(k=100)
        _populate_ledger(ledger_v1, 20, start_seed=1)
        write_snapshot(ledger_v1, snapshot_dir, slot=500)

        # Snapshot 2: 50 UTxOs at slot 1000.
        ledger_v2 = LedgerDB(k=100)
        _populate_ledger(ledger_v2, 50, start_seed=100)
        write_snapshot(ledger_v2, snapshot_dir, slot=1000)

        # Snapshot 3: 80 UTxOs at slot 2000.
        ledger_v3 = LedgerDB(k=100)
        _populate_ledger(ledger_v3, 80, start_seed=200)
        write_snapshot(ledger_v3, snapshot_dir, slot=2000)

        # Recover should use the slot-2000 snapshot (80 UTxOs).
        recovered = LedgerDB(k=100)
        tip_slot = recover(snapshot_dir, recovered)

        assert tip_slot == 2000
        assert recovered.utxo_count == 80

        # Verify the recovered UTxOs are from ledger_v3, not v1 or v2.
        # v3 used start_seed=200, so keys should be for seeds 200..279.
        for i in range(80):
            key = _make_utxo_key(200 + i, 0)
            assert key in recovered

        # v1 keys (seeds 1..20) should NOT be present.
        for i in range(20):
            key = _make_utxo_key(1 + i, 0)
            assert key not in recovered

    def test_diffs_only_replay_after_latest_snapshot(self, tmp_path: Path) -> None:
        """Diffs older than the latest snapshot are skipped."""
        snapshot_dir = tmp_path / "snapshots"

        # Snapshot at slot 500 with 10 UTxOs.
        ledger_v1 = LedgerDB(k=100)
        entries_v1 = _populate_ledger(ledger_v1, 10, start_seed=1)
        write_snapshot(ledger_v1, snapshot_dir, slot=500)

        # Snapshot at slot 1000 with 30 UTxOs.
        ledger_v2 = LedgerDB(k=100)
        entries_v2 = _populate_ledger(ledger_v2, 30, start_seed=50)
        write_snapshot(ledger_v2, snapshot_dir, slot=1000)

        # Write diffs: one at slot 800 (before latest snapshot) and
        # one at slot 1500 (after).
        log_path = snapshot_dir / "diff-replay.log"

        old_created = [(_make_utxo_key(9000, 0), _make_col_vals(9000, 0))]
        diff_old = BlockDiff(consumed=[], created=old_created, block_slot=800)
        write_diff_log_entry(diff_old, log_path)

        new_created = [(_make_utxo_key(9001, 0), _make_col_vals(9001, 0))]
        diff_new = BlockDiff(consumed=[], created=new_created, block_slot=1500)
        write_diff_log_entry(diff_new, log_path)

        recovered = LedgerDB(k=100)
        tip_slot = recover(snapshot_dir, recovered)

        assert tip_slot == 1500
        # 30 from snapshot + 1 from diff at slot 1500 (slot 800 diff skipped).
        assert recovered.utxo_count == 31

        # The slot-800 diff's UTxO should NOT be present (skipped).
        assert _make_utxo_key(9000, 0) not in recovered
        # The slot-1500 diff's UTxO should be present.
        assert _make_utxo_key(9001, 0) in recovered
