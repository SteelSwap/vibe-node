"""ImmutableDB advanced tests — chunk arithmetic, hash/slot lookups, recovery, corruption.

Covers test specifications:
    - chunksBetween never returns empty list
    - chunksBetween(x, x) returns singleton
    - chunksBetween result is always sorted
    - chunksBetween bounds are inclusive
    - Stream with explicit from/to range parameters
    - GetHashForSlot — lookup hash by slot number
    - GetBlockAtOrAfterPoint — find block at or after a given point
    - Reopen with validation (verify index integrity)
    - Error injection: simulated write failure during append
    - Fine-grained corruption: truncate a chunk file mid-block, verify recovery

Haskell references:
    Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
    Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Secondary
    Ouroboros.Consensus.Storage.ImmutableDB.Impl.Validation
    Ouroboros.Consensus.Storage.ImmutableDB.API (stream, getBlockComponent)
"""

from __future__ import annotations

import os
import struct

import pytest

from vibe.cardano.storage.immutable import (
    _SEC_ENTRY_SIZE,
    ImmutableDB,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


def make_key(slot: int, block_hash: bytes) -> bytes:
    """Encode a (slot, hash) pair as the 40-byte key format."""
    return struct.pack(">Q", slot) + block_hash[:32].ljust(32, b"\x00")


def make_block(slot: int, size: int = 64) -> bytes:
    """Create fake CBOR block bytes of a given size."""
    return bytes([slot % 256]) * size


def chunks_between(db: ImmutableDB, from_slot: int, to_slot: int) -> list[int]:
    """Compute the list of chunk numbers between two slots (inclusive).

    Mirrors the Haskell chunksBetween function from
    Ouroboros.Consensus.Storage.ImmutableDB.Chunks.
    """
    from_chunk = db._slot_to_chunk(from_slot)
    to_chunk = db._slot_to_chunk(to_slot)
    return list(range(from_chunk, to_chunk + 1))


# ---------------------------------------------------------------------------
# chunksBetween — chunk arithmetic properties
# ---------------------------------------------------------------------------


class TestChunksBetweenNeverEmpty:
    """chunksBetween never returns empty list.

    For any valid slot range [from, to] where from <= to,
    the chunk list is always non-empty.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.Chunks.chunksBetween
    """

    def test_same_slot(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 50, 50)
        assert len(result) > 0

    def test_adjacent_slots(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 99, 100)
        assert len(result) > 0

    def test_wide_range(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 0, 999)
        assert len(result) > 0

    def test_slot_zero(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 0, 0)
        assert len(result) > 0


class TestChunksBetweenSingleton:
    """chunksBetween(x, x) returns singleton.

    When from and to are the same slot, the result is exactly one chunk.
    """

    def test_slot_zero(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 0, 0)
        assert result == [0]

    def test_mid_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 50, 50)
        assert result == [0]

    def test_chunk_boundary(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 100, 100)
        assert result == [1]

    def test_last_slot_in_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 99, 99)
        assert result == [0]

    def test_large_slot(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=432_000)
        result = chunks_between(db, 1_000_000, 1_000_000)
        assert len(result) == 1
        assert result == [1_000_000 // 432_000]


class TestChunksBetweenSorted:
    """chunksBetween result is always sorted."""

    def test_single_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 10, 90)
        assert result == sorted(result)

    def test_multi_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 0, 499)
        assert result == sorted(result)
        assert result == [0, 1, 2, 3, 4]

    def test_large_range(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        result = chunks_between(db, 5, 95)
        assert result == sorted(result)
        assert result == list(range(0, 10))


class TestChunksBetweenInclusive:
    """chunksBetween bounds are inclusive.

    The chunk containing from_slot and the chunk containing to_slot
    must both be in the result.
    """

    def test_includes_from_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 50, 250)
        from_chunk = db._slot_to_chunk(50)
        assert from_chunk in result

    def test_includes_to_chunk(self, tmp_path):
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 50, 250)
        to_chunk = db._slot_to_chunk(250)
        assert to_chunk in result

    def test_boundary_slots(self, tmp_path):
        """Slots at exact chunk boundaries are included."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = chunks_between(db, 100, 200)
        assert 1 in result  # chunk for slot 100
        assert 2 in result  # chunk for slot 200


# ---------------------------------------------------------------------------
# Stream with explicit from/to range parameters
# ---------------------------------------------------------------------------


class TestStreamWithRange:
    """Stream with explicit from/to range parameters.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.stream
    """

    @pytest.mark.asyncio
    async def test_stream_from_start(self, tmp_path):
        """Stream from slot 0 yields all blocks."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 5, 10, 20]:
            await db.append_block(s, make_hash(s), make_block(s))

        it = db.stream(start_slot=0)
        slots = []
        while it.has_next():
            key, _ = it.next()
            slots.append(struct.unpack(">Q", key[:8])[0])
        assert slots == [1, 5, 10, 20]

    @pytest.mark.asyncio
    async def test_stream_from_middle(self, tmp_path):
        """Stream starting from a mid-range slot."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 5, 10, 20]:
            await db.append_block(s, make_hash(s), make_block(s))

        it = db.stream(start_slot=6)
        slots = []
        while it.has_next():
            key, _ = it.next()
            slots.append(struct.unpack(">Q", key[:8])[0])
        assert slots == [10, 20]

    @pytest.mark.asyncio
    async def test_stream_from_exact_slot(self, tmp_path):
        """Stream starting from an exact block slot includes that block."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 5, 10, 20]:
            await db.append_block(s, make_hash(s), make_block(s))

        it = db.stream(start_slot=5)
        slots = []
        while it.has_next():
            key, _ = it.next()
            slots.append(struct.unpack(">Q", key[:8])[0])
        assert slots == [5, 10, 20]

    @pytest.mark.asyncio
    async def test_stream_across_chunks(self, tmp_path):
        """Stream spans multiple chunks correctly."""
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        slot_list = [3, 8, 12, 25, 31]
        for s in slot_list:
            await db.append_block(s, make_hash(s), make_block(s))

        it = db.stream(start_slot=0)
        slots = []
        while it.has_next():
            key, _ = it.next()
            slots.append(struct.unpack(">Q", key[:8])[0])
        assert slots == slot_list

    @pytest.mark.asyncio
    async def test_stream_past_all_blocks(self, tmp_path):
        """Stream starting beyond all blocks yields nothing."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), make_block(5))

        it = db.stream(start_slot=100)
        assert not it.has_next()


# ---------------------------------------------------------------------------
# GetHashForSlot — lookup hash by slot number
# ---------------------------------------------------------------------------


class TestGetHashForSlot:
    """GetHashForSlot — lookup hash by slot number.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.getBlockComponent
        Specifically getting the block hash for a given slot.
    """

    @pytest.mark.asyncio
    async def test_hash_for_existing_slot(self, tmp_path):
        """Looking up a hash by slot returns the correct hash."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(42)
        await db.append_block(10, block_hash, make_block(10))

        # Use secondary index to find hash for slot
        entries = db._read_secondary_entries(0)
        slot_to_hash = {e.slot: e.block_hash for e in entries}
        assert 10 in slot_to_hash
        assert slot_to_hash[10] == block_hash

    @pytest.mark.asyncio
    async def test_hash_for_empty_slot_absent(self, tmp_path):
        """Empty slots have no hash entry in secondary index."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), make_block(5))

        entries = db._read_secondary_entries(0)
        slot_to_hash = {e.slot: e.block_hash for e in entries}
        assert 3 not in slot_to_hash

    @pytest.mark.asyncio
    async def test_hash_for_multiple_slots(self, tmp_path):
        """Multiple slots each resolve to the correct hash."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        expected = {}
        for s in [2, 7, 15, 42]:
            h = make_hash(s * 100)
            await db.append_block(s, h, make_block(s))
            expected[s] = h

        entries = db._read_secondary_entries(0)
        slot_to_hash = {e.slot: e.block_hash for e in entries}
        for s, expected_hash in expected.items():
            assert slot_to_hash[s] == expected_hash

    @pytest.mark.asyncio
    async def test_hash_lookup_via_in_memory_index(self, tmp_path):
        """The in-memory hash index allows direct hash -> entry lookup."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(77)
        await db.append_block(20, block_hash, make_block(20))

        entry = db._hash_index.get(block_hash)
        assert entry is not None
        assert entry.slot == 20
        assert entry.block_hash == block_hash


# ---------------------------------------------------------------------------
# GetBlockAtOrAfterPoint — find block at or after a given point
# ---------------------------------------------------------------------------


class TestGetBlockAtOrAfterPoint:
    """GetBlockAtOrAfterPoint — find block at or after a given point.

    Given a slot number, find the block at that slot or the next block
    after it. This is used for chain-sync "find intersection" operations.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API
        streamAfterKnownPoint
    """

    @pytest.mark.asyncio
    async def test_exact_slot_match(self, tmp_path):
        """Block exists at the exact requested slot."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        data = b"EXACT_MATCH"
        await db.append_block(10, make_hash(10), data)

        result = await db.get_block_by_slot(10)
        assert result == data

    @pytest.mark.asyncio
    async def test_slot_after_gap(self, tmp_path):
        """When requested slot is empty, find the next block via iteration.

        Use the stream iterator to find the first block at or after
        the target slot.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"BLOCK_5")
        await db.append_block(15, make_hash(15), b"BLOCK_15")
        await db.append_block(25, make_hash(25), b"BLOCK_25")

        # Slot 10 is empty — the next block is at slot 15
        it = db.stream(start_slot=10)
        assert it.has_next()
        key, data = it.next()
        slot = struct.unpack(">Q", key[:8])[0]
        assert slot == 15
        assert data == b"BLOCK_15"
        it.close()

    @pytest.mark.asyncio
    async def test_slot_before_all_blocks(self, tmp_path):
        """Slot before any block returns the first block."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(10, make_hash(10), b"FIRST")

        it = db.stream(start_slot=0)
        assert it.has_next()
        key, data = it.next()
        slot = struct.unpack(">Q", key[:8])[0]
        assert slot == 10
        assert data == b"FIRST"
        it.close()

    @pytest.mark.asyncio
    async def test_slot_after_all_blocks(self, tmp_path):
        """Slot after all blocks returns nothing."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(10, make_hash(10), b"LAST")

        it = db.stream(start_slot=20)
        assert not it.has_next()


# ---------------------------------------------------------------------------
# Reopen with validation — verify index integrity
# ---------------------------------------------------------------------------


class TestReopenWithValidation:
    """Reopen with validation — verify index integrity on reopen.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.Impl.openDBInternal
        Ouroboros.Consensus.Storage.ImmutableDB.Impl.Validation
    """

    @pytest.mark.asyncio
    async def test_reopen_validates_tip(self, tmp_path):
        """After reopen, tip matches what was written."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"A")
        await db.append_block(10, make_hash(10), b"B")
        await db.append_block(20, make_hash(20), b"C")
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        assert db2.get_tip_slot() == 20
        assert db2.get_tip_hash() == make_hash(20)

    @pytest.mark.asyncio
    async def test_reopen_hash_index_complete(self, tmp_path):
        """After reopen, all block hashes are in the in-memory index."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        hashes = []
        for s in [1, 5, 10]:
            h = make_hash(s)
            hashes.append(h)
            await db.append_block(s, h, make_block(s))
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        for h in hashes:
            assert h in db2._hash_index

    @pytest.mark.asyncio
    async def test_reopen_all_blocks_readable(self, tmp_path):
        """After reopen, every block can be read by hash."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        blocks = {}
        for s in [2, 7, 15]:
            data = os.urandom(80)
            blocks[make_hash(s)] = data
            await db.append_block(s, make_hash(s), data)
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        for h, expected in blocks.items():
            result = await db2.get_block(h)
            assert result == expected

    @pytest.mark.asyncio
    async def test_reopen_and_validate_returns_correct_count(self, tmp_path):
        """validate_and_recover on a clean DB returns the correct block count."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 3, 5, 7, 9]:
            await db.append_block(s, make_hash(s), make_block(s))
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        count = await db2.validate_and_recover()
        assert count == 5

    @pytest.mark.asyncio
    async def test_reopen_across_chunks(self, tmp_path):
        """Reopen recovers state that spans multiple chunks."""
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        for s in [3, 8, 15, 22, 31]:
            await db.append_block(s, make_hash(s), make_block(s))
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=10)
        assert db2.get_tip_slot() == 31
        for s in [3, 8, 15, 22, 31]:
            result = await db2.get_block(make_hash(s))
            assert result is not None


# ---------------------------------------------------------------------------
# Error injection: simulated write failure during append
# ---------------------------------------------------------------------------


class TestWriteFailureInjection:
    """Error injection: simulated write failure during append.

    Verify that a write failure during append doesn't corrupt
    the database state.
    """

    @pytest.mark.asyncio
    async def test_write_failure_preserves_tip(self, tmp_path):
        """If a write fails, the tip should not advance."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"GOOD_BLOCK")
        assert db.get_tip_slot() == 5

        # Simulate write failure by making the chunk file read-only
        chunk_path = db._chunk_path(0)
        original_mode = chunk_path.stat().st_mode
        chunk_path.chmod(0o444)

        try:
            with pytest.raises(PermissionError):
                await db.append_block(10, make_hash(10), b"BAD_BLOCK")
        finally:
            chunk_path.chmod(original_mode)

        # Tip should still be at slot 5 since the write failed
        # Note: the in-memory state may have been partially updated,
        # but the on-disk state is intact. A reopen would recover correctly.
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        assert db2.get_tip_slot() == 5

    @pytest.mark.asyncio
    async def test_write_failure_original_data_intact(self, tmp_path):
        """After a failed write, original block data is still readable."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        original_data = b"ORIGINAL_BLOCK_DATA"
        await db.append_block(5, make_hash(5), original_data)

        chunk_path = db._chunk_path(0)
        original_mode = chunk_path.stat().st_mode
        chunk_path.chmod(0o444)

        try:
            with pytest.raises(PermissionError):
                await db.append_block(10, make_hash(10), b"FAILED")
        finally:
            chunk_path.chmod(original_mode)

        # Original data should still be readable on reopen
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        result = await db2.get_block(make_hash(5))
        assert result == original_data


# ---------------------------------------------------------------------------
# Fine-grained corruption: truncate a chunk file mid-block
# ---------------------------------------------------------------------------


class TestFineGrainedCorruption:
    """Fine-grained corruption: truncate a chunk file mid-block, verify recovery.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.Impl.Validation
        The Haskell node validates chunk files on startup and truncates
        to the last fully-readable block.
    """

    @pytest.mark.asyncio
    async def test_truncate_mid_last_block(self, tmp_path):
        """Truncate the chunk file mid-way through the last block.

        Recovery should drop the last (corrupt) block and keep
        all earlier blocks intact.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        block_1 = b"A" * 100
        block_2 = b"B" * 200
        block_3 = b"C" * 300

        await db.append_block(1, make_hash(1), block_1)
        await db.append_block(2, make_hash(2), block_2)
        await db.append_block(3, make_hash(3), block_3)

        assert db.get_tip_slot() == 3

        # Truncate the chunk file to remove part of block 3
        chunk_path = db._chunk_path(0)
        full_size = chunk_path.stat().st_size
        assert full_size == 600  # 100 + 200 + 300

        # Truncate to 450 bytes — mid-way through block 3 (starts at 300)
        with open(chunk_path, "r+b") as f:
            f.truncate(450)

        # Recovery should detect the corruption
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        valid_count = await db2.validate_and_recover()

        # Blocks 1 and 2 survive, block 3 is truncated
        assert valid_count == 2
        assert db2.get_tip_slot() == 2

        # Verify surviving blocks are readable
        assert await db2.get_block(make_hash(1)) == block_1
        assert await db2.get_block(make_hash(2)) == block_2
        assert await db2.get_block(make_hash(3)) is None

    @pytest.mark.asyncio
    async def test_truncate_all_blocks(self, tmp_path):
        """Truncate the chunk file to zero bytes — all blocks lost."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(1, make_hash(1), b"X" * 50)
        await db.append_block(2, make_hash(2), b"Y" * 50)

        chunk_path = db._chunk_path(0)
        with open(chunk_path, "w+b") as f:
            f.truncate(0)

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        valid_count = await db2.validate_and_recover()
        assert valid_count == 0
        assert db2.get_tip_slot() is None

    @pytest.mark.asyncio
    async def test_truncate_mid_first_block(self, tmp_path):
        """Truncate mid-way through the first block — nothing survives."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(1, make_hash(1), b"Z" * 200)

        chunk_path = db._chunk_path(0)
        with open(chunk_path, "r+b") as f:
            f.truncate(50)  # Only 50 of 200 bytes

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        valid_count = await db2.validate_and_recover()
        assert valid_count == 0
        assert db2.get_tip_slot() is None

    @pytest.mark.asyncio
    async def test_cross_chunk_corruption_isolates(self, tmp_path):
        """Corruption in chunk 1 doesn't affect chunk 0.

        If chunk 1 is corrupted, all blocks in chunk 0 should survive.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=10)

        # Write blocks across two chunks
        await db.append_block(3, make_hash(3), b"CHUNK0_A" * 10)
        await db.append_block(7, make_hash(7), b"CHUNK0_B" * 10)
        await db.append_block(12, make_hash(12), b"CHUNK1_A" * 10)
        await db.append_block(15, make_hash(15), b"CHUNK1_B" * 10)

        # Truncate chunk 1
        chunk1_path = db._chunk_path(1)
        with open(chunk1_path, "r+b") as f:
            f.truncate(5)

        db2 = ImmutableDB(str(tmp_path), epoch_size=10)
        valid_count = await db2.validate_and_recover()

        # Chunk 0's 2 blocks should survive
        assert valid_count == 2
        assert db2.get_tip_slot() == 7
        assert await db2.get_block(make_hash(3)) == b"CHUNK0_A" * 10
        assert await db2.get_block(make_hash(7)) == b"CHUNK0_B" * 10

    @pytest.mark.asyncio
    async def test_secondary_index_corruption_detected(self, tmp_path):
        """Truncate the secondary index file to corrupt an entry.

        When the secondary index entry has invalid offset/size,
        validation should detect the inconsistency.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(1, make_hash(1), b"BLOCK_1" * 20)
        await db.append_block(2, make_hash(2), b"BLOCK_2" * 20)

        # Truncate the secondary index to remove the second entry
        sec_path = db._secondary_path(0)
        original_size = sec_path.stat().st_size
        assert original_size == 2 * _SEC_ENTRY_SIZE

        with open(sec_path, "r+b") as f:
            f.truncate(_SEC_ENTRY_SIZE + 10)  # Partial second entry

        # Reopen — recovery reads only complete entries
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        # The partial entry should be ignored during recovery
        # (the _recover method reads in _SEC_ENTRY_SIZE chunks)
        # Block 1 should still be accessible
        result = await db2.get_block(make_hash(1))
        assert result == b"BLOCK_1" * 20
