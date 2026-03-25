"""Tests for VolatileDB — hash-indexed recent block storage.

Covers the core VolatileDB operations against the test specifications from
VNODE-182: block add/get, successor map, garbage collection, persistence,
fork tracking, and KeyValueStore protocol conformance.

Test specifications referenced (from test_specifications table):
- test_garbage_collect_removes_blocks_older_than_k
- test_garbage_collect_filters_volatile_blocks
- test_garbage_collect_collectable_predicate
- test_garbage_collect_removes_old_non_chain_blocks
- test_blocks_remain_in_volatile_after_copy_to_immutable
- test_copy_to_immutable_does_not_garbage_collect
- test_garbage_collect_file_removes_all_hashes_from_maps
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe.cardano.storage.volatile import BlockInfo, ClosedVolatileDBError, VolatileDB
from vibe.core.storage.interfaces import KeyValueStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash(n: int) -> bytes:
    """Generate a deterministic 32-byte hash for test block ``n``."""
    return n.to_bytes(32, "big")


def _cbor(n: int) -> bytes:
    """Generate fake CBOR bytes for test block ``n``."""
    return f"cbor-block-{n}".encode()


def _genesis_hash() -> bytes:
    """The zero hash representing genesis."""
    return b"\x00" * 32


async def _add_chain(
    db: VolatileDB,
    start_slot: int,
    count: int,
    predecessor: bytes | None = None,
    start_number: int = 1,
) -> list[BlockInfo]:
    """Add a linear chain of blocks to the DB and return their BlockInfo."""
    if predecessor is None:
        predecessor = _genesis_hash()

    infos = []
    for i in range(count):
        block_num = start_number + i
        slot = start_slot + i
        h = _hash(block_num)
        info = BlockInfo(
            block_hash=h,
            slot=slot,
            predecessor_hash=predecessor,
            block_number=block_num,
        )
        await db.add_block(h, slot, predecessor, block_num, _cbor(block_num))
        infos.append(info)
        predecessor = h
    return infos


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestKeyValueStoreConformance:
    """Verify VolatileDB satisfies the KeyValueStore protocol."""

    def test_volatile_db_is_key_value_store(self) -> None:
        """VolatileDB must be a structural subtype of KeyValueStore."""
        assert isinstance(VolatileDB(), KeyValueStore)

    async def test_put_and_get(self) -> None:
        db = VolatileDB()
        await db.put(b"key1", b"value1")
        assert await db.get(b"key1") == b"value1"

    async def test_get_missing_returns_none(self) -> None:
        db = VolatileDB()
        assert await db.get(b"nonexistent") is None

    async def test_delete_existing(self) -> None:
        db = VolatileDB()
        await db.put(b"key1", b"value1")
        assert await db.delete(b"key1") is True
        assert await db.get(b"key1") is None

    async def test_delete_missing_returns_false(self) -> None:
        db = VolatileDB()
        assert await db.delete(b"nonexistent") is False

    async def test_contains(self) -> None:
        db = VolatileDB()
        await db.put(b"key1", b"value1")
        assert await db.contains(b"key1") is True
        assert await db.contains(b"key2") is False

    async def test_keys(self) -> None:
        db = VolatileDB()
        await db.put(b"a", b"1")
        await db.put(b"b", b"2")
        assert set(await db.keys()) == {b"a", b"b"}


# ---------------------------------------------------------------------------
# Block add / get
# ---------------------------------------------------------------------------


class TestBlockOperations:
    """Test add_block, get_block, get_block_info."""

    async def test_add_and_get_block(self) -> None:
        db = VolatileDB()
        h = _hash(1)
        await db.add_block(h, 100, _genesis_hash(), 1, _cbor(1))
        assert await db.get_block(h) == _cbor(1)

    async def test_get_missing_block_returns_none(self) -> None:
        db = VolatileDB()
        assert await db.get_block(_hash(999)) is None

    async def test_add_block_stores_metadata(self) -> None:
        db = VolatileDB()
        h = _hash(1)
        pred = _genesis_hash()
        await db.add_block(h, 42, pred, 1, _cbor(1))

        info = await db.get_block_info(h)
        assert info is not None
        assert info.block_hash == h
        assert info.slot == 42
        assert info.predecessor_hash == pred
        assert info.block_number == 1

    async def test_get_block_info_missing_returns_none(self) -> None:
        db = VolatileDB()
        assert await db.get_block_info(_hash(999)) is None

    async def test_block_count(self) -> None:
        db = VolatileDB()
        assert db.block_count == 0
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        assert db.block_count == 1
        await db.add_block(_hash(2), 2, _hash(1), 2, _cbor(2))
        assert db.block_count == 2

    async def test_get_all_block_info(self) -> None:
        db = VolatileDB()
        await _add_chain(db, 1, 3)
        all_info = await db.get_all_block_info()
        assert len(all_info) == 3
        assert all(isinstance(v, BlockInfo) for v in all_info.values())


# ---------------------------------------------------------------------------
# Successor map
# ---------------------------------------------------------------------------


class TestSuccessorMap:
    """Test successor map operations used by chain selection."""

    async def test_successors_of_genesis(self) -> None:
        """Genesis hash should have successors after adding blocks."""
        db = VolatileDB()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        succs = await db.get_successors(_genesis_hash())
        assert succs == [_hash(1)]

    async def test_linear_chain_successors(self) -> None:
        """Each block in a linear chain has exactly one successor."""
        db = VolatileDB()
        await _add_chain(db, 1, 5)

        # Genesis -> block 1
        assert await db.get_successors(_genesis_hash()) == [_hash(1)]
        # Block 1 -> block 2
        assert await db.get_successors(_hash(1)) == [_hash(2)]
        # Block 4 -> block 5
        assert await db.get_successors(_hash(4)) == [_hash(5)]
        # Block 5 (tip) has no successors
        assert await db.get_successors(_hash(5)) == []

    async def test_fork_tracking(self) -> None:
        """A predecessor with two successors represents a fork.

        This is the core data structure for chain selection: when two blocks
        extend the same predecessor, the successor map captures both forks.
        """
        db = VolatileDB()
        # Block A at slot 1 from genesis
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        # Fork: block B and block C both extend block A
        await db.add_block(_hash(2), 2, _hash(1), 2, _cbor(2))
        await db.add_block(_hash(3), 2, _hash(1), 3, _cbor(3))

        succs = await db.get_successors(_hash(1))
        assert set(succs) == {_hash(2), _hash(3)}

    async def test_successors_empty_for_unknown_hash(self) -> None:
        db = VolatileDB()
        assert await db.get_successors(_hash(999)) == []

    async def test_no_duplicate_successors(self) -> None:
        """Adding the same block twice should not create duplicate entries."""
        db = VolatileDB()
        h = _hash(1)
        pred = _genesis_hash()
        await db.add_block(h, 1, pred, 1, _cbor(1))
        await db.add_block(h, 1, pred, 1, _cbor(1))  # re-add
        assert await db.get_successors(pred) == [h]

    async def test_successor_removed_on_block_delete(self) -> None:
        """Removing a block should clean up the successor map."""
        db = VolatileDB()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        await db.remove_block(_hash(1))
        assert await db.get_successors(_genesis_hash()) == []


# ---------------------------------------------------------------------------
# Max slot tracking
# ---------------------------------------------------------------------------


class TestMaxSlot:
    """Test get_max_slot tracking."""

    async def test_empty_db_max_slot(self) -> None:
        db = VolatileDB()
        assert await db.get_max_slot() == -1

    async def test_max_slot_tracks_highest(self) -> None:
        db = VolatileDB()
        await db.add_block(_hash(1), 10, _genesis_hash(), 1, _cbor(1))
        assert await db.get_max_slot() == 10
        await db.add_block(_hash(2), 20, _hash(1), 2, _cbor(2))
        assert await db.get_max_slot() == 20

    async def test_max_slot_recomputed_on_tip_removal(self) -> None:
        """If the block at max slot is removed, max_slot should update."""
        db = VolatileDB()
        await db.add_block(_hash(1), 10, _genesis_hash(), 1, _cbor(1))
        await db.add_block(_hash(2), 20, _hash(1), 2, _cbor(2))
        await db.remove_block(_hash(2))
        assert await db.get_max_slot() == 10

    async def test_max_slot_returns_negative_after_all_removed(self) -> None:
        db = VolatileDB()
        await db.add_block(_hash(1), 5, _genesis_hash(), 1, _cbor(1))
        await db.remove_block(_hash(1))
        assert await db.get_max_slot() == -1


# ---------------------------------------------------------------------------
# Garbage collection
# ---------------------------------------------------------------------------


class TestGarbageCollection:
    """Test GC behavior against multiple test specifications.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.garbageCollect
        Removes all blocks with slot <= the given slot.
    """

    async def test_gc_removes_blocks_at_or_below_slot(self) -> None:
        """test_garbage_collect_removes_blocks_older_than_k:
        All blocks with slots <= immutable_tip_slot are removed.
        """
        db = VolatileDB()
        await _add_chain(db, 1, 10)
        removed = await db.gc(immutable_tip_slot=5)
        assert removed == 5
        assert db.block_count == 5
        # Blocks 1-5 (slots 1-5) should be gone
        for i in range(1, 6):
            assert await db.get_block(_hash(i)) is None
        # Blocks 6-10 (slots 6-10) should remain
        for i in range(6, 11):
            assert await db.get_block(_hash(i)) is not None

    async def test_gc_removes_zero_when_nothing_old(self) -> None:
        """GC with a slot below all stored blocks removes nothing."""
        db = VolatileDB()
        await _add_chain(db, 100, 5, start_number=1)
        removed = await db.gc(immutable_tip_slot=50)
        assert removed == 0
        assert db.block_count == 5

    async def test_gc_removes_all_when_slot_at_max(self) -> None:
        """GC at or above max slot removes everything."""
        db = VolatileDB()
        await _add_chain(db, 1, 5)
        removed = await db.gc(immutable_tip_slot=5)
        assert removed == 5
        assert db.block_count == 0
        assert await db.get_max_slot() == -1

    async def test_gc_on_empty_db(self) -> None:
        """GC on an empty DB is a no-op."""
        db = VolatileDB()
        removed = await db.gc(immutable_tip_slot=100)
        assert removed == 0

    async def test_gc_removes_fork_blocks(self) -> None:
        """test_garbage_collect_removes_old_non_chain_blocks:
        GC removes old blocks on forks too, not just the main chain.
        """
        db = VolatileDB()
        # Main chain: genesis -> A(slot 1) -> B(slot 2) -> C(slot 3)
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        await db.add_block(_hash(2), 2, _hash(1), 2, _cbor(2))
        await db.add_block(_hash(3), 3, _hash(2), 3, _cbor(3))
        # Fork: genesis -> X(slot 1) -> Y(slot 2)
        await db.add_block(_hash(10), 1, _genesis_hash(), 1, _cbor(10))
        await db.add_block(_hash(11), 2, _hash(10), 2, _cbor(11))

        removed = await db.gc(immutable_tip_slot=2)
        # Should remove A, B, X, Y (all at slot <= 2) = 4 blocks
        assert removed == 4
        # Only C (slot 3) remains
        assert db.block_count == 1
        assert await db.get_block(_hash(3)) is not None

    async def test_gc_updates_successor_map(self) -> None:
        """After GC, the successor map should be cleaned up."""
        db = VolatileDB()
        await _add_chain(db, 1, 5)
        await db.gc(immutable_tip_slot=3)
        # Predecessor entries for removed blocks should be cleaned
        assert await db.get_successors(_genesis_hash()) == []

    async def test_gc_updates_max_slot(self) -> None:
        """Max slot should reflect remaining blocks after GC."""
        db = VolatileDB()
        await _add_chain(db, 1, 10)
        await db.gc(immutable_tip_slot=7)
        assert await db.get_max_slot() == 10

    async def test_gc_collectable_predicate(self) -> None:
        """test_garbage_collect_collectable_predicate:
        Blocks at slots > immutable_tip_slot are not collectable.
        """
        db = VolatileDB()
        # Add blocks at slots 1, 5, 10, 15, 20
        for i, slot in enumerate([1, 5, 10, 15, 20], start=1):
            pred = _genesis_hash() if i == 1 else _hash(i - 1)
            await db.add_block(_hash(i), slot, pred, i, _cbor(i))

        removed = await db.gc(immutable_tip_slot=10)
        assert removed == 3  # slots 1, 5, 10
        assert db.block_count == 2  # slots 15, 20 remain

    async def test_blocks_remain_until_gc(self) -> None:
        """test_blocks_remain_in_volatile_after_copy_to_immutable /
        test_copy_to_immutable_does_not_garbage_collect:

        Blocks can coexist in both VolatileDB and ImmutableDB. Removing
        from VolatileDB is a separate GC step, not automatic.
        """
        db = VolatileDB()
        await _add_chain(db, 1, 10)

        # Simulate "copy to immutable" by reading blocks (no removal yet)
        for i in range(1, 6):
            data = await db.get_block(_hash(i))
            assert data is not None  # Still readable

        # All 10 blocks are still in VolatileDB
        assert db.block_count == 10

        # Only GC actually removes them
        await db.gc(immutable_tip_slot=5)
        assert db.block_count == 5


# ---------------------------------------------------------------------------
# Block removal
# ---------------------------------------------------------------------------


class TestBlockRemoval:
    """Test individual block removal (distinct from GC)."""

    async def test_remove_existing_block(self) -> None:
        db = VolatileDB()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        assert await db.remove_block(_hash(1)) is True
        assert await db.get_block(_hash(1)) is None
        assert await db.get_block_info(_hash(1)) is None

    async def test_remove_nonexistent_block(self) -> None:
        db = VolatileDB()
        assert await db.remove_block(_hash(999)) is False

    async def test_remove_cleans_successor_map(self) -> None:
        """test_garbage_collect_file_removes_all_hashes_from_maps:
        Removing a block should remove it from the predecessor's successor list.
        """
        db = VolatileDB()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        await db.add_block(_hash(2), 2, _hash(1), 2, _cbor(2))
        await db.add_block(_hash(3), 3, _hash(1), 3, _cbor(3))  # fork

        await db.remove_block(_hash(2))
        succs = await db.get_successors(_hash(1))
        assert _hash(2) not in succs
        assert _hash(3) in succs


# ---------------------------------------------------------------------------
# On-disk persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test on-disk block file storage and recovery."""

    async def test_add_block_creates_file(self, tmp_path: Path) -> None:
        db = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        h = _hash(1)
        await db.add_block(h, 1, _genesis_hash(), 1, _cbor(1))
        filepath = tmp_path / f"{h.hex()}.block"
        assert filepath.exists()
        assert filepath.read_bytes() == _cbor(1)

    async def test_remove_block_deletes_file(self, tmp_path: Path) -> None:
        db = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        h = _hash(1)
        await db.add_block(h, 1, _genesis_hash(), 1, _cbor(1))
        await db.remove_block(h)
        filepath = tmp_path / f"{h.hex()}.block"
        assert not filepath.exists()

    async def test_gc_deletes_files(self, tmp_path: Path) -> None:
        db = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        await _add_chain(db, 1, 5)
        await db.gc(immutable_tip_slot=3)
        # Blocks 1-3 files should be gone
        for i in range(1, 4):
            assert not (tmp_path / f"{_hash(i).hex()}.block").exists()
        # Blocks 4-5 files should remain
        for i in range(4, 6):
            assert (tmp_path / f"{_hash(i).hex()}.block").exists()

    async def test_load_from_disk_recovers_state(self, tmp_path: Path) -> None:
        """Startup recovery: scan directory to rebuild in-memory indices."""
        # Phase 1: populate and close
        db1 = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        await _add_chain(db1, 10, 3)

        # Phase 2: new instance, load from disk
        db2 = VolatileDB(db_dir=tmp_path, write_batch_size=1)

        def parse_header(cbor_bytes: bytes) -> BlockInfo:
            """Reverse-engineer the test block number from fake CBOR."""
            # Our _cbor() produces "cbor-block-N"
            n = int(cbor_bytes.decode().split("-")[-1])
            return BlockInfo(
                block_hash=_hash(n),
                slot=10 + n - 1,  # matches _add_chain(start_slot=10)
                predecessor_hash=_hash(n - 1) if n > 1 else _genesis_hash(),
                block_number=n,
            )

        loaded = await db2.load_from_disk(parse_header)
        assert loaded == 3
        assert db2.block_count == 3
        assert await db2.get_max_slot() == 12

        # Successor map should be rebuilt
        assert await db2.get_successors(_genesis_hash()) == [_hash(1)]

    async def test_load_from_disk_skips_corrupt_files(self, tmp_path: Path) -> None:
        """Corrupt block files are skipped during recovery."""
        db = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))

        # Write a corrupt file
        (tmp_path / "deadbeef.block").write_bytes(b"not valid")

        db2 = VolatileDB(db_dir=tmp_path, write_batch_size=1)

        def parse_header(cbor_bytes: bytes) -> BlockInfo:
            text = cbor_bytes.decode()
            if not text.startswith("cbor-block-"):
                raise ValueError("corrupt")
            n = int(text.split("-")[-1])
            return BlockInfo(
                block_hash=_hash(n),
                slot=n,
                predecessor_hash=_genesis_hash(),
                block_number=n,
            )

        loaded = await db2.load_from_disk(parse_header)
        assert loaded == 1  # Only the valid block

    async def test_load_from_disk_without_dir_raises(self) -> None:
        """In-memory-only VolatileDB cannot load from disk."""
        db = VolatileDB()
        with pytest.raises(FileNotFoundError):
            await db.load_from_disk(lambda x: x)

    async def test_put_creates_file(self, tmp_path: Path) -> None:
        """KeyValueStore.put also persists to disk."""
        db = VolatileDB(db_dir=tmp_path, write_batch_size=1)
        h = _hash(42)
        await db.put(h, b"raw-data")
        filepath = tmp_path / f"{h.hex()}.block"
        assert filepath.exists()
        assert filepath.read_bytes() == b"raw-data"

    async def test_db_dir_created_if_missing(self, tmp_path: Path) -> None:
        """VolatileDB creates the db_dir if it doesn't exist."""
        new_dir = tmp_path / "volatile" / "blocks"
        db = VolatileDB(db_dir=new_dir, write_batch_size=1)
        assert new_dir.exists()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        assert (new_dir / f"{_hash(1).hex()}.block").exists()


# ---------------------------------------------------------------------------
# Close then operate
# ---------------------------------------------------------------------------


class TestCloseThenOperate:
    """test_close_then_operate_raises

    Operations on a closed VolatileDB raise ClosedVolatileDBError.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.API.ClosedDBError
    """

    async def test_close_then_get_raises(self) -> None:
        """get() on a closed DB raises."""
        db = VolatileDB()
        await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))
        db.close()

        with pytest.raises(ClosedVolatileDBError):
            await db.get(_hash(1))

    async def test_close_then_add_block_raises(self) -> None:
        """add_block() on a closed DB raises."""
        db = VolatileDB()
        db.close()

        with pytest.raises(ClosedVolatileDBError):
            await db.add_block(_hash(1), 1, _genesis_hash(), 1, _cbor(1))

    async def test_close_is_idempotent(self) -> None:
        """Closing twice doesn't raise."""
        db = VolatileDB()
        db.close()
        db.close()
        assert db.is_closed

    async def test_is_closed_property(self) -> None:
        """is_closed reflects the state correctly."""
        db = VolatileDB()
        assert not db.is_closed
        db.close()
        assert db.is_closed


# ---------------------------------------------------------------------------
# Duplicate block — idempotent add
# ---------------------------------------------------------------------------


class TestDuplicateBlock:
    """test_duplicate_block_same_hash_ignored

    Adding the same block twice is idempotent — no error, no duplicate.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.putBlock
        "If the block is already stored, this is a no-op"
    """

    async def test_duplicate_block_same_hash_ignored(self) -> None:
        """Adding the same block twice results in only one stored block."""
        db = VolatileDB()
        h = _hash(1)
        pred = _genesis_hash()
        cbor = _cbor(1)

        await db.add_block(h, 1, pred, 1, cbor)
        assert db.block_count == 1

        # Add the exact same block again
        await db.add_block(h, 1, pred, 1, cbor)
        assert db.block_count == 1  # Still 1, not 2

        # The block should still be retrievable
        assert await db.get_block(h) == cbor

        # Successor map should not have duplicates
        succs = await db.get_successors(pred)
        assert succs == [h]  # Only one entry

    async def test_duplicate_block_different_cbor_overwrites(self) -> None:
        """If the same hash is added with different CBOR, the latest wins.

        This matches Python dict behavior. In practice, blocks with the
        same hash should have the same content.
        """
        db = VolatileDB()
        h = _hash(1)
        pred = _genesis_hash()

        await db.add_block(h, 1, pred, 1, b"original")
        await db.add_block(h, 1, pred, 1, b"updated")

        assert db.block_count == 1
        assert await db.get_block(h) == b"updated"
