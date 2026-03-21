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

from vibe.cardano.storage.volatile import VolatileDB, BlockInfo


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
        await db.add_block(
            block_hash=bh,
            slot=i,
            predecessor_hash=prev_hash,
            block_number=i,
            cbor_bytes=cbor,
        )
        prev_hash = bh

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
    gc_count = await db.gc(immutable_tip_slot=3)
    assert gc_count == 3  # blocks at slots 1, 2, 3

    remaining_files = list(db_dir.glob("*.block"))
    assert len(remaining_files) == 2  # blocks at slots 4, 5
