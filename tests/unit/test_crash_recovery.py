"""Tests for crash recovery — vibe.cardano.storage.recovery.

Covers:
- Snapshot write + load roundtrip
- Diff log write + read roundtrip
- Full recovery flow: snapshot + diff replay
- Edge cases: corrupt logs, truncated entries, missing snapshots
- Recovery after simulated crash

Test spec references (from test_specifications DB):
- test_ledgerdb_snapshot_roundtrip
- test_recovery_after_simulated_hard_shutdown
- test_init_from_valid_snapshot_on_chain
- test_skip_corrupted_snapshot_fallback_to_genesis
- test_init_from_genesis_when_no_snapshots
- test_crash_during_put_block_loses_block_but_db_remains_consistent
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from vibe.cardano.storage import BlockDiff, LedgerDB
from vibe.cardano.storage.recovery import (
    _DIFF_HEADER_FMT,
    _DIFF_HEADER_SIZE,
    _DIFF_MAGIC,
    SNAPSHOT_INTERVAL,
    _deserialize_col_vals,
    _read_diff_log,
    _serialize_col_vals,
    _slot_from_snapshot_path,
    recover,
    write_diff_log_entry,
    write_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_utxo_entry(
    tx_hash: bytes, tx_index: int, address: str = "addr_test1", value: int = 1_000_000
) -> tuple[bytes, dict[str, Any]]:
    """Create a (key, col_vals) tuple for a UTxO entry."""
    key = tx_hash[:32].ljust(32, b"\x00") + tx_index.to_bytes(2, "big")
    col_vals = {
        "key": key,
        "tx_hash": tx_hash[:32].ljust(32, b"\x00"),
        "tx_index": tx_index,
        "address": address,
        "value": value,
        "datum_hash": b"",
    }
    return key, col_vals


def _populate_ledger(ledger_db: LedgerDB, n: int = 5) -> list[tuple[bytes, dict[str, Any]]]:
    """Add N UTxO entries to a LedgerDB, returning the entries."""
    entries = []
    for i in range(n):
        tx_hash = (i).to_bytes(32, "big")
        key, col_vals = _make_utxo_entry(tx_hash, i, value=(i + 1) * 1_000_000)
        entries.append((key, col_vals))
    ledger_db._bulk_insert(entries)
    return entries


# ---------------------------------------------------------------------------
# Tests: snapshot write + roundtrip
# ---------------------------------------------------------------------------


class TestWriteSnapshot:
    """Tests for write_snapshot."""

    def test_creates_arrow_file(self, tmp_path: Path) -> None:
        """write_snapshot produces a .arrow file."""
        ledger_db = LedgerDB(k=10)
        _populate_ledger(ledger_db, 3)

        arrow_path = write_snapshot(ledger_db, tmp_path, slot=100, block_hash=b"\xaa" * 32)
        assert arrow_path.exists()
        assert arrow_path.suffix == ".arrow"

    def test_creates_meta_file(self, tmp_path: Path) -> None:
        """write_snapshot produces a .meta JSON sidecar."""
        ledger_db = LedgerDB(k=10)
        _populate_ledger(ledger_db, 3)

        write_snapshot(ledger_db, tmp_path, slot=100)

        meta_path = tmp_path / "snapshot-100.meta"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["slot"] == 100
        assert meta["utxo_count"] == 3

    def test_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        """Snapshot roundtrip: write then load restores the same UTxO set.

        Corresponds to: test_ledgerdb_snapshot_roundtrip
        """
        ledger_db = LedgerDB(k=10)
        entries = _populate_ledger(ledger_db, 5)
        original_count = ledger_db.utxo_count

        write_snapshot(ledger_db, tmp_path, slot=200)

        # Create a fresh LedgerDB and recover into it.
        new_db = LedgerDB(k=10)
        assert new_db.utxo_count == 0

        recovered_slot = recover(tmp_path, new_db)
        assert recovered_slot == 200
        assert new_db.utxo_count == original_count

        # Verify each UTxO is present.
        for key, _ in entries:
            assert key in new_db

    def test_snapshot_with_empty_db(self, tmp_path: Path) -> None:
        """Snapshot of an empty LedgerDB produces a valid file."""
        ledger_db = LedgerDB(k=10)
        arrow_path = write_snapshot(ledger_db, tmp_path, slot=0)
        assert arrow_path.exists()

        # Recover from empty snapshot.
        new_db = LedgerDB(k=10)
        slot = recover(tmp_path, new_db)
        assert slot == 0
        assert new_db.utxo_count == 0


# ---------------------------------------------------------------------------
# Tests: diff log serialization
# ---------------------------------------------------------------------------


class TestDiffLogSerialization:
    """Tests for column value serialization helpers."""

    def test_roundtrip_with_bytes(self) -> None:
        col_vals = {
            "key": b"\x01\x02\x03",
            "tx_hash": b"\xaa" * 32,
            "tx_index": 42,
            "address": "addr_test1qz...",
            "value": 5_000_000,
            "datum_hash": b"",
        }
        serialized = _serialize_col_vals(col_vals)
        restored = _deserialize_col_vals(serialized)

        assert restored["key"] == col_vals["key"]
        assert restored["tx_hash"] == col_vals["tx_hash"]
        assert restored["tx_index"] == col_vals["tx_index"]
        assert restored["address"] == col_vals["address"]
        assert restored["value"] == col_vals["value"]
        assert restored["datum_hash"] == col_vals["datum_hash"]


# ---------------------------------------------------------------------------
# Tests: diff log write + read
# ---------------------------------------------------------------------------


class TestDiffLog:
    """Tests for write_diff_log_entry and _read_diff_log."""

    def test_single_entry_roundtrip(self, tmp_path: Path) -> None:
        """Write one diff entry and read it back."""
        log_path = tmp_path / "diff-replay.log"

        key1, cv1 = _make_utxo_entry(b"\x01" * 32, 0)
        key2, cv2 = _make_utxo_entry(b"\x02" * 32, 1)

        diff = BlockDiff(
            consumed=[(key1, cv1)],
            created=[(key2, cv2)],
            block_slot=100,
        )
        write_diff_log_entry(diff, log_path)

        diffs = _read_diff_log(log_path)
        assert len(diffs) == 1
        assert diffs[0].block_slot == 100
        assert len(diffs[0].consumed) == 1
        assert len(diffs[0].created) == 1
        assert diffs[0].consumed[0][0] == key1
        assert diffs[0].created[0][0] == key2

    def test_multiple_entries(self, tmp_path: Path) -> None:
        """Write multiple diff entries and read them all back."""
        log_path = tmp_path / "diff-replay.log"

        for slot in [100, 200, 300]:
            key, cv = _make_utxo_entry(slot.to_bytes(32, "big"), 0)
            diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=slot)
            write_diff_log_entry(diff, log_path)

        diffs = _read_diff_log(log_path)
        assert len(diffs) == 3
        assert [d.block_slot for d in diffs] == [100, 200, 300]

    def test_empty_diff(self, tmp_path: Path) -> None:
        """A diff with no consumed or created entries."""
        log_path = tmp_path / "diff-replay.log"
        diff = BlockDiff(consumed=[], created=[], block_slot=50)
        write_diff_log_entry(diff, log_path)

        diffs = _read_diff_log(log_path)
        assert len(diffs) == 1
        assert diffs[0].block_slot == 50
        assert diffs[0].consumed == []
        assert diffs[0].created == []

    def test_missing_log_returns_empty(self, tmp_path: Path) -> None:
        """Reading a non-existent log returns empty list."""
        diffs = _read_diff_log(tmp_path / "nonexistent.log")
        assert diffs == []

    def test_truncated_entry_handled(self, tmp_path: Path) -> None:
        """A truncated entry at end of log is tolerated.

        Simulates crash during write — the partial entry is dropped.
        Corresponds to: test_crash_during_put_block_loses_block_but_db_remains_consistent
        """
        log_path = tmp_path / "diff-replay.log"

        # Write a valid entry.
        key, cv = _make_utxo_entry(b"\x01" * 32, 0)
        diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=100)
        write_diff_log_entry(diff, log_path)

        # Append a truncated second entry (just the header, no body).
        with open(log_path, "ab") as f:
            f.write(struct.pack(_DIFF_HEADER_FMT, _DIFF_MAGIC, 200, 1, 0))

        diffs = _read_diff_log(log_path)
        # Only the first valid entry should be returned.
        assert len(diffs) == 1
        assert diffs[0].block_slot == 100

    def test_corrupt_magic_stops_replay(self, tmp_path: Path) -> None:
        """Bad magic bytes stop the log replay."""
        log_path = tmp_path / "diff-replay.log"

        # Write valid entry.
        key, cv = _make_utxo_entry(b"\x01" * 32, 0)
        diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=100)
        write_diff_log_entry(diff, log_path)

        # Append garbage.
        with open(log_path, "ab") as f:
            f.write(b"\xff" * _DIFF_HEADER_SIZE)

        diffs = _read_diff_log(log_path)
        assert len(diffs) == 1


# ---------------------------------------------------------------------------
# Tests: full recovery flow
# ---------------------------------------------------------------------------


class TestRecover:
    """Tests for the recover function."""

    def test_recovery_from_snapshot_only(self, tmp_path: Path) -> None:
        """Recover from a snapshot with no diff log.

        Corresponds to: test_init_from_valid_snapshot_on_chain
        """
        ledger_db = LedgerDB(k=10)
        entries = _populate_ledger(ledger_db, 5)

        write_snapshot(ledger_db, tmp_path, slot=500)

        new_db = LedgerDB(k=10)
        slot = recover(tmp_path, new_db)
        assert slot == 500
        assert new_db.utxo_count == 5

    def test_recovery_with_diff_replay(self, tmp_path: Path) -> None:
        """Recover from snapshot + replay diffs that came after it.

        Corresponds to: test_recovery_after_simulated_hard_shutdown
        """
        # Build initial state and snapshot.
        ledger_db = LedgerDB(k=10)
        _populate_ledger(ledger_db, 3)
        write_snapshot(ledger_db, tmp_path, slot=100)

        # Write diff log entries for slots after the snapshot.
        log_path = tmp_path / "diff-replay.log"
        for slot in [150, 200, 250]:
            key, cv = _make_utxo_entry(slot.to_bytes(32, "big"), 0, value=slot * 100)
            diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=slot)
            write_diff_log_entry(diff, log_path)

        # Recover into a fresh DB.
        new_db = LedgerDB(k=10)
        recovered_slot = recover(tmp_path, new_db)

        assert recovered_slot == 250
        # 3 original + 3 from diffs = 6
        assert new_db.utxo_count == 6

    def test_recovery_skips_old_diffs(self, tmp_path: Path) -> None:
        """Diffs with slot <= snapshot_slot are skipped during replay."""
        ledger_db = LedgerDB(k=10)
        _populate_ledger(ledger_db, 2)
        write_snapshot(ledger_db, tmp_path, slot=200)

        # Write diffs: some before snapshot, some after.
        log_path = tmp_path / "diff-replay.log"
        for slot in [100, 150, 250, 300]:
            key, cv = _make_utxo_entry(slot.to_bytes(32, "big"), 0)
            diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=slot)
            write_diff_log_entry(diff, log_path)

        new_db = LedgerDB(k=10)
        recovered_slot = recover(tmp_path, new_db)

        assert recovered_slot == 300
        # 2 from snapshot + 2 from diffs (250, 300) = 4
        assert new_db.utxo_count == 4

    def test_no_snapshots_returns_minus_one(self, tmp_path: Path) -> None:
        """With no snapshots, recovery returns -1.

        Corresponds to: test_init_from_genesis_when_no_snapshots
        """
        slot = recover(tmp_path, LedgerDB(k=10))
        assert slot == -1

    def test_nonexistent_dir_returns_minus_one(self) -> None:
        slot = recover(Path("/nonexistent/dir"), LedgerDB(k=10))
        assert slot == -1

    def test_recovery_truncates_diff_log(self, tmp_path: Path) -> None:
        """After recovery, the diff log is truncated (empty)."""
        ledger_db = LedgerDB(k=10)
        _populate_ledger(ledger_db, 1)
        write_snapshot(ledger_db, tmp_path, slot=100)

        log_path = tmp_path / "diff-replay.log"
        key, cv = _make_utxo_entry(b"\xff" * 32, 0)
        diff = BlockDiff(consumed=[], created=[(key, cv)], block_slot=200)
        write_diff_log_entry(diff, log_path)

        new_db = LedgerDB(k=10)
        recover(tmp_path, new_db)

        # Log should be empty after recovery.
        assert log_path.read_bytes() == b""

    def test_recovery_with_consumed_diffs(self, tmp_path: Path) -> None:
        """Recovery correctly applies diffs that consume (spend) UTxOs."""
        ledger_db = LedgerDB(k=10)
        entries = _populate_ledger(ledger_db, 3)
        write_snapshot(ledger_db, tmp_path, slot=100)

        # Write a diff that spends the first UTxO.
        log_path = tmp_path / "diff-replay.log"
        spent_key = entries[0][0]
        diff = BlockDiff(
            consumed=[(spent_key, entries[0][1])],
            created=[],
            block_slot=200,
        )
        write_diff_log_entry(diff, log_path)

        new_db = LedgerDB(k=10)
        recovered_slot = recover(tmp_path, new_db)

        assert recovered_slot == 200
        # 3 from snapshot - 1 consumed = 2
        assert new_db.utxo_count == 2
        assert spent_key not in new_db

    def test_multiple_snapshots_uses_latest(self, tmp_path: Path) -> None:
        """When multiple snapshots exist, recovery uses the latest one."""
        # Write snapshot at slot 100 with 2 UTxOs.
        db1 = LedgerDB(k=10)
        _populate_ledger(db1, 2)
        write_snapshot(db1, tmp_path, slot=100)

        # Write snapshot at slot 500 with 5 UTxOs.
        db2 = LedgerDB(k=10)
        _populate_ledger(db2, 5)
        write_snapshot(db2, tmp_path, slot=500)

        new_db = LedgerDB(k=10)
        slot = recover(tmp_path, new_db)
        assert slot == 500
        assert new_db.utxo_count == 5


# ---------------------------------------------------------------------------
# Tests: slot extraction from filename
# ---------------------------------------------------------------------------


class TestSlotFromSnapshotPath:
    def test_normal(self) -> None:
        assert _slot_from_snapshot_path(Path("snapshot-12345.arrow")) == 12345

    def test_zero(self) -> None:
        assert _slot_from_snapshot_path(Path("snapshot-0.arrow")) == 0

    def test_malformed(self) -> None:
        assert _slot_from_snapshot_path(Path("bad-name.arrow")) == 0


# ---------------------------------------------------------------------------
# Tests: snapshot interval constant
# ---------------------------------------------------------------------------


class TestConstants:
    def test_snapshot_interval(self) -> None:
        assert SNAPSHOT_INTERVAL == 2000
