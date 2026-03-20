"""Tests for Mithril snapshot import — vibe.cardano.sync.mithril.

Covers:
- Haskell primary index parsing
- Chunk file iteration (parse_immutable_chunks)
- Block header extraction (slot + hash)
- Full import_mithril_snapshot flow
- Edge cases: empty chunks, missing indexes, corrupt blocks

Test spec references (from test_specifications DB):
- test_immutable_db_recovery_truncation
- test_init_from_genesis_when_no_snapshots
- test_init_from_valid_snapshot_on_chain
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import cbor2
import pyarrow as pa
import pytest

from vibe.cardano.storage import ImmutableDB, LedgerDB
from vibe.cardano.sync.mithril import (
    _extract_blocks_from_chunk,
    _extract_slot_and_hash,
    _read_haskell_primary_index,
    import_mithril_snapshot,
    parse_immutable_chunks,
)


# ---------------------------------------------------------------------------
# Helpers: build synthetic Haskell-format chunk + primary index
# ---------------------------------------------------------------------------


def _make_shelley_block(slot: int, block_number: int = 1) -> bytes:
    """Create a minimal tagged Shelley block for testing.

    Structure: Tag(2, [header, tx_bodies, witnesses, auxiliary])
    header = [header_body, body_signature]
    header_body = [block_number, slot, prev_hash, issuer_vkey, vrf_vkey,
                   nonce_vrf, leader_vrf, body_size, body_hash,
                   hot_vkey, seq_num, kes_period, sigma,
                   proto_major, proto_minor]
    """
    header_body = [
        block_number,           # [0] block_number
        slot,                   # [1] slot
        b"\x00" * 32,          # [2] prev_hash
        b"\x01" * 32,          # [3] issuer_vkey
        b"\x02" * 32,          # [4] vrf_vkey
        [b"\x03" * 32, b"\x04" * 64],  # [5] nonce_vrf
        [b"\x05" * 32, b"\x06" * 64],  # [6] leader_vrf
        100,                    # [7] block_body_size
        b"\x07" * 32,          # [8] block_body_hash
        b"\x08" * 32,          # [9] hot_vkey (op cert)
        1,                      # [10] sequence_number
        100,                    # [11] kes_period
        b"\x09" * 64,          # [12] sigma
        7,                      # [13] proto major
        0,                      # [14] proto minor
    ]
    header = [header_body, b"\xaa" * 448]  # body_signature
    block = [header, [], {}, None]  # [header, txs, witnesses, aux]

    # Wrap in CBOR tag 2 (Shelley era).
    payload = cbor2.dumps(block)
    # Tag 2 = 0xC2
    return b"\xc2" + payload


def _make_haskell_primary_index(offsets: list[int]) -> bytes:
    """Build a Haskell-format primary index file from a list of offsets.

    Format: 2-byte header (secondary entry size) + array of uint32 BE offsets.
    """
    header = struct.pack(">H", 56)  # secondary entry size (doesn't matter for our parsing)
    body = b"".join(struct.pack(">I", o) for o in offsets)
    return header + body


def _build_chunk_and_index(
    blocks: list[bytes],
    empty_slots_before: int = 0,
) -> tuple[bytes, bytes]:
    """Build a chunk file and its matching primary index.

    Args:
        blocks: List of CBOR block bytes.
        empty_slots_before: Number of empty slots before the first block.

    Returns:
        (chunk_data, primary_index_data)
    """
    chunk = b"".join(blocks)

    # Build offsets: one per slot + a final sentinel.
    offsets = []
    pos = 0

    # Empty slots before first block
    for _ in range(empty_slots_before):
        offsets.append(pos)

    for block in blocks:
        offsets.append(pos)
        pos += len(block)

    # Sentinel (end-of-last-block offset)
    offsets.append(pos)

    primary = _make_haskell_primary_index(offsets)
    return chunk, primary


# ---------------------------------------------------------------------------
# Tests: primary index parsing
# ---------------------------------------------------------------------------


class TestHaskellPrimaryIndex:
    """Tests for _read_haskell_primary_index."""

    def test_empty_file(self, tmp_path: Path) -> None:
        idx_path = tmp_path / "00000.primary"
        idx_path.write_bytes(b"")
        assert _read_haskell_primary_index(idx_path) == []

    def test_header_only(self, tmp_path: Path) -> None:
        """A file with just the 2-byte header and no offsets."""
        idx_path = tmp_path / "00000.primary"
        idx_path.write_bytes(struct.pack(">H", 56))
        assert _read_haskell_primary_index(idx_path) == []

    def test_single_block(self, tmp_path: Path) -> None:
        """Two offsets: start=0 and end=100."""
        offsets = [0, 100]
        idx_path = tmp_path / "00000.primary"
        idx_path.write_bytes(_make_haskell_primary_index(offsets))
        assert _read_haskell_primary_index(idx_path) == [0, 100]

    def test_multiple_blocks_with_gaps(self, tmp_path: Path) -> None:
        """Offsets with repeated values for empty slots."""
        offsets = [0, 100, 100, 200, 300]  # slot 1 is empty
        idx_path = tmp_path / "00000.primary"
        idx_path.write_bytes(_make_haskell_primary_index(offsets))
        result = _read_haskell_primary_index(idx_path)
        assert result == [0, 100, 100, 200, 300]


# ---------------------------------------------------------------------------
# Tests: block boundary extraction
# ---------------------------------------------------------------------------


class TestExtractBlocks:
    """Tests for _extract_blocks_from_chunk."""

    def test_single_block(self) -> None:
        offsets = [0, 100]
        blocks = list(_extract_blocks_from_chunk(b"\x00" * 100, offsets))
        assert blocks == [(0, 100)]

    def test_empty_slot_skipped(self) -> None:
        """Empty slots (repeated offsets) produce no block."""
        offsets = [0, 100, 100, 200]
        chunk = b"\x00" * 200
        blocks = list(_extract_blocks_from_chunk(chunk, offsets))
        assert len(blocks) == 2
        assert blocks[0] == (0, 100)
        assert blocks[1] == (100, 200)

    def test_offset_beyond_chunk_size_skipped(self) -> None:
        """An offset beyond the chunk data is silently skipped."""
        offsets = [0, 50, 200]  # 200 > chunk size
        chunk = b"\x00" * 100
        blocks = list(_extract_blocks_from_chunk(chunk, offsets))
        assert blocks == [(0, 50)]

    def test_empty_offsets(self) -> None:
        blocks = list(_extract_blocks_from_chunk(b"", []))
        assert blocks == []


# ---------------------------------------------------------------------------
# Tests: slot + hash extraction from CBOR blocks
# ---------------------------------------------------------------------------


class TestExtractSlotAndHash:
    """Tests for _extract_slot_and_hash."""

    def test_shelley_block(self) -> None:
        """Extract slot and hash from a synthetic Shelley block."""
        cbor_bytes = _make_shelley_block(slot=42, block_number=1)
        slot, block_hash = _extract_slot_and_hash(cbor_bytes)
        assert slot == 42
        assert len(block_hash) == 32
        assert isinstance(block_hash, bytes)

    def test_different_slots_produce_different_hashes(self) -> None:
        """Two blocks at different slots have different hashes."""
        b1 = _make_shelley_block(slot=100)
        b2 = _make_shelley_block(slot=200)
        _, h1 = _extract_slot_and_hash(b1)
        _, h2 = _extract_slot_and_hash(b2)
        assert h1 != h2

    def test_malformed_block_raises(self) -> None:
        """A tagged but malformed block should raise ValueError."""
        # Tag 2 (Shelley) + empty array
        bad_block = b"\xc2" + cbor2.dumps([])
        with pytest.raises(ValueError):
            _extract_slot_and_hash(bad_block)


# ---------------------------------------------------------------------------
# Tests: parse_immutable_chunks
# ---------------------------------------------------------------------------


class TestParseImmutableChunks:
    """Tests for parse_immutable_chunks."""

    def test_single_chunk_single_block(self, tmp_path: Path) -> None:
        """One chunk with one Shelley block."""
        block = _make_shelley_block(slot=10)
        chunk_data, primary_data = _build_chunk_and_index([block])

        (tmp_path / "00000.chunk").write_bytes(chunk_data)
        (tmp_path / "00000.primary").write_bytes(primary_data)

        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 1
        slot, bhash, cbor = results[0]
        assert slot == 10
        assert len(bhash) == 32
        assert cbor == block

    def test_multiple_blocks_in_chunk(self, tmp_path: Path) -> None:
        """One chunk with three blocks."""
        blocks = [
            _make_shelley_block(slot=10),
            _make_shelley_block(slot=20),
            _make_shelley_block(slot=30),
        ]
        chunk_data, primary_data = _build_chunk_and_index(blocks)

        (tmp_path / "00000.chunk").write_bytes(chunk_data)
        (tmp_path / "00000.primary").write_bytes(primary_data)

        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 3
        assert [r[0] for r in results] == [10, 20, 30]

    def test_multiple_chunks(self, tmp_path: Path) -> None:
        """Two chunk files, each with one block."""
        for i, slot in enumerate([100, 200]):
            block = _make_shelley_block(slot=slot)
            chunk_data, primary_data = _build_chunk_and_index([block])
            (tmp_path / f"{i:05d}.chunk").write_bytes(chunk_data)
            (tmp_path / f"{i:05d}.primary").write_bytes(primary_data)

        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 2
        assert results[0][0] == 100
        assert results[1][0] == 200

    def test_missing_primary_index_skipped(self, tmp_path: Path) -> None:
        """A chunk without a primary index is skipped."""
        block = _make_shelley_block(slot=10)
        chunk_data, _ = _build_chunk_and_index([block])
        (tmp_path / "00000.chunk").write_bytes(chunk_data)
        # No primary index written.

        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 0

    def test_empty_chunk_dir(self, tmp_path: Path) -> None:
        """An empty directory yields no blocks."""
        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 0

    def test_nonexistent_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            list(parse_immutable_chunks(Path("/nonexistent/dir")))

    def test_chunk_with_empty_slots(self, tmp_path: Path) -> None:
        """Blocks with empty slots between them are correctly parsed."""
        blocks = [
            _make_shelley_block(slot=10),
            _make_shelley_block(slot=30),
        ]
        # Create with 1 empty slot between the blocks.
        chunk_data = b"".join(blocks)
        offsets = [0, len(blocks[0]), len(blocks[0]), len(chunk_data), len(chunk_data)]
        primary_data = _make_haskell_primary_index(offsets)

        (tmp_path / "00000.chunk").write_bytes(chunk_data)
        (tmp_path / "00000.primary").write_bytes(primary_data)

        results = list(parse_immutable_chunks(tmp_path))
        assert len(results) == 2
        assert results[0][0] == 10
        assert results[1][0] == 30


# ---------------------------------------------------------------------------
# Tests: import_mithril_snapshot
# ---------------------------------------------------------------------------


class TestImportMithrilSnapshot:
    """Tests for import_mithril_snapshot."""

    @pytest.mark.asyncio
    async def test_basic_import(self, tmp_path: Path) -> None:
        """Import a snapshot with a few blocks into fresh storage."""
        # Set up snapshot directory structure.
        immutable_dir = tmp_path / "snapshot" / "immutable"
        immutable_dir.mkdir(parents=True)

        blocks = [
            _make_shelley_block(slot=10),
            _make_shelley_block(slot=20),
            _make_shelley_block(slot=30),
        ]
        chunk_data, primary_data = _build_chunk_and_index(blocks)
        (immutable_dir / "00000.chunk").write_bytes(chunk_data)
        (immutable_dir / "00000.primary").write_bytes(primary_data)

        # Create storage instances.
        db_dir = tmp_path / "our_db"
        immutable_db = ImmutableDB(db_dir / "immutable", epoch_size=100)
        ledger_db = LedgerDB(k=10, snapshot_dir=db_dir / "snapshots")

        tip_slot, tip_hash = await import_mithril_snapshot(
            tmp_path / "snapshot", immutable_db, ledger_db
        )

        assert tip_slot == 30
        assert len(tip_hash) == 32
        assert immutable_db.get_tip_slot() == 30

    @pytest.mark.asyncio
    async def test_missing_snapshot_dir_raises(self, tmp_path: Path) -> None:
        db_dir = tmp_path / "db"
        immutable_db = ImmutableDB(db_dir / "immutable")
        ledger_db = LedgerDB()

        with pytest.raises(FileNotFoundError):
            await import_mithril_snapshot(
                tmp_path / "nonexistent", immutable_db, ledger_db
            )

    @pytest.mark.asyncio
    async def test_missing_immutable_dir_raises(self, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        # No immutable/ subdirectory.

        db_dir = tmp_path / "db"
        immutable_db = ImmutableDB(db_dir / "immutable")
        ledger_db = LedgerDB()

        with pytest.raises(FileNotFoundError):
            await import_mithril_snapshot(
                snapshot_dir, immutable_db, ledger_db
            )

    @pytest.mark.asyncio
    async def test_empty_snapshot_raises(self, tmp_path: Path) -> None:
        """An empty immutable dir (no chunks) raises ValueError."""
        immutable_dir = tmp_path / "snapshot" / "immutable"
        immutable_dir.mkdir(parents=True)

        db_dir = tmp_path / "db"
        immutable_db = ImmutableDB(db_dir / "immutable")
        ledger_db = LedgerDB()

        with pytest.raises(ValueError, match="No blocks imported"):
            await import_mithril_snapshot(
                tmp_path / "snapshot", immutable_db, ledger_db
            )

    @pytest.mark.asyncio
    async def test_idempotent_import(self, tmp_path: Path) -> None:
        """Importing the same snapshot twice doesn't duplicate blocks."""
        immutable_dir = tmp_path / "snapshot" / "immutable"
        immutable_dir.mkdir(parents=True)

        blocks = [_make_shelley_block(slot=10)]
        chunk_data, primary_data = _build_chunk_and_index(blocks)
        (immutable_dir / "00000.chunk").write_bytes(chunk_data)
        (immutable_dir / "00000.primary").write_bytes(primary_data)

        db_dir = tmp_path / "our_db"
        immutable_db = ImmutableDB(db_dir / "immutable", epoch_size=100)
        ledger_db = LedgerDB(k=10)

        # First import succeeds.
        tip_slot, _ = await import_mithril_snapshot(
            tmp_path / "snapshot", immutable_db, ledger_db
        )
        assert tip_slot == 10

        # Second import of same data — should raise (all blocks skipped).
        with pytest.raises(ValueError, match="No blocks imported"):
            await import_mithril_snapshot(
                tmp_path / "snapshot", immutable_db, ledger_db
            )
