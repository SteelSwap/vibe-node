"""Tests for vibe.cardano.storage.volatile -- Haskell parity gaps.

Covers:
- max_blocks_per_file: VolatileDB one-block-per-file layout is respected

Haskell references:
    Ouroboros.Consensus.Storage.VolatileDB.Impl
    Test.Ouroboros.Storage.VolatileDB (maxBlocksPerFile property)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe.cardano.storage.volatile import VolatileDB


def _block_hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _genesis_hash() -> bytes:
    return b"\x00" * 32


# ---------------------------------------------------------------------------
# test_volatiledb_max_blocks_per_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_volatiledb_max_blocks_per_file(tmp_path: Path) -> None:
    """VolatileDB stores at most one block per file.

    Our VolatileDB uses a one-block-per-file layout (<hash>.block files).
    This test verifies that after adding N blocks, exactly N files exist
    on disk, and each file contains exactly one block's CBOR data.

    Haskell reference:
        The Haskell VolatileDB packs multiple blocks per file with a
        configurable maxBlocksPerFile. Our simplified implementation
        uses exactly 1 block per file (maxBlocksPerFile = 1 effectively).
        Test.Ouroboros.Storage.VolatileDB.prop_maxBlocksPerFile verifies
        the file count invariant.
    """
    db_dir = tmp_path / "volatile"
    db = VolatileDB(db_dir=db_dir)

    num_blocks = 5
    prev_hash = _genesis_hash()
    hashes = []

    for i in range(1, num_blocks + 1):
        bh = _block_hash(i)
        hashes.append(bh)
        cbor = f"block-data-{i}".encode()
        db.add_block(
            block_hash=bh,
            slot=i,
            predecessor_hash=prev_hash,
            block_number=i,
            cbor_bytes=cbor,
        )
        prev_hash = bh

    # Flush buffered writes before checking disk state.
    db._flush_writes()
    # Count .block files on disk.
    block_files = list(db_dir.glob("*.block"))
    assert len(block_files) == num_blocks, (
        f"Expected {num_blocks} .block files, found {len(block_files)}"
    )

    # Each file should contain exactly its block's CBOR data.
    for i, bh in enumerate(hashes, 1):
        filepath = db_dir / f"{bh.hex()}.block"
        assert filepath.exists(), f"Missing block file for hash {bh.hex()[:8]}"
        data = filepath.read_bytes()
        assert data == f"block-data-{i}".encode()

    # After GC, files for removed blocks should be gone.
    gc_count = db.gc(immutable_tip_slot=3)
    assert gc_count == 3  # blocks at slots 1, 2, 3

    remaining_files = list(db_dir.glob("*.block"))
    assert len(remaining_files) == 2  # blocks at slots 4, 5


# ---------------------------------------------------------------------------
# Additional Haskell-parity tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_and_get_block() -> None:
    """Add a block to an in-memory VolatileDB and retrieve it by hash.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.putBlock / getBlockComponent
    """
    db = VolatileDB(db_dir=None)
    bh = _block_hash(42)
    cbor = b"round-trip-payload"

    db.add_block(
        block_hash=bh,
        slot=10,
        predecessor_hash=_genesis_hash(),
        block_number=1,
        cbor_bytes=cbor,
    )

    result = db.get_block(bh)
    assert result == cbor
    assert db.block_count == 1


@pytest.mark.asyncio
async def test_add_duplicate_block() -> None:
    """Adding the same block hash twice is idempotent -- second write overwrites.

    Haskell reference:
        The Haskell VolatileDB's putBlock silently overwrites if the same
        block hash already exists.
    """
    db = VolatileDB(db_dir=None)
    bh = _block_hash(1)
    genesis = _genesis_hash()

    db.add_block(
        block_hash=bh,
        slot=1,
        predecessor_hash=genesis,
        block_number=1,
        cbor_bytes=b"first",
    )
    db.add_block(
        block_hash=bh,
        slot=1,
        predecessor_hash=genesis,
        block_number=1,
        cbor_bytes=b"second",
    )

    # The second write should have overwritten
    result = db.get_block(bh)
    assert result == b"second"
    # Block count stays at 1 (same key)
    assert db.block_count == 1


@pytest.mark.asyncio
async def test_get_block_not_found() -> None:
    """Querying a nonexistent hash returns None.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.getBlockComponent
        returns Nothing for missing blocks.
    """
    db = VolatileDB(db_dir=None)
    result = db.get_block(_block_hash(999))
    assert result is None


@pytest.mark.asyncio
async def test_get_predecessor() -> None:
    """The successor map correctly tracks predecessor relationships.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.filterByPredecessor
    """
    db = VolatileDB(db_dir=None)
    genesis = _genesis_hash()

    bh1 = _block_hash(1)
    bh2 = _block_hash(2)
    bh3 = _block_hash(3)

    # Chain: genesis -> bh1 -> bh2
    # Fork:  genesis -> bh3
    db.add_block(
        block_hash=bh1,
        slot=1,
        predecessor_hash=genesis,
        block_number=1,
        cbor_bytes=b"b1",
    )
    db.add_block(
        block_hash=bh2,
        slot=2,
        predecessor_hash=bh1,
        block_number=2,
        cbor_bytes=b"b2",
    )
    db.add_block(
        block_hash=bh3,
        slot=1,
        predecessor_hash=genesis,
        block_number=1,
        cbor_bytes=b"b3",
    )

    # Genesis has two successors
    successors = db.get_successors(genesis)
    assert set(successors) == {bh1, bh3}

    # bh1 has one successor
    successors_of_bh1 = db.get_successors(bh1)
    assert successors_of_bh1 == [bh2]

    # bh2 has no successors
    successors_of_bh2 = db.get_successors(bh2)
    assert successors_of_bh2 == []

    # Block info tracks the predecessor hash
    info = db.get_block_info(bh2)
    assert info is not None
    assert info.predecessor_hash == bh1


@pytest.mark.asyncio
async def test_gc_removes_old_blocks() -> None:
    """GC removes blocks at or below the immutable tip slot.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.garbageCollect
        Removes all blocks with slot <= immutableTipSlot.
    """
    db = VolatileDB(db_dir=None)
    genesis = _genesis_hash()

    prev = genesis
    for i in range(1, 11):
        bh = _block_hash(i)
        db.add_block(
            block_hash=bh,
            slot=i,
            predecessor_hash=prev,
            block_number=i,
            cbor_bytes=f"block-{i}".encode(),
        )
        prev = bh

    assert db.block_count == 10

    # GC everything at or below slot 7
    removed = db.gc(immutable_tip_slot=7)
    assert removed == 7
    assert db.block_count == 3

    # Blocks 1-7 are gone
    for i in range(1, 8):
        assert db.get_block(_block_hash(i)) is None

    # Blocks 8-10 survive
    for i in range(8, 11):
        result = db.get_block(_block_hash(i))
        assert result is not None
        assert result == f"block-{i}".encode()

    # Max slot should reflect surviving blocks
    max_slot = db.get_max_slot()
    assert max_slot == 10
