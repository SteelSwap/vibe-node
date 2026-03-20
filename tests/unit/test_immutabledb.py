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
    ImmutableDB,
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
