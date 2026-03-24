"""LedgerDB tests — UTxO apply/consume, snapshot/restore, count tracking.

Covers:
- apply_block creates UTxOs
- apply_block consumes UTxOs
- snapshot and restore round-trip
- utxo_count tracking accuracy

Haskell references:
    Ouroboros.Consensus.Storage.LedgerDB.API (applyBlock, getPastLedger)
    Ouroboros.Consensus.Storage.LedgerDB.BackingStore (snapshot, restore)
    Test.Ouroboros.Storage.LedgerDB

Antithesis compatibility:
    All tests use deterministic data and can be replayed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from vibe.cardano.storage.ledger import LedgerDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_utxo(index: int) -> tuple[bytes, dict]:
    """Create a deterministic UTxO entry.

    Key is 34 bytes: 32-byte tx_hash + 2-byte big-endian tx_index.
    """
    tx_hash = index.to_bytes(32, "big")
    tx_index = index % 65536
    key = tx_hash + tx_index.to_bytes(2, "big")
    col_vals = {
        "tx_hash": tx_hash,
        "tx_index": tx_index,
        "address": f"addr_test1qz{index:040d}",
        "value": (index + 1) * 1_000_000,
        "datum_hash": b"",
    }
    return key, col_vals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestApplyBlockCreatesUtxos:
    """apply_block with created entries adds UTxOs to the set.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.API
        applyBlock creates new UTxO entries from transaction outputs.
    """

    def test_apply_block_creates_utxos(self) -> None:
        """Created UTxOs are queryable after apply_block."""
        db = LedgerDB(k=10)

        entries = [_make_utxo(i) for i in range(5)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        assert db.utxo_count == 5

        for key, col_vals in entries:
            result = db.get_utxo(key)
            assert result is not None, f"UTxO {key.hex()[:16]} not found"
            assert result["tx_hash"] == col_vals["tx_hash"]
            assert result["tx_index"] == col_vals["tx_index"]
            assert result["address"] == col_vals["address"]
            assert result["value"] == col_vals["value"]

    def test_apply_multiple_blocks_accumulates(self) -> None:
        """UTxOs from multiple blocks accumulate in the set."""
        db = LedgerDB(k=10)

        batch1 = [_make_utxo(i) for i in range(3)]
        batch2 = [_make_utxo(i) for i in range(10, 13)]

        db.apply_block(consumed=[], created=batch1, block_slot=1)
        db.apply_block(consumed=[], created=batch2, block_slot=2)

        assert db.utxo_count == 6

        for key, _ in batch1 + batch2:
            assert db.get_utxo(key) is not None


class TestApplyBlockConsumesUtxos:
    """apply_block with consumed entries removes UTxOs from the set.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.API
        applyBlock removes consumed UTxO entries (spent transaction inputs).
    """

    def test_apply_block_consumes_utxos(self) -> None:
        """Consumed UTxOs are removed and no longer queryable."""
        db = LedgerDB(k=10)

        entries = [_make_utxo(i) for i in range(5)]
        db.apply_block(consumed=[], created=entries, block_slot=1)
        assert db.utxo_count == 5

        # Consume entries 0 and 2
        consumed_keys = [entries[0][0], entries[2][0]]
        db.apply_block(consumed=consumed_keys, created=[], block_slot=2)

        assert db.utxo_count == 3

        # Consumed are gone
        assert db.get_utxo(entries[0][0]) is None
        assert db.get_utxo(entries[2][0]) is None

        # Remaining are still present
        assert db.get_utxo(entries[1][0]) is not None
        assert db.get_utxo(entries[3][0]) is not None
        assert db.get_utxo(entries[4][0]) is not None

    def test_consume_and_create_in_same_block(self) -> None:
        """A block can both consume and create UTxOs atomically."""
        db = LedgerDB(k=10)

        # Block 1: create 3 UTxOs
        entries = [_make_utxo(i) for i in range(3)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        # Block 2: consume entry 0, create entry 10
        new_entry = _make_utxo(10)
        db.apply_block(
            consumed=[entries[0][0]],
            created=[new_entry],
            block_slot=2,
        )

        assert db.utxo_count == 3  # 3 - 1 + 1
        assert db.get_utxo(entries[0][0]) is None
        assert db.get_utxo(new_entry[0]) is not None


class TestSnapshotAndRestore:
    """Snapshot writes an Arrow IPC file; restore rebuilds state from it.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.BackingStore
        snapshot / restore operations for crash recovery.
    """

    @pytest.mark.asyncio
    async def test_snapshot_and_restore(self) -> None:
        """Full round-trip: create UTxOs, snapshot, restore into fresh DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))

            entries = [_make_utxo(i) for i in range(8)]
            db.apply_block(consumed=[], created=entries, block_slot=1)

            # Consume 2
            db.apply_block(
                consumed=[entries[0][0], entries[3][0]],
                created=[],
                block_slot=2,
            )
            assert db.utxo_count == 6

            handle = await db.snapshot()

            # Restore into a completely fresh DB
            db2 = LedgerDB(k=10, snapshot_dir=Path(tmpdir))
            await db2.restore(handle)

            assert db2.utxo_count == 6

            # Consumed entries must be absent
            assert db2.get_utxo(entries[0][0]) is None
            assert db2.get_utxo(entries[3][0]) is None

            # Surviving entries must match
            for i in [1, 2, 4, 5, 6, 7]:
                key, col_vals = entries[i]
                result = db2.get_utxo(key)
                assert result is not None
                assert result["value"] == col_vals["value"]
                assert result["address"] == col_vals["address"]


class TestUtxoCountTracking:
    """utxo_count accurately reflects the live UTxO set size.

    Haskell reference:
        The Haskell LedgerDB tracks UTxO set size for monitoring
        and resource management.
    """

    def test_utxo_count_tracking(self) -> None:
        """Count stays accurate through creates, consumes, and rollbacks."""
        db = LedgerDB(k=10)

        assert db.utxo_count == 0

        # Create 5
        entries = [_make_utxo(i) for i in range(5)]
        db.apply_block(consumed=[], created=entries, block_slot=1)
        assert db.utxo_count == 5

        # Consume 2
        db.apply_block(
            consumed=[entries[0][0], entries[1][0]],
            created=[],
            block_slot=2,
        )
        assert db.utxo_count == 3

        # Create 3 more
        more = [_make_utxo(i) for i in range(10, 13)]
        db.apply_block(consumed=[], created=more, block_slot=3)
        assert db.utxo_count == 6

        # Rollback last block — should undo the 3 creates
        db.rollback(1)
        assert db.utxo_count == 3

        # Rollback consume block — should restore the 2 consumed
        db.rollback(1)
        assert db.utxo_count == 5

    def test_utxo_count_after_compact(self) -> None:
        """Compaction does not change the utxo_count."""
        db = LedgerDB(k=10)

        entries = [_make_utxo(i) for i in range(10)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        # Consume half
        consumed_keys = [entries[i][0] for i in range(0, 10, 2)]
        db.apply_block(consumed=consumed_keys, created=[], block_slot=2)
        assert db.utxo_count == 5

        db.compact()
        assert db.utxo_count == 5

    def test_contains_operator(self) -> None:
        """The __contains__ operator matches utxo_count semantics."""
        db = LedgerDB(k=10)

        entry = _make_utxo(0)
        assert entry[0] not in db

        db.apply_block(consumed=[], created=[entry], block_slot=1)
        assert entry[0] in db
        assert len(db) == 1

        db.apply_block(consumed=[entry[0]], created=[], block_slot=2)
        assert entry[0] not in db
        assert len(db) == 0
