"""ImmutableDB tests — Haskell parity for append-only epoch-chunked storage.

Covers:
- Append block and retrieve by hash
- Sequential block appending
- Tip slot and hash tracking
- Block-not-found returns None
- Chunk rollover across epoch boundaries

Haskell references:
    Ouroboros.Consensus.Storage.ImmutableDB.API (appendBlock, getBlockComponent, getTip)
    Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
    Test.Ouroboros.Storage.ImmutableDB

Antithesis compatibility:
    All tests use deterministic data and can be replayed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe.cardano.storage.immutable import (
    AppendBlockNotNewerThanTipError,
    ImmutableDB,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block_hash(n: int) -> bytes:
    """Create a deterministic 32-byte block hash."""
    return n.to_bytes(32, "big")


def _cbor(n: int, size: int = 64) -> bytes:
    """Create a deterministic fake CBOR payload."""
    return (n.to_bytes(4, "big") * ((size // 4) + 1))[:size]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImmutableDBAppendAndRetrieve:
    """Append blocks and retrieve them by hash.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.appendBlock
        Ouroboros.Consensus.Storage.ImmutableDB.API.getBlockComponent
    """

    @pytest.mark.asyncio
    async def test_append_block_and_retrieve(self, tmp_path: Path) -> None:
        """Add a single block and retrieve it by hash."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        bh = _block_hash(1)
        data = _cbor(1)
        await db.append_block(slot=1, block_hash=bh, cbor_bytes=data)

        result = await db.get_block(bh)
        assert result is not None
        assert result == data

    @pytest.mark.asyncio
    async def test_append_sequential_blocks(self, tmp_path: Path) -> None:
        """Multiple blocks appended in slot order are all retrievable."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        blocks = []
        for i in range(1, 6):
            bh = _block_hash(i)
            data = _cbor(i, size=32 + i * 8)  # varying sizes
            blocks.append((bh, data))
            await db.append_block(slot=i, block_hash=bh, cbor_bytes=data)

        for bh, expected_data in blocks:
            result = await db.get_block(bh)
            assert result is not None, f"Block {bh.hex()[:8]} not found"
            assert result == expected_data

    @pytest.mark.asyncio
    async def test_append_rejects_non_monotonic_slot(self, tmp_path: Path) -> None:
        """Appending a block at slot <= tip slot raises an error.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.AppendBlockNotNewerThanTipError
        """
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        await db.append_block(slot=5, block_hash=_block_hash(1), cbor_bytes=_cbor(1))

        with pytest.raises(AppendBlockNotNewerThanTipError):
            await db.append_block(slot=3, block_hash=_block_hash(2), cbor_bytes=_cbor(2))

        with pytest.raises(AppendBlockNotNewerThanTipError):
            await db.append_block(slot=5, block_hash=_block_hash(3), cbor_bytes=_cbor(3))


class TestImmutableDBTipTracking:
    """Verify tip slot and hash tracking after appends.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.getTip
    """

    @pytest.mark.asyncio
    async def test_get_tip_slot(self, tmp_path: Path) -> None:
        """Tip slot updates after each append."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        assert db.get_tip_slot() is None

        await db.append_block(slot=10, block_hash=_block_hash(1), cbor_bytes=_cbor(1))
        assert db.get_tip_slot() == 10

        await db.append_block(slot=20, block_hash=_block_hash(2), cbor_bytes=_cbor(2))
        assert db.get_tip_slot() == 20

    @pytest.mark.asyncio
    async def test_get_tip_hash(self, tmp_path: Path) -> None:
        """Tip hash updates to the most recently appended block's hash."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        assert db.get_tip_hash() is None

        bh1 = _block_hash(1)
        await db.append_block(slot=1, block_hash=bh1, cbor_bytes=_cbor(1))
        assert db.get_tip_hash() == bh1

        bh2 = _block_hash(2)
        await db.append_block(slot=2, block_hash=bh2, cbor_bytes=_cbor(2))
        assert db.get_tip_hash() == bh2

    @pytest.mark.asyncio
    async def test_get_tip_key(self, tmp_path: Path) -> None:
        """get_tip returns a 40-byte key (8-byte slot + 32-byte hash)."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        assert await db.get_tip() is None

        bh = _block_hash(42)
        await db.append_block(slot=100, block_hash=bh, cbor_bytes=_cbor(42))

        tip_key = await db.get_tip()
        assert tip_key is not None
        assert len(tip_key) == 40
        # First 8 bytes encode the slot
        import struct

        tip_slot = struct.unpack(">Q", tip_key[:8])[0]
        assert tip_slot == 100
        assert tip_key[8:40] == bh


class TestImmutableDBBlockNotFound:
    """Querying for nonexistent blocks returns None.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.getBlockComponent
        returns Nothing for missing blocks
    """

    @pytest.mark.asyncio
    async def test_block_not_found(self, tmp_path: Path) -> None:
        """get_block returns None for a hash not in the DB."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        result = await db.get_block(_block_hash(999))
        assert result is None

    @pytest.mark.asyncio
    async def test_block_not_found_after_appends(self, tmp_path: Path) -> None:
        """get_block returns None for a hash not among appended blocks."""
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=100)

        await db.append_block(slot=1, block_hash=_block_hash(1), cbor_bytes=_cbor(1))
        await db.append_block(slot=2, block_hash=_block_hash(2), cbor_bytes=_cbor(2))

        result = await db.get_block(_block_hash(999))
        assert result is None


class TestImmutableDBChunkRollover:
    """Blocks spanning multiple epoch chunks.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
        Chunk files are per-epoch; blocks crossing epoch boundaries
        go into the next chunk file.
    """

    @pytest.mark.asyncio
    async def test_chunk_rollover(self, tmp_path: Path) -> None:
        """Blocks across epoch boundaries create separate chunk files."""
        epoch_size = 10
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=epoch_size)

        # Add blocks in epochs 0, 1, and 2
        slots = [1, 5, 9, 11, 15, 21]
        hashes = []
        payloads = []
        for i, slot in enumerate(slots):
            bh = _block_hash(i + 1)
            data = _cbor(i + 1)
            hashes.append(bh)
            payloads.append(data)
            await db.append_block(slot=slot, block_hash=bh, cbor_bytes=data)

        # Verify all blocks are retrievable
        for bh, expected in zip(hashes, payloads):
            result = await db.get_block(bh)
            assert result is not None, f"Block {bh.hex()[:8]} not found"
            assert result == expected

        # Verify chunk files exist for epochs 0, 1, 2
        chunk_dir = tmp_path / "imm" / "chunks"
        assert (chunk_dir / "chunk-000000.dat").exists()  # epoch 0: slots 0-9
        assert (chunk_dir / "chunk-000001.dat").exists()  # epoch 1: slots 10-19
        assert (chunk_dir / "chunk-000002.dat").exists()  # epoch 2: slots 20-29

    @pytest.mark.asyncio
    async def test_slot_based_lookup_across_chunks(self, tmp_path: Path) -> None:
        """Blocks can be retrieved by slot across chunk boundaries."""
        epoch_size = 5
        db = ImmutableDB(base_dir=tmp_path / "imm", epoch_size=epoch_size)

        # Slot 3 in chunk 0, slot 7 in chunk 1
        data_a = _cbor(10, size=48)
        data_b = _cbor(20, size=96)
        await db.append_block(slot=3, block_hash=_block_hash(10), cbor_bytes=data_a)
        await db.append_block(slot=7, block_hash=_block_hash(20), cbor_bytes=data_b)

        result_a = await db.get_block_by_slot(3)
        assert result_a == data_a

        result_b = await db.get_block_by_slot(7)
        assert result_b == data_b

        # Empty slot returns None
        assert await db.get_block_by_slot(4) is None


class TestImmutableDBRecovery:
    """Startup recovery rebuilds state from on-disk indexes.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.Impl.openDBInternal
    """

    @pytest.mark.asyncio
    async def test_recovery_after_reopen(self, tmp_path: Path) -> None:
        """A new ImmutableDB instance recovers state from disk."""
        base = tmp_path / "imm"
        db = ImmutableDB(base_dir=base, epoch_size=100)

        bh1 = _block_hash(1)
        bh2 = _block_hash(2)
        await db.append_block(slot=10, block_hash=bh1, cbor_bytes=_cbor(1))
        await db.append_block(slot=20, block_hash=bh2, cbor_bytes=_cbor(2))

        # Re-open — simulates restart
        db2 = ImmutableDB(base_dir=base, epoch_size=100)

        assert db2.get_tip_slot() == 20
        assert db2.get_tip_hash() == bh2

        # Blocks are still retrievable
        assert await db2.get_block(bh1) == _cbor(1)
        assert await db2.get_block(bh2) == _cbor(2)

        # Can append after recovery
        bh3 = _block_hash(3)
        await db2.append_block(slot=30, block_hash=bh3, cbor_bytes=_cbor(3))
        assert db2.get_tip_slot() == 30
