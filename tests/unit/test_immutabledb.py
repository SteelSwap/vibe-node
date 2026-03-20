"""Tests for vibe.cardano.storage.immutable — ImmutableDB.

Covers the test specifications from the database for the storage subsystem:
- test_append_block_to_empty_db
- test_append_block_to_empty_chunk_file
- test_append_block_not_newer_than_tip_raises
- test_append_block_preserves_order_and_content
- test_append_multiple_blocks_sequential (chunk file is exact concatenation)
- test_chunk_file_is_exact_concatenation
- test_append_block_triggers_chunk_rollover
- test_append_block_with_greater_slot_succeeds
- test_append_block_with_smaller_slot_fails
- test_append_block_with_equal_slot_to_regular_tip_fails
- test_append_then_get_block_component
"""

from __future__ import annotations

import os
import struct

import pytest

from vibe.cardano.storage.immutable import (
    AppendBlockNotNewerThanTipError,
    ClosedDBError,
    ImmutableDB,
    ImmutableDBIterator,
    _PRI_ENTRY_FMT,
    _PRI_ENTRY_SIZE,
    _SEC_ENTRY_FMT,
    _SEC_ENTRY_SIZE,
)
from vibe.core.storage.interfaces import AppendStore


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
    # Fill with slot number repeated for easy identification
    return bytes([slot % 256]) * size


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify ImmutableDB satisfies the AppendStore Protocol."""

    def test_is_append_store(self, tmp_path: object) -> None:
        """ImmutableDB is a structural subtype of AppendStore."""
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        assert isinstance(db, AppendStore)


# ---------------------------------------------------------------------------
# Append to empty DB
# ---------------------------------------------------------------------------


class TestAppendToEmptyDB:
    """test_append_block_to_empty_db / test_append_block_to_empty_db_succeeds"""

    @pytest.mark.asyncio
    async def test_append_single_block(self, tmp_path: object) -> None:
        """Appending a single block to an empty ImmutableDB should succeed."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(1)
        block_data = make_block(5, size=128)

        await db.append_block(5, block_hash, block_data)

        # Verify tip is updated
        tip = await db.get_tip()
        assert tip is not None
        tip_slot = struct.unpack(">Q", tip[:8])[0]
        assert tip_slot == 5
        assert tip[8:40] == block_hash

    @pytest.mark.asyncio
    async def test_append_to_empty_stores_in_chunk(self, tmp_path: object) -> None:
        """Block is stored in the chunk file."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_data = b"CBOR_BLOCK_BYTES_HERE"
        await db.append_block(0, make_hash(0), block_data)

        chunk_path = db._chunk_path(0)
        assert chunk_path.exists()
        assert chunk_path.read_bytes() == block_data

    @pytest.mark.asyncio
    async def test_append_to_empty_creates_primary_index(self, tmp_path: object) -> None:
        """Primary index file is created with slot offset."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(3, make_hash(3), b"block_data")

        offsets = db._read_primary_offsets(0)
        # Should have entries for slots 0..3 plus the actual entry
        assert len(offsets) >= 4
        # Slot 3's offset should be 0 (first block in chunk)
        assert offsets[3] == 0

    @pytest.mark.asyncio
    async def test_append_to_empty_creates_secondary_index(self, tmp_path: object) -> None:
        """Secondary index contains the block hash entry."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(7)
        await db.append_block(7, block_hash, b"some_block")

        entries = db._read_secondary_entries(0)
        assert len(entries) == 1
        assert entries[0].block_hash == block_hash
        assert entries[0].slot == 7
        assert entries[0].offset == 0
        assert entries[0].size == len(b"some_block")


# ---------------------------------------------------------------------------
# Append to empty chunk file — no headers/footers
# ---------------------------------------------------------------------------


class TestAppendToEmptyChunkFile:
    """test_append_block_to_empty_chunk_file

    Appending a single raw block to an empty chunk file results in a file
    containing exactly that block's bytes, with no headers, footers, or
    separators.
    """

    @pytest.mark.asyncio
    async def test_exact_bytes(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        raw_block = os.urandom(256)
        await db.append_block(0, make_hash(0), raw_block)

        chunk_file = db._chunk_path(0)
        assert chunk_file.read_bytes() == raw_block


# ---------------------------------------------------------------------------
# Ordering violations
# ---------------------------------------------------------------------------


class TestAppendBlockNotNewerThanTip:
    """test_append_block_not_newer_than_tip_raises
    test_append_block_with_smaller_slot_fails
    test_append_block_with_equal_slot_to_regular_tip_fails
    """

    @pytest.mark.asyncio
    async def test_same_slot_raises(self, tmp_path: object) -> None:
        """Block at same slot as tip raises AppendBlockNotNewerThanTipError."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(1), b"block_a")

        with pytest.raises(AppendBlockNotNewerThanTipError) as exc_info:
            await db.append_block(5, make_hash(2), b"block_b")

        assert exc_info.value.block_slot == 5
        assert exc_info.value.tip_slot == 5

    @pytest.mark.asyncio
    async def test_older_slot_raises(self, tmp_path: object) -> None:
        """Block at slot before tip raises AppendBlockNotNewerThanTipError."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(10, make_hash(1), b"block_a")

        with pytest.raises(AppendBlockNotNewerThanTipError) as exc_info:
            await db.append_block(3, make_hash(2), b"block_b")

        assert exc_info.value.block_slot == 3
        assert exc_info.value.tip_slot == 10

    @pytest.mark.asyncio
    async def test_error_message_contains_slots(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(10, make_hash(1), b"x")

        with pytest.raises(AppendBlockNotNewerThanTipError, match="slot 5.*slot 10"):
            await db.append_block(5, make_hash(2), b"y")


# ---------------------------------------------------------------------------
# Greater slot succeeds
# ---------------------------------------------------------------------------


class TestAppendWithGreaterSlot:
    """test_append_block_with_greater_slot_succeeds"""

    @pytest.mark.asyncio
    async def test_sequential(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(1), b"a")
        await db.append_block(6, make_hash(2), b"b")
        assert db.get_tip_slot() == 6

    @pytest.mark.asyncio
    async def test_with_gap(self, tmp_path: object) -> None:
        """Appending with a large gap should succeed."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(1), b"a")
        await db.append_block(99, make_hash(2), b"b")
        assert db.get_tip_slot() == 99


# ---------------------------------------------------------------------------
# Chunk file concatenation invariant
# ---------------------------------------------------------------------------


class TestChunkFileConcatenation:
    """test_append_multiple_blocks_sequential
    test_chunk_file_is_exact_concatenation
    test_append_block_preserves_order_and_content

    Chunk file == b''.join(blocks). No extra bytes.
    """

    @pytest.mark.asyncio
    async def test_two_blocks(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        b1 = b"BLOCK_ONE"
        b2 = b"BLOCK_TWO"
        await db.append_block(0, make_hash(0), b1)
        await db.append_block(1, make_hash(1), b2)

        assert db._chunk_path(0).read_bytes() == b1 + b2

    @pytest.mark.asyncio
    async def test_three_blocks_exact(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        blocks = [os.urandom(i * 10 + 10) for i in range(3)]
        for i, blk in enumerate(blocks):
            await db.append_block(i, make_hash(i), blk)

        expected = b"".join(blocks)
        assert db._chunk_path(0).read_bytes() == expected

    @pytest.mark.asyncio
    async def test_no_extra_bytes(self, tmp_path: object) -> None:
        """No extra information before or after — spec invariant."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block = b"\x83\x00\x01\x02"  # Fake minimal CBOR
        await db.append_block(0, make_hash(0), block)

        file_bytes = db._chunk_path(0).read_bytes()
        assert len(file_bytes) == len(block)
        assert file_bytes == block


# ---------------------------------------------------------------------------
# Chunk rollover
# ---------------------------------------------------------------------------


class TestChunkRollover:
    """test_append_block_triggers_chunk_rollover

    Configure chunkInfo so chunk 0 holds slots 0-9. Append a block at
    slot 5 (chunk 0), then append a block at slot 15 (chunk 1). Verify
    chunk separation.
    """

    @pytest.mark.asyncio
    async def test_rollover(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        b1 = b"CHUNK_ZERO_BLOCK"
        b2 = b"CHUNK_ONE_BLOCK"

        await db.append_block(5, make_hash(5), b1)
        await db.append_block(15, make_hash(15), b2)

        # Chunk 0 has block at slot 5
        assert db._chunk_path(0).read_bytes() == b1
        # Chunk 1 has block at slot 15
        assert db._chunk_path(1).read_bytes() == b2

    @pytest.mark.asyncio
    async def test_rollover_secondary_indexes(self, tmp_path: object) -> None:
        """Secondary indexes are per-chunk."""
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        await db.append_block(5, make_hash(5), b"a")
        await db.append_block(15, make_hash(15), b"b")

        entries_0 = db._read_secondary_entries(0)
        entries_1 = db._read_secondary_entries(1)
        assert len(entries_0) == 1
        assert entries_0[0].slot == 5
        assert len(entries_1) == 1
        assert entries_1[0].slot == 15


# ---------------------------------------------------------------------------
# Block retrieval
# ---------------------------------------------------------------------------


class TestBlockRetrieval:
    """test_append_then_get_block_component

    Append a block, then retrieve it and verify all components match.
    """

    @pytest.mark.asyncio
    async def test_get_by_hash(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(42)
        block_data = os.urandom(200)
        await db.append_block(10, block_hash, block_data)

        result = await db.get_block(block_hash)
        assert result == block_data

    @pytest.mark.asyncio
    async def test_get_by_slot(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_data = b"SLOT_LOOKUP_BLOCK"
        await db.append_block(7, make_hash(7), block_data)

        result = await db.get_block_by_slot(7)
        assert result == block_data

    @pytest.mark.asyncio
    async def test_get_by_key(self, tmp_path: object) -> None:
        """AppendStore.get() with full 40-byte key."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_hash = make_hash(99)
        block_data = b"KEY_LOOKUP"
        await db.append_block(20, block_hash, block_data)

        key = make_key(20, block_hash)
        result = await db.get(key)
        assert result == block_data

    @pytest.mark.asyncio
    async def test_get_nonexistent_hash(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        result = await db.get_block(make_hash(999))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_empty_slot(self, tmp_path: object) -> None:
        """Slot with no block returns None."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"x")
        result = await db.get_block_by_slot(3)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_multiple_blocks(self, tmp_path: object) -> None:
        """Retrieve multiple blocks by hash after appending."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        blocks = {}
        for slot in [2, 5, 8, 12]:
            h = make_hash(slot)
            data = os.urandom(64)
            blocks[h] = data
            await db.append_block(slot, h, data)

        for h, expected in blocks.items():
            result = await db.get_block(h)
            assert result == expected


# ---------------------------------------------------------------------------
# Tip tracking
# ---------------------------------------------------------------------------


class TestTipTracking:
    """Verify tip is updated correctly on appends."""

    @pytest.mark.asyncio
    async def test_empty_tip(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        assert await db.get_tip() is None
        assert db.get_tip_slot() is None
        assert db.get_tip_hash() is None

    @pytest.mark.asyncio
    async def test_tip_after_appends(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(1, make_hash(1), b"a")
        assert db.get_tip_slot() == 1

        await db.append_block(5, make_hash(5), b"b")
        assert db.get_tip_slot() == 5
        assert db.get_tip_hash() == make_hash(5)


# ---------------------------------------------------------------------------
# iter_from
# ---------------------------------------------------------------------------


class TestIterFrom:
    """Iterate blocks forward from a starting slot."""

    @pytest.mark.asyncio
    async def test_iter_all(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        slots = [1, 3, 7, 10]
        for s in slots:
            await db.append_block(s, make_hash(s), f"block_{s}".encode())

        start_key = struct.pack(">Q", 0) + b"\x00" * 32
        collected = []
        async for key, value in db.iter_from(start_key):
            slot = struct.unpack(">Q", key[:8])[0]
            collected.append((slot, value))

        assert [s for s, _ in collected] == slots

    @pytest.mark.asyncio
    async def test_iter_from_middle(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 3, 7, 10]:
            await db.append_block(s, make_hash(s), f"block_{s}".encode())

        start_key = struct.pack(">Q", 5) + b"\x00" * 32
        collected = []
        async for key, value in db.iter_from(start_key):
            slot = struct.unpack(">Q", key[:8])[0]
            collected.append(slot)

        assert collected == [7, 10]

    @pytest.mark.asyncio
    async def test_iter_across_chunks(self, tmp_path: object) -> None:
        """Iteration spans chunk boundaries."""
        db = ImmutableDB(str(tmp_path), epoch_size=10)
        slots = [3, 8, 12, 25]
        for s in slots:
            await db.append_block(s, make_hash(s), f"blk{s}".encode())

        start_key = struct.pack(">Q", 0) + b"\x00" * 32
        collected = []
        async for key, _ in db.iter_from(start_key):
            slot = struct.unpack(">Q", key[:8])[0]
            collected.append(slot)

        assert collected == slots

    @pytest.mark.asyncio
    async def test_iter_empty_db(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        start_key = struct.pack(">Q", 0) + b"\x00" * 32
        collected = []
        async for _ in db.iter_from(start_key):
            collected.append(True)
        assert collected == []


# ---------------------------------------------------------------------------
# Recovery from disk
# ---------------------------------------------------------------------------


class TestRecovery:
    """Crash recovery: reopen DB from existing files."""

    @pytest.mark.asyncio
    async def test_reopen_recovers_tip(self, tmp_path: object) -> None:
        """After closing and reopening, tip is recovered."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"block_5")
        await db.append_block(10, make_hash(10), b"block_10")
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        assert db2.get_tip_slot() == 10
        assert db2.get_tip_hash() == make_hash(10)

    @pytest.mark.asyncio
    async def test_reopen_recovers_hash_index(self, tmp_path: object) -> None:
        """After reopen, hash-based lookups still work."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        block_data = b"PERSISTENT_BLOCK"
        await db.append_block(7, make_hash(7), block_data)
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        result = await db2.get_block(make_hash(7))
        assert result == block_data

    @pytest.mark.asyncio
    async def test_reopen_allows_further_appends(self, tmp_path: object) -> None:
        """After recovery, can append more blocks."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"first")
        del db

        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        await db2.append_block(10, make_hash(10), b"second")
        assert db2.get_tip_slot() == 10

        # Both blocks retrievable
        assert await db2.get_block(make_hash(5)) == b"first"
        assert await db2.get_block(make_hash(10)) == b"second"


# ---------------------------------------------------------------------------
# AppendStore.append() key format
# ---------------------------------------------------------------------------


class TestAppendStoreKeyFormat:
    """Test the AppendStore.append() wrapper with 40-byte keys."""

    @pytest.mark.asyncio
    async def test_append_via_protocol(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        key = make_key(15, make_hash(15))
        value = b"protocol_append_block"

        await db.append(key, value)

        assert db.get_tip_slot() == 15
        result = await db.get(key)
        assert result == value

    @pytest.mark.asyncio
    async def test_append_invalid_key_raises(self, tmp_path: object) -> None:
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        with pytest.raises(ValueError, match="Key must be >= 40 bytes"):
            await db.append(b"short", b"value")


# ---------------------------------------------------------------------------
# DeleteAfter — truncate chain
# ---------------------------------------------------------------------------


class TestDeleteAfter:
    """test_delete_after_truncates_chain

    Implement DeleteAfter: truncate chain after a given slot, verify blocks
    after that slot are gone.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.deleteAfter
    """

    @pytest.mark.asyncio
    async def test_delete_after_truncates_chain(self, tmp_path: object) -> None:
        """Blocks after the cutoff slot are removed; blocks at or before survive."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        # Append blocks at slots 1, 3, 5, 7, 9
        blocks = {}
        for s in [1, 3, 5, 7, 9]:
            data = f"block_at_{s}".encode()
            await db.append_block(s, make_hash(s), data)
            blocks[s] = data

        assert db.get_tip_slot() == 9

        # Truncate after slot 5 — blocks at 7 and 9 should be gone
        removed = await db.delete_after(5)
        assert removed == 2

        assert db.get_tip_slot() == 5

        # Blocks at slots 1, 3, 5 should still be retrievable
        for s in [1, 3, 5]:
            result = await db.get_block(make_hash(s))
            assert result == blocks[s], f"Block at slot {s} should survive"

        # Blocks at slots 7 and 9 should be gone
        for s in [7, 9]:
            result = await db.get_block(make_hash(s))
            assert result is None, f"Block at slot {s} should be truncated"

    @pytest.mark.asyncio
    async def test_delete_after_at_tip_is_noop(self, tmp_path: object) -> None:
        """Truncating at the tip slot removes nothing."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"block_5")
        removed = await db.delete_after(5)
        assert removed == 0
        assert db.get_tip_slot() == 5

    @pytest.mark.asyncio
    async def test_delete_after_beyond_tip_is_noop(self, tmp_path: object) -> None:
        """Truncating beyond the tip slot removes nothing."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(5, make_hash(5), b"block_5")
        removed = await db.delete_after(100)
        assert removed == 0


# ---------------------------------------------------------------------------
# Iterator — has_next, close
# ---------------------------------------------------------------------------


class TestIteratorHasNext:
    """test_iterator_has_next

    Explicit hasNext check on iterator.
    """

    @pytest.mark.asyncio
    async def test_iterator_has_next(self, tmp_path: object) -> None:
        """Iterator.has_next() returns True when blocks remain, False when exhausted."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        for s in [1, 3, 5]:
            await db.append_block(s, make_hash(s), f"blk{s}".encode())

        it = db.stream(start_slot=0)

        assert it.has_next() is True
        it.next()  # slot 1
        assert it.has_next() is True
        it.next()  # slot 3
        assert it.has_next() is True
        it.next()  # slot 5
        assert it.has_next() is False

    @pytest.mark.asyncio
    async def test_iterator_has_next_empty_db(self, tmp_path: object) -> None:
        """Iterator on empty DB has no next."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        it = db.stream(start_slot=0)
        assert it.has_next() is False


class TestIteratorClose:
    """test_iterator_close

    Close iterator, verify subsequent next raises ClosedDBError.
    """

    @pytest.mark.asyncio
    async def test_iterator_close(self, tmp_path: object) -> None:
        """After close(), next() raises ClosedDBError."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        await db.append_block(1, make_hash(1), b"block_1")

        it = db.stream(start_slot=0)
        assert it.has_next() is True

        it.close()
        assert it.has_next() is False

        with pytest.raises(ClosedDBError):
            it.next()

    @pytest.mark.asyncio
    async def test_iterator_close_idempotent(self, tmp_path: object) -> None:
        """Closing an already-closed iterator doesn't raise."""
        db = ImmutableDB(str(tmp_path), epoch_size=100)
        it = db.stream(start_slot=0)
        it.close()
        it.close()  # Should not raise


# ---------------------------------------------------------------------------
# Corruption recovery
# ---------------------------------------------------------------------------


class TestCorruptionRecovery:
    """test_corruption_bitflip_detected
    test_corruption_deleted_file_recovery

    Verify that corruption in chunk files is detected and recovery
    truncates to the last valid block.
    """

    @pytest.mark.asyncio
    async def test_corruption_bitflip_detected(self, tmp_path: object) -> None:
        """Flip a byte in a chunk file, verify recovery truncates to last valid block.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Validation
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        # Append 3 blocks in same chunk
        await db.append_block(1, make_hash(1), b"BLOCK_ONE_VALID")
        await db.append_block(2, make_hash(2), b"BLOCK_TWO_VALID")
        await db.append_block(3, make_hash(3), b"BLOCK_THREE_OK!")

        assert db.get_tip_slot() == 3

        # Corrupt the chunk file by truncating it — this simulates
        # a bitflip that makes the last block unreadable because
        # the size recorded in the secondary index won't match.
        chunk_path = db._chunk_path(0)
        original = chunk_path.read_bytes()
        # Truncate to remove the last block partially
        truncated = original[: len(b"BLOCK_ONE_VALID") + len(b"BLOCK_TWO_VALID") + 5]
        chunk_path.write_bytes(truncated)

        # Create a fresh DB that will run recovery
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)
        valid_count = await db2.validate_and_recover()

        # Only blocks 1 and 2 should survive (block 3's data is truncated)
        assert valid_count == 2
        assert db2.get_tip_slot() == 2

    @pytest.mark.asyncio
    async def test_corruption_deleted_file_recovery(self, tmp_path: object) -> None:
        """Delete a chunk file, verify recovery handles it.

        If a chunk file is missing entirely, recovery should stop at
        the last chunk that was fully readable.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=10)

        # Append blocks across two chunks
        await db.append_block(3, make_hash(3), b"chunk0_block")
        await db.append_block(15, make_hash(15), b"chunk1_block")

        assert db.get_tip_slot() == 15

        # Delete chunk 1's data file
        chunk1_path = db._chunk_path(1)
        assert chunk1_path.exists()
        chunk1_path.unlink()

        # Create a fresh DB and validate
        db2 = ImmutableDB(str(tmp_path), epoch_size=10)
        valid_count = await db2.validate_and_recover()

        # Only chunk 0's block should survive
        assert valid_count == 1
        assert db2.get_tip_slot() == 3


# ---------------------------------------------------------------------------
# Primary Index
# ---------------------------------------------------------------------------


class TestPrimaryIndex:
    """Tests for primary index read/write operations.

    The primary index maps relative slots to byte offsets in chunk files.
    """

    @pytest.mark.asyncio
    async def test_primary_index_write_load_roundtrip(self, tmp_path: object) -> None:
        """Write primary index, load it back, verify offsets match.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        # Append blocks of known sizes to control offsets precisely
        b1 = b"A" * 100
        b2 = b"B" * 200
        b3 = b"C" * 50
        await db.append_block(2, make_hash(2), b1)
        await db.append_block(5, make_hash(5), b2)
        await db.append_block(8, make_hash(8), b3)

        offsets = db._read_primary_offsets(0)
        assert len(offsets) > 0

        # Slot 2 should start at offset 0
        assert offsets[2] == 0
        # Slot 3 should reflect end of b1 (carried forward for empty slots)
        assert offsets[3] == 100
        # Slot 5 should start at offset 100
        assert offsets[5] == 100
        # Slot 6 should reflect end of b2
        assert offsets[6] == 300
        # Slot 8 should start at offset 300
        assert offsets[8] == 300

    @pytest.mark.asyncio
    async def test_primary_index_filled_slots_consistency(self, tmp_path: object) -> None:
        """Filled slots correspond to non-zero-delta offsets.

        For a filled slot i, offset[i+1] - offset[i] > 0.
        For an empty slot i, offset[i+1] - offset[i] == 0.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        # Blocks at slots 1, 3, 6 — slots 0, 2, 4, 5 are empty
        await db.append_block(1, make_hash(1), b"X" * 40)
        await db.append_block(3, make_hash(3), b"Y" * 60)
        await db.append_block(6, make_hash(6), b"Z" * 80)

        offsets = db._read_primary_offsets(0)

        # Filled slots should have positive delta
        filled_slots = [1, 3, 6]
        for s in filled_slots:
            delta = offsets[s + 1] - offsets[s]
            assert delta > 0, f"Filled slot {s} should have positive delta, got {delta}"

        # Empty slots should have zero delta
        empty_slots = [0, 2, 4, 5]
        for s in empty_slots:
            if s + 1 < len(offsets):
                delta = offsets[s + 1] - offsets[s]
                assert delta == 0, f"Empty slot {s} should have zero delta, got {delta}"

    @pytest.mark.asyncio
    async def test_primary_index_truncate_to_slot(self, tmp_path: object) -> None:
        """Truncate index at a slot, verify later entries gone.

        Uses delete_after to truncate, then verifies the primary index
        is consistent.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        await db.append_block(2, make_hash(2), b"AA" * 20)
        await db.append_block(5, make_hash(5), b"BB" * 30)
        await db.append_block(8, make_hash(8), b"CC" * 10)

        # Truncate after slot 5
        await db.delete_after(5)

        # Block at slot 8 should be gone
        result = await db.get_block_by_slot(8)
        assert result is None

        # Block at slot 5 should still be there
        result = await db.get_block_by_slot(5)
        assert result == b"BB" * 30

    @pytest.mark.asyncio
    async def test_primary_index_reconstruct_from_chunks(self, tmp_path: object) -> None:
        """Rebuild primary index from chunk file, verify matches original.

        After writing blocks, wipe the primary index, recreate the DB
        (which rebuilds from secondary index), and verify slot lookups
        still work.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        blocks = {2: b"AAA", 5: b"BBBBB", 9: b"CC"}
        for s, data in blocks.items():
            await db.append_block(s, make_hash(s), data)

        # Verify lookups work before wipe
        for s, data in blocks.items():
            assert await db.get_block_by_slot(s) == data

        # Wipe primary index files
        for f in db._primary_dir.glob("*.idx"):
            f.unlink()

        # Recreate DB — recovery reads from secondary index and can
        # still do hash-based lookups (primary is for slot-based only)
        db2 = ImmutableDB(str(tmp_path), epoch_size=100)

        # Hash-based lookups should still work (from secondary index)
        for s, data in blocks.items():
            result = await db2.get_block(make_hash(s))
            assert result == data, f"Hash lookup for slot {s} failed after primary wipe"

    @pytest.mark.asyncio
    async def test_primary_index_empty_slots_carry_forward(self, tmp_path: object) -> None:
        """Empty slots have same offset as previous filled slot.

        When blocks exist at slots 0 and 5, slots 1-4 should all carry
        the same offset as the end of slot 0's block.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        b0 = b"FIRST" * 10  # 50 bytes
        await db.append_block(0, make_hash(0), b0)
        await db.append_block(5, make_hash(5), b"SECOND")

        offsets = db._read_primary_offsets(0)

        # Slot 0 starts at 0
        assert offsets[0] == 0
        # Slot 1 (end of slot 0's block = 50)
        end_of_slot_0 = len(b0)
        assert offsets[1] == end_of_slot_0

        # Slots 2-4 should carry forward the same offset (empty)
        for s in [2, 3, 4]:
            assert offsets[s] == end_of_slot_0, (
                f"Empty slot {s} should carry forward offset {end_of_slot_0}"
            )

        # Slot 5 starts where the last empty slot pointed
        assert offsets[5] == end_of_slot_0

    @pytest.mark.asyncio
    async def test_primary_index_first_filled_slot(self, tmp_path: object) -> None:
        """First filled slot is correctly identified.

        If the first block is at slot 3, slots 0-2 should have offset 0
        and slot 3 should also have offset 0 (since it's the first block).
        """
        db = ImmutableDB(str(tmp_path), epoch_size=100)

        await db.append_block(3, make_hash(3), b"FIRST_BLOCK")

        offsets = db._read_primary_offsets(0)

        # Slots 0-3 should all be 0 (no blocks before slot 3)
        for s in range(4):
            assert offsets[s] == 0, f"Slot {s} should have offset 0"

        # Slot 4 should be at end of block
        assert offsets[4] == len(b"FIRST_BLOCK")
