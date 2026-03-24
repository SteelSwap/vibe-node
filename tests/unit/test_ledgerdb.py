"""Unit tests for LedgerDB — Arrow-backed UTxO state store.

Tests cover:
    - UTxO insert / lookup / delete
    - Block apply with consumed + created
    - Rollback correctness (undo N blocks)
    - Diff layer bounded at k
    - Snapshot write + restore roundtrip
    - ExceededRollbackError
    - Compaction
    - StateStore protocol compliance
    - Performance benchmarks (pytest-benchmark)

Test specifications from the database:
    - test_ledgerdb_empty_creation
    - test_ledgerdb_from_anchor_is_empty
    - test_exceeded_rollback_error_raised
    - test_complete_rollback_leaves_only_anchor
    - test_ledgerdb_prune_never_exceeds_k
    - test_ledger_db_length_after_push_and_prune
"""

from __future__ import annotations

import struct

import pytest

from vibe.cardano.storage.ledger import (
    BlockDiff,
    ExceededRollbackError,
    LedgerDB,
)
from vibe.core.storage.interfaces import SnapshotHandle, StateStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Create a (key, column_values) pair for a UTxO entry."""
    key = make_txin(tx_hash_seed, tx_index)
    tx_hash = key[:32]
    return key, {
        "tx_hash": tx_hash,
        "tx_index": tx_index,
        "address": address,
        "value": value,
        "datum_hash": datum_hash,
    }


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


class TestLedgerDBCreation:
    """Test LedgerDB initialization."""

    def test_empty_creation(self):
        """LedgerDB starts with zero UTxOs and zero diffs."""
        db = LedgerDB(k=10)
        assert db.utxo_count == 0
        assert db.max_rollback == 0
        assert len(db) == 0
        assert db.k == 10

    def test_from_anchor_is_empty(self):
        """A freshly constructed LedgerDB has no checkpoints."""
        db = LedgerDB(k=2160)
        assert db.utxo_count == 0
        assert db.max_rollback == 0

    def test_repr(self):
        db = LedgerDB(k=5)
        assert "LedgerDB" in repr(db)
        assert "k=5" in repr(db)
        assert "utxos=0" in repr(db)


# ---------------------------------------------------------------------------
# UTxO Insert / Lookup / Delete
# ---------------------------------------------------------------------------


class TestUTxOOperations:
    """Test basic UTxO CRUD operations."""

    def test_insert_and_lookup(self):
        """Insert a UTxO and look it up by key."""
        db = LedgerDB(k=10)
        key, cols = make_utxo_entry(1, 0, address="addr_abc", value=5_000_000)

        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        result = db.get_utxo(key)
        assert result is not None
        assert result["address"] == "addr_abc"
        assert result["value"] == 5_000_000
        assert result["tx_index"] == 0
        assert key in db

    def test_lookup_missing_key(self):
        """Looking up a non-existent key returns None."""
        db = LedgerDB(k=10)
        key = make_txin(999, 0)
        assert db.get_utxo(key) is None
        assert key not in db

    def test_delete_via_consume(self):
        """Consuming a UTxO removes it from the set."""
        db = LedgerDB(k=10)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)
        assert db.utxo_count == 1

        db.apply_block(consumed=[key], created=[], block_slot=2)
        assert db.utxo_count == 0
        assert db.get_utxo(key) is None

    def test_multiple_utxos(self):
        """Insert and look up multiple UTxOs."""
        db = LedgerDB(k=10)
        entries = [make_utxo_entry(i, 0, value=i * 1_000_000) for i in range(10)]

        db.apply_block(
            consumed=[],
            created=entries,
            block_slot=1,
        )
        assert db.utxo_count == 10

        for key, cols in entries:
            result = db.get_utxo(key)
            assert result is not None
            assert result["value"] == cols["value"]


# ---------------------------------------------------------------------------
# Block Apply
# ---------------------------------------------------------------------------


class TestBlockApply:
    """Test apply_block with consumed + created UTxOs."""

    def test_apply_consumes_and_creates(self):
        """A block that spends some UTxOs and creates others."""
        db = LedgerDB(k=10)

        # Create initial UTxOs.
        initial = [make_utxo_entry(i, 0) for i in range(5)]
        db.apply_block(consumed=[], created=initial, block_slot=1)
        assert db.utxo_count == 5

        # Block 2: consume 2, create 3.
        consumed = [initial[0][0], initial[1][0]]
        new_entries = [make_utxo_entry(100 + i, 0) for i in range(3)]
        db.apply_block(consumed=consumed, created=new_entries, block_slot=2)

        assert db.utxo_count == 6  # 5 - 2 + 3
        assert db.get_utxo(initial[0][0]) is None
        assert db.get_utxo(initial[1][0]) is None
        assert db.get_utxo(new_entries[0][0]) is not None

    def test_apply_records_diff(self):
        """Each apply_block pushes one diff."""
        db = LedgerDB(k=10)

        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)
        assert db.max_rollback == 1

        db.apply_block(consumed=[key], created=[], block_slot=2)
        assert db.max_rollback == 2

    def test_consume_nonexistent_is_silent(self):
        """Consuming a key not in the set is a no-op (no error)."""
        db = LedgerDB(k=10)
        fake_key = make_txin(999, 0)
        db.apply_block(consumed=[fake_key], created=[], block_slot=1)
        assert db.utxo_count == 0
        assert db.max_rollback == 1


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRollback:
    """Test rollback correctness."""

    def test_rollback_single_block(self):
        """Roll back one block restores consumed UTxOs."""
        db = LedgerDB(k=10)

        key, cols = make_utxo_entry(1, 0, value=42_000_000)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        db.apply_block(consumed=[key], created=[], block_slot=2)
        assert db.get_utxo(key) is None

        db.rollback(1)
        result = db.get_utxo(key)
        assert result is not None
        assert result["value"] == 42_000_000

    def test_rollback_removes_created(self):
        """Rolling back a block removes UTxOs it created."""
        db = LedgerDB(k=10)

        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)
        assert db.utxo_count == 1

        db.rollback(1)
        assert db.utxo_count == 0
        assert db.get_utxo(key) is None

    def test_rollback_multiple_blocks(self):
        """Roll back N blocks reverses all N diffs."""
        db = LedgerDB(k=10)

        # Block 1: create 3 UTxOs.
        entries_1 = [make_utxo_entry(i, 0) for i in range(3)]
        db.apply_block(consumed=[], created=entries_1, block_slot=1)

        # Block 2: consume 1, create 2.
        entries_2 = [make_utxo_entry(10 + i, 0) for i in range(2)]
        db.apply_block(consumed=[entries_1[0][0]], created=entries_2, block_slot=2)

        # Block 3: consume another, create 1.
        entry_3 = make_utxo_entry(20, 0)
        db.apply_block(consumed=[entries_1[1][0]], created=[entry_3], block_slot=3)

        assert db.max_rollback == 3

        # Roll back all 3.
        db.rollback(3)
        assert db.max_rollback == 0
        assert db.utxo_count == 0  # Back to empty (before block 1)

    def test_complete_rollback_leaves_only_anchor(self):
        """Rolling back all blocks returns to the initial (empty) state.

        Mirrors test_complete_rollback_leaves_only_anchor from test specs.
        """
        db = LedgerDB(k=3)

        for slot in range(1, 4):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        assert db.max_rollback == 3

        db.rollback(3)
        assert db.max_rollback == 0
        assert db.utxo_count == 0

    def test_exceeded_rollback_error(self):
        """Requesting rollback beyond stored diffs raises ExceededRollbackError.

        Mirrors test_exceeded_rollback_error_raised from test specs:
        k=5, push 3 blocks (unsaturated, max_rollback=3), request 4.
        """
        db = LedgerDB(k=5)

        for slot in range(1, 4):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        assert db.max_rollback == 3

        with pytest.raises(ExceededRollbackError) as exc_info:
            db.rollback(4)

        assert exc_info.value.rollback_maximum == 3
        assert exc_info.value.rollback_requested == 4

    def test_rollback_zero_is_noop(self):
        """Rolling back 0 blocks does nothing."""
        db = LedgerDB(k=10)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        db.rollback(0)
        assert db.utxo_count == 1
        assert db.max_rollback == 1


# ---------------------------------------------------------------------------
# Diff Layer Bounded at k
# ---------------------------------------------------------------------------


class TestDiffLayerBounded:
    """Test that the diff deque respects the k bound."""

    def test_diffs_bounded_at_k(self):
        """After more than k blocks, oldest diffs are evicted.

        Mirrors test_ledgerdb_prune_never_exceeds_k from test specs.
        """
        k = 5
        db = LedgerDB(k=k)

        for slot in range(1, k + 10):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        # Diff count should never exceed k.
        assert db.max_rollback == k

    def test_old_diffs_evicted(self):
        """After k+1 blocks, the first diff is gone — cannot rollback to it."""
        db = LedgerDB(k=3)

        for slot in range(1, 6):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        # Can only roll back 3, not 5.
        assert db.max_rollback == 3

        with pytest.raises(ExceededRollbackError):
            db.rollback(4)


# ---------------------------------------------------------------------------
# Snapshot / Restore
# ---------------------------------------------------------------------------


class TestSnapshotRestore:
    """Test Arrow IPC snapshot write + restore roundtrip."""

    @pytest.fixture
    def snapshot_dir(self, tmp_path):
        return tmp_path / "snapshots"

    @pytest.mark.asyncio
    async def test_snapshot_roundtrip(self, snapshot_dir):
        """Snapshot and restore produces identical UTxO set."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        entries = [
            make_utxo_entry(i, 0, address=f"addr_{i}", value=i * 1_000_000) for i in range(1, 6)
        ]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        handle = await db.snapshot()
        assert handle.snapshot_id == "0"
        assert handle.metadata["utxo_count"] == "5"

        # Create a new LedgerDB and restore.
        db2 = LedgerDB(k=10, snapshot_dir=snapshot_dir)
        await db2.restore(handle)

        assert db2.utxo_count == 5
        for key, cols in entries:
            result = db2.get_utxo(key)
            assert result is not None
            assert result["address"] == cols["address"]
            assert result["value"] == cols["value"]

    @pytest.mark.asyncio
    async def test_restore_clears_diffs(self, snapshot_dir):
        """Restoring a snapshot clears the diff layer."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)
        assert db.max_rollback == 1

        handle = await db.snapshot()

        # Add more blocks.
        for slot in range(2, 5):
            k2, c2 = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(k2, c2)], block_slot=slot)

        assert db.max_rollback == 4

        await db.restore(handle)
        assert db.max_rollback == 0
        assert db.utxo_count == 1

    @pytest.mark.asyncio
    async def test_restore_missing_file_raises(self, snapshot_dir):
        """Restoring from a non-existent file raises KeyError."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        handle = SnapshotHandle(
            snapshot_id="999",
            metadata={"path": str(snapshot_dir / "nonexistent.arrow")},
        )
        with pytest.raises(KeyError):
            await db.restore(handle)

    @pytest.mark.asyncio
    async def test_restore_missing_path_metadata_raises(self, snapshot_dir):
        """Restoring with no path metadata raises KeyError."""
        db = LedgerDB(k=10, snapshot_dir=snapshot_dir)

        handle = SnapshotHandle(snapshot_id="999")
        with pytest.raises(KeyError):
            await db.restore(handle)


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------


class TestCompaction:
    """Test table compaction after deletions."""

    def test_compact_removes_dead_rows(self):
        """After compaction, table row count matches live UTxO count."""
        db = LedgerDB(k=10)

        entries = [make_utxo_entry(i, 0) for i in range(10)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        # Delete half.
        consumed = [entries[i][0] for i in range(5)]
        db.apply_block(consumed=consumed, created=[], block_slot=2)

        assert db.utxo_count == 5
        # Table still has 10 rows (dead rows not removed yet).
        assert len(db._table) == 10

        db.compact()
        assert len(db._table) == 5
        assert db.utxo_count == 5

        # All remaining entries still accessible.
        for i in range(5, 10):
            assert db.get_utxo(entries[i][0]) is not None

    def test_compact_empty_db(self):
        """Compacting an empty DB is a no-op."""
        db = LedgerDB(k=10)
        db.compact()
        assert db.utxo_count == 0
        assert len(db._table) == 0


# ---------------------------------------------------------------------------
# StateStore Protocol Compliance
# ---------------------------------------------------------------------------


class TestStateStoreProtocol:
    """Verify LedgerDB satisfies the StateStore protocol."""

    def test_is_state_store(self):
        """LedgerDB is structurally compatible with StateStore."""
        db = LedgerDB(k=10)
        assert isinstance(db, StateStore)

    @pytest.mark.asyncio
    async def test_async_get(self):
        """The async get method works for protocol compliance."""
        db = LedgerDB(k=10)
        key, cols = make_utxo_entry(1, 0)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        result = await db.get(key)
        assert result == key

        missing = await db.get(make_txin(999, 0))
        assert missing is None

    @pytest.mark.asyncio
    async def test_batch_put_and_delete(self):
        """batch_put and batch_delete work for protocol compliance."""
        db = LedgerDB(k=10)

        keys = [make_txin(i, 0) for i in range(5)]
        items = [(k, b"value") for k in keys]

        await db.batch_put(items)
        assert db.utxo_count == 5

        await db.batch_delete(keys[:3])
        assert db.utxo_count == 2


# ---------------------------------------------------------------------------
# Performance Benchmarks
# ---------------------------------------------------------------------------


class TestPerformanceBenchmarks:
    """Performance benchmarks for LedgerDB operations.

    These use pytest-benchmark when available, otherwise fall back to
    simple timing assertions.
    """

    def _build_db(self, n_utxos: int, k: int = 2160) -> LedgerDB:
        """Create a LedgerDB with n_utxos entries."""
        db = LedgerDB(k=k)
        entries = [make_utxo_entry(i, 0) for i in range(n_utxos)]
        db.apply_block(consumed=[], created=entries, block_slot=1)
        return db

    def test_lookup_performance(self):
        """Point lookup should be fast (~single-digit μs)."""
        import time

        db = self._build_db(10_000)
        key = make_txin(5000, 0)

        start = time.perf_counter()
        for _ in range(1000):
            db.get_utxo(key)
        elapsed = time.perf_counter() - start
        us_per_op = elapsed / 1000 * 1e6
        assert us_per_op < 100, f"Lookup too slow: {us_per_op:.1f} μs/op"

    def test_block_apply_performance(self):
        """Applying a block with ~300 mutations should be fast."""
        import time

        db = LedgerDB(k=10)
        initial = [make_utxo_entry(i, 0) for i in range(150)]
        db.apply_block(consumed=[], created=initial, block_slot=1)

        start = time.perf_counter()
        consumed = [initial[i][0] for i in range(150)]
        created = [make_utxo_entry(150 + i, 0) for i in range(150)]
        db.apply_block(consumed=consumed, created=created, block_slot=2)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"Block apply too slow: {elapsed_ms:.1f} ms"

    def test_rollback_performance(self):
        """Rollback of 100 blocks should complete quickly."""
        import time

        k = 100
        db = LedgerDB(k=k)
        for slot in range(1, k + 1):
            entries = [make_utxo_entry(slot * 10 + i, 0) for i in range(3)]
            db.apply_block(consumed=[], created=entries, block_slot=slot)

        start = time.perf_counter()
        db.rollback(k)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Rollback too slow: {elapsed_ms:.1f} ms"


# ---------------------------------------------------------------------------
# BlockDiff dataclass
# ---------------------------------------------------------------------------


class TestBlockDiff:
    """Test the BlockDiff dataclass."""

    def test_creation(self):
        """BlockDiff is frozen and stores consumed/created correctly."""
        diff = BlockDiff(
            consumed=[(b"key1", {"value": 1})],
            created=[(b"key2", {"value": 2})],
            block_slot=42,
        )
        assert len(diff.consumed) == 1
        assert len(diff.created) == 1
        assert diff.block_slot == 42

    def test_default_slot(self):
        """BlockDiff defaults to slot 0."""
        diff = BlockDiff(consumed=[], created=[])
        assert diff.block_slot == 0


# ---------------------------------------------------------------------------
# Fork switch — rollback and reapply
# ---------------------------------------------------------------------------


class TestForkSwitch:
    """Test fork switching: rollback N blocks, apply different blocks.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.API.switchFork
    """

    def test_fork_switch_rollback_and_reapply(self):
        """Rollback N blocks, apply different blocks, verify UTxO state
        is correct for the new fork.

        Simulates a chain fork: blocks A1, A2 produce UTxOs X, Y.
        After rollback, blocks B1, B2 produce UTxOs P, Q instead.
        """
        db = LedgerDB(k=10)

        # Initial state: block 0 creates base UTxOs
        base_entries = [make_utxo_entry(100 + i, 0, value=(100 + i) * 1_000_000) for i in range(3)]
        db.apply_block(consumed=[], created=base_entries, block_slot=1)

        # Fork A: blocks 2, 3 — consume base[0], create new UTxOs
        fork_a_entries = [make_utxo_entry(200 + i, 0, value=200_000_000) for i in range(2)]
        db.apply_block(consumed=[base_entries[0][0]], created=fork_a_entries, block_slot=2)

        fork_a_entries_2 = [make_utxo_entry(300, 0, value=300_000_000)]
        db.apply_block(consumed=[base_entries[1][0]], created=fork_a_entries_2, block_slot=3)

        # Verify fork A state
        assert db.get_utxo(fork_a_entries[0][0]) is not None
        assert db.get_utxo(fork_a_entries_2[0][0]) is not None
        assert db.get_utxo(base_entries[0][0]) is None  # consumed
        assert db.get_utxo(base_entries[1][0]) is None  # consumed

        # Switch to fork B: rollback 2 blocks
        db.rollback(2)

        # After rollback: base UTxOs 0,1 should be restored, fork A UTxOs gone
        assert db.get_utxo(base_entries[0][0]) is not None
        assert db.get_utxo(base_entries[1][0]) is not None
        assert db.get_utxo(fork_a_entries[0][0]) is None
        assert db.get_utxo(fork_a_entries_2[0][0]) is None

        # Apply fork B: consume base[2], create totally new UTxOs
        fork_b_entries = [make_utxo_entry(400 + i, 0, value=400_000_000) for i in range(2)]
        db.apply_block(consumed=[base_entries[2][0]], created=fork_b_entries, block_slot=2)

        # Verify fork B state
        assert db.get_utxo(base_entries[0][0]) is not None  # untouched
        assert db.get_utxo(base_entries[1][0]) is not None  # untouched
        assert db.get_utxo(base_entries[2][0]) is None  # consumed in fork B
        assert db.get_utxo(fork_b_entries[0][0]) is not None
        assert db.get_utxo(fork_b_entries[1][0]) is not None
        # Fork A UTxOs should definitely still be gone
        assert db.get_utxo(fork_a_entries[0][0]) is None

    def test_switch_same_chain_is_identity(self):
        """Rollback N then reapply same blocks = no change.

        This is an important invariant: applying and rolling back the
        same mutations should be a no-op.
        """
        db = LedgerDB(k=10)

        # Block 1: create UTxOs
        entries_1 = [make_utxo_entry(i, 0, value=i * 1_000_000) for i in range(5)]
        db.apply_block(consumed=[], created=entries_1, block_slot=1)

        # Block 2: consume 2, create 2
        consumed_2 = [entries_1[0][0], entries_1[1][0]]
        created_2 = [make_utxo_entry(10 + i, 0, value=10_000_000) for i in range(2)]
        db.apply_block(consumed=consumed_2, created=created_2, block_slot=2)

        # Snapshot current state
        utxo_count_before = db.utxo_count
        remaining_keys = set(k for k in [e[0] for e in entries_1[2:]] + [e[0] for e in created_2])

        # Rollback 1 block, then reapply the same block
        db.rollback(1)
        db.apply_block(consumed=consumed_2, created=created_2, block_slot=2)

        # State should be identical
        assert db.utxo_count == utxo_count_before
        for key in remaining_keys:
            assert db.get_utxo(key) is not None
        for key in consumed_2:
            assert db.get_utxo(key) is None


# ---------------------------------------------------------------------------
# Past ledger lookup
# ---------------------------------------------------------------------------


class TestPastLedgerLookup:
    """Test historical ledger state queries.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.API.getPastLedgerAt
    """

    def test_past_ledger_lookup_within_k(self):
        """Look up ledger state at a historical point within k blocks.

        After applying 5 blocks with k=10, we should be able to look
        back to any of the 5 stored states.
        """
        db = LedgerDB(k=10)

        # Apply 5 blocks, each creating one UTxO
        all_entries = []
        for slot in range(1, 6):
            key, cols = make_utxo_entry(slot, 0, value=slot * 1_000_000)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)
            all_entries.append((key, cols))

        assert db.utxo_count == 5

        # Look back 3 blocks — should see state after block 2
        past = db.get_past_ledger(3)
        assert past is not None
        assert past.utxo_count == 2  # Only blocks 1 and 2's UTxOs

        # Entries from blocks 1 and 2 should exist
        assert past.get_utxo(all_entries[0][0]) is not None
        assert past.get_utxo(all_entries[1][0]) is not None

        # Entries from blocks 3, 4, 5 should NOT exist
        assert past.get_utxo(all_entries[2][0]) is None
        assert past.get_utxo(all_entries[3][0]) is None
        assert past.get_utxo(all_entries[4][0]) is None

    def test_past_ledger_beyond_k_returns_none(self):
        """Historical point beyond k is unavailable.

        With k=3, after pushing 3 blocks, we can look back 3 but not 4.
        """
        db = LedgerDB(k=3)

        for slot in range(1, 4):
            key, cols = make_utxo_entry(slot, 0)
            db.apply_block(consumed=[], created=[(key, cols)], block_slot=slot)

        assert db.max_rollback == 3

        # Looking back exactly 3 should work
        past = db.get_past_ledger(3)
        assert past is not None
        assert past.utxo_count == 0  # Back to empty anchor

        # Looking back 4 should return None
        past = db.get_past_ledger(4)
        assert past is None

    def test_past_ledger_zero_is_current(self):
        """Looking back 0 blocks returns current state."""
        db = LedgerDB(k=10)

        key, cols = make_utxo_entry(1, 0, value=42_000_000)
        db.apply_block(consumed=[], created=[(key, cols)], block_slot=1)

        past = db.get_past_ledger(0)
        assert past is not None
        assert past.utxo_count == 1
        result = past.get_utxo(key)
        assert result is not None
        assert result["value"] == 42_000_000
