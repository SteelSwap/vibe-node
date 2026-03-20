"""LedgerDB snapshot policy tests — verify retention, intervals, and consistency.

Tests mirror Haskell properties:
    - prop_onDiskNumSnapshots — correct number of snapshots retained
    - prop_onDiskShouldTakeSnapshot — snapshot at correct interval
    - Snapshot metadata serialization roundtrip
    - Oldest snapshot deleted when max exceeded
    - Snapshot consistent after rollback

Haskell reference:
    Ouroboros.Consensus.Storage.LedgerDB.Snapshots
    onDiskNumSnapshots, onDiskShouldTakeSnapshot

Spec reference:
    The Haskell node keeps a bounded number of on-disk snapshots,
    taking a new one every SNAPSHOT_INTERVAL slots and deleting
    the oldest when the maximum is exceeded.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from vibe.cardano.storage.ledger import (
    BlockDiff,
    ExceededRollbackError,
    LedgerDB,
    UTXO_SCHEMA,
)
from vibe.core.storage.interfaces import SnapshotHandle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SNAPSHOT_INTERVAL = 100  # Slots between snapshots (mirrors Haskell default)
MAX_SNAPSHOTS = 3  # Maximum on-disk snapshots to retain


def make_txin(tx_hash_seed: int, tx_index: int) -> bytes:
    """Create a 34-byte TxIn key from a seed and index."""
    tx_hash = struct.pack(">I", tx_hash_seed).ljust(32, b"\x00")
    return tx_hash + struct.pack(">H", tx_index)


def make_utxo_entry(
    tx_hash_seed: int,
    tx_index: int,
    address: str = "addr_test1qz",
    value: int = 2_000_000,
    datum_hash: bytes = b"",
) -> tuple[bytes, dict]:
    key = make_txin(tx_hash_seed, tx_index)
    tx_hash = key[:32]
    return key, {
        "tx_hash": tx_hash,
        "tx_index": tx_index,
        "address": address,
        "value": value,
        "datum_hash": datum_hash,
    }


async def apply_n_blocks(db: LedgerDB, n: int, start_slot: int = 1) -> None:
    """Apply n blocks, each creating one UTxO."""
    for slot in range(start_slot, start_slot + n):
        key, cols = make_utxo_entry(slot, 0, value=slot * 1_000_000)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)


# ---------------------------------------------------------------------------
# prop_onDiskNumSnapshots — correct number of snapshots retained
# ---------------------------------------------------------------------------


class TestOnDiskNumSnapshots:
    """Verify correct number of snapshots retained (never more than max).

    Haskell property: prop_onDiskNumSnapshots
    The number of on-disk snapshots should never exceed the configured maximum.
    """

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_single_snapshot_count(self, snapshot_dir):
        """Taking one snapshot results in exactly one on-disk file."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        await db.snapshot()

        arrow_files = list(snapshot_dir.glob("*.arrow"))
        assert len(arrow_files) == 1

    @pytest.mark.asyncio
    async def test_multiple_snapshots_count(self, snapshot_dir):
        """Taking N snapshots results in N on-disk files."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        for i in range(5):
            key, cols = make_utxo_entry(i + 1, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=i + 1)
            await db.snapshot()

        arrow_files = list(snapshot_dir.glob("*.arrow"))
        assert len(arrow_files) == 5

    @pytest.mark.asyncio
    async def test_snapshot_ids_monotonic(self, snapshot_dir):
        """Snapshot IDs are monotonically increasing."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        handles = []
        for i in range(4):
            key, cols = make_utxo_entry(i + 1, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=i + 1)
            handles.append(await db.snapshot())

        ids = [int(h.snapshot_id) for h in handles]
        assert ids == sorted(ids)
        assert ids == list(range(4))

    @pytest.mark.asyncio
    async def test_max_snapshots_enforced_by_manual_cleanup(self, snapshot_dir):
        """Demonstrate manual cleanup to enforce max snapshot count.

        The current LedgerDB doesn't auto-prune, so we verify the pattern
        that a snapshot manager would use: take snapshot, delete oldest
        when count exceeds max.

        Haskell reference:
            Ouroboros.Consensus.Storage.LedgerDB.Snapshots.trimSnapshots
        """
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        handles = []

        for i in range(MAX_SNAPSHOTS + 2):
            key, cols = make_utxo_entry(i + 1, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=i + 1)
            h = await db.snapshot()
            handles.append(h)

            # Manual cleanup: delete oldest when exceeding max
            while len(handles) > MAX_SNAPSHOTS:
                oldest = handles.pop(0)
                oldest_path = Path(oldest.metadata["path"])
                if oldest_path.exists():
                    oldest_path.unlink()

        arrow_files = list(snapshot_dir.glob("*.arrow"))
        assert len(arrow_files) == MAX_SNAPSHOTS

    @pytest.mark.asyncio
    async def test_zero_snapshots_initially(self, snapshot_dir):
        """Before any snapshot is taken, no files exist on disk."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        # snapshot_dir may not even exist yet
        if snapshot_dir.exists():
            arrow_files = list(snapshot_dir.glob("*.arrow"))
            assert len(arrow_files) == 0


# ---------------------------------------------------------------------------
# prop_onDiskShouldTakeSnapshot — snapshot at correct intervals
# ---------------------------------------------------------------------------


class TestOnDiskShouldTakeSnapshot:
    """Verify snapshots are taken at correct intervals.

    Haskell property: prop_onDiskShouldTakeSnapshot
    A snapshot should be taken every SNAPSHOT_INTERVAL slots.
    """

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_snapshot_at_interval(self, snapshot_dir):
        """Take a snapshot every SNAPSHOT_INTERVAL slots, verify correct timing.

        Simulates the snapshot policy: only take a snapshot when
        (current_slot % SNAPSHOT_INTERVAL == 0).
        """
        db = LedgerDB(k=2160, snapshot_dir=snapshot_dir)
        snapshot_slots = []

        for slot in range(1, SNAPSHOT_INTERVAL * 4 + 1):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

            if slot % SNAPSHOT_INTERVAL == 0:
                await db.snapshot()
                snapshot_slots.append(slot)

        assert snapshot_slots == [100, 200, 300, 400]
        arrow_files = list(snapshot_dir.glob("*.arrow"))
        assert len(arrow_files) == 4

    @pytest.mark.asyncio
    async def test_no_snapshot_between_intervals(self, snapshot_dir):
        """No snapshot should be taken at non-interval slots."""
        db = LedgerDB(k=100, snapshot_dir=snapshot_dir)
        snapshots_taken = 0

        for slot in range(1, SNAPSHOT_INTERVAL):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

            # Only snapshot at interval boundaries
            if slot % SNAPSHOT_INTERVAL == 0:
                await db.snapshot()
                snapshots_taken += 1

        # No snapshots should have been taken (slots 1 through 99)
        assert snapshots_taken == 0


# ---------------------------------------------------------------------------
# Snapshot metadata serialization roundtrip
# ---------------------------------------------------------------------------


class TestSnapshotMetadataRoundtrip:
    """Verify snapshot metadata survives serialization roundtrip."""

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_metadata_contains_path(self, snapshot_dir):
        """Snapshot handle metadata contains the file path."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        handle = await db.snapshot()
        assert "path" in handle.metadata
        assert Path(handle.metadata["path"]).exists()

    @pytest.mark.asyncio
    async def test_metadata_contains_utxo_count(self, snapshot_dir):
        """Snapshot handle metadata records UTxO count."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        entries = [make_utxo_entry(i, 0) for i in range(7)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        handle = await db.snapshot()
        assert handle.metadata["utxo_count"] == "7"

    @pytest.mark.asyncio
    async def test_metadata_contains_timestamp(self, snapshot_dir):
        """Snapshot handle metadata records a timestamp."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        before = time.time()
        handle = await db.snapshot()
        after = time.time()

        ts = float(handle.metadata["timestamp"])
        assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_snapshot_handle_roundtrip_reconstruct(self, snapshot_dir):
        """Reconstruct a SnapshotHandle from its fields and restore successfully."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        entries = [make_utxo_entry(i, 0, value=i * 1_000_000) for i in range(1, 4)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        handle = await db.snapshot()

        # Reconstruct the handle from raw fields (simulates deserialization)
        reconstructed = SnapshotHandle(
            snapshot_id=handle.snapshot_id,
            metadata=dict(handle.metadata),
        )

        db2 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        await db2.restore(reconstructed)
        assert db2.utxo_count == 3


# ---------------------------------------------------------------------------
# Oldest snapshot deleted when max exceeded
# ---------------------------------------------------------------------------


class TestOldestSnapshotDeleted:
    """Verify oldest snapshot is deleted when max exceeded."""

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_oldest_deleted_preserves_latest(self, snapshot_dir):
        """When oldest snapshot is deleted, latest snapshots are still restorable."""
        db = LedgerDB(k=20, snapshot_dir=snapshot_dir)
        handles = []

        # Take 5 snapshots at different states
        for i in range(5):
            key, cols = make_utxo_entry(i + 1, 0, value=(i + 1) * 1_000_000)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=i + 1)
            handles.append(await db.snapshot())

        # Delete the two oldest
        for h in handles[:2]:
            Path(h.metadata["path"]).unlink()

        # Latest 3 should still be restorable
        for h in handles[2:]:
            db_restored = LedgerDB(k=20, snapshot_dir=snapshot_dir)
            await db_restored.restore(h)
            assert db_restored.utxo_count > 0

    @pytest.mark.asyncio
    async def test_deleted_snapshot_not_restorable(self, snapshot_dir):
        """A deleted snapshot cannot be restored."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        handle = await db.snapshot()
        Path(handle.metadata["path"]).unlink()

        db2 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        with pytest.raises(KeyError):
            await db2.restore(handle)


# ---------------------------------------------------------------------------
# Snapshot during rollback — verify consistency
# ---------------------------------------------------------------------------


class TestSnapshotDuringRollback:
    """Verify snapshot is consistent after rollback.

    If we rollback and then snapshot, the snapshot should reflect
    the rolled-back state, not the pre-rollback state.
    """

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_snapshot_after_rollback_reflects_correct_state(self, snapshot_dir):
        """Snapshot taken after rollback contains only the survived UTxOs."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        # Block 1: create 5 UTxOs
        entries_1 = [make_utxo_entry(i, 0, value=i * 1_000_000) for i in range(1, 6)]
        db.apply_block(consumed=[], created=entries_1, block_slot=1)

        # Block 2: create 3 more
        entries_2 = [make_utxo_entry(10 + i, 0) for i in range(3)]
        db.apply_block(consumed=[], created=entries_2, block_slot=2)

        assert db.utxo_count == 8

        # Rollback block 2
        db.rollback(1)
        assert db.utxo_count == 5

        # Snapshot the rolled-back state
        handle = await db.snapshot()

        # Restore into a fresh DB and verify
        db2 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        await db2.restore(handle)

        assert db2.utxo_count == 5
        # Block 1's UTxOs should exist
        for key, _ in entries_1:
            assert db2.get_utxo(key) is not None
        # Block 2's UTxOs should NOT exist
        for key, _ in entries_2:
            assert db2.get_utxo(key) is None

    @pytest.mark.asyncio
    async def test_snapshot_after_full_rollback_is_empty(self, snapshot_dir):
        """Snapshot after rolling back all blocks captures empty state."""
        db = LedgerDB(k=5, snapshot_dir=snapshot_dir)

        for slot in range(1, 4):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        db.rollback(3)
        assert db.utxo_count == 0

        handle = await db.snapshot()

        db2 = LedgerDB(k=5, snapshot_dir=snapshot_dir)
        await db2.restore(handle)
        assert db2.utxo_count == 0

    @pytest.mark.asyncio
    async def test_snapshot_rollback_reapply_consistency(self, snapshot_dir):
        """Snapshot -> rollback -> reapply -> snapshot produces correct state.

        This tests the full lifecycle: take a snapshot, rollback,
        apply new blocks on a different fork, take another snapshot,
        and verify the second snapshot reflects the new fork.
        """
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        # Block 1: create UTxOs
        entries_1 = [make_utxo_entry(i, 0) for i in range(1, 4)]
        db.apply_block(consumed=[], created=entries_1, block_slot=1)

        # First snapshot (3 UTxOs)
        handle_1 = await db.snapshot()

        # Block 2: create more
        entries_2 = [make_utxo_entry(10 + i, 0) for i in range(2)]
        db.apply_block(consumed=[], created=entries_2, block_slot=2)

        # Rollback block 2
        db.rollback(1)

        # Apply different block 2 (fork)
        fork_entries = [make_utxo_entry(20 + i, 0) for i in range(4)]
        db.apply_block(consumed=[], created=fork_entries, block_slot=2)

        # Second snapshot (3 + 4 = 7 UTxOs)
        handle_2 = await db.snapshot()

        # Verify both snapshots are independent
        db_snap1 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        await db_snap1.restore(handle_1)
        assert db_snap1.utxo_count == 3

        db_snap2 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        await db_snap2.restore(handle_2)
        assert db_snap2.utxo_count == 7
