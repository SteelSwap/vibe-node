"""Tests for ChainDB chain fragment and ChainSelectionResult."""

from __future__ import annotations

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB


def _hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _hdr(n: int) -> list:
    """Dummy header CBOR for block n."""
    return [6, b"header" + n.to_bytes(4, "big")]


@pytest.fixture
def chain_db(tmp_path):
    """Create a ChainDB with in-memory volatile and minimal immutable/ledger."""
    vol = VolatileDB(db_dir=None)  # in-memory
    imm = ImmutableDB(base_dir=tmp_path / "immutable")
    led = LedgerDB()
    db = ChainDB(imm, vol, led, k=10)
    db.start_chain_sel_runner()
    yield db
    db.stop_chain_sel_runner()


class TestChainFragment:
    """Test that add_block maintains the chain fragment correctly."""

    def test_first_block_creates_fragment(self, chain_db):
        result = chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"block1",
            header_cbor=_hdr(1),
        )
        assert result.adopted is True
        frag = chain_db.get_current_chain()
        assert len(frag) == 1
        assert frag[0].block_hash == _hash(1)

    def test_extending_chain_appends_to_fragment(self, chain_db):
        chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        result = chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        assert result.adopted is True
        assert result.rollback_depth == 0
        frag = chain_db.get_current_chain()
        assert len(frag) == 2
        assert frag[0].block_hash == _hash(1)
        assert frag[1].block_hash == _hash(2)

    def test_worse_block_not_adopted(self, chain_db):
        chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        # Block at same height — not adopted (no improvement)
        result = chain_db.add_block(
            slot=3,
            block_hash=_hash(99),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b99",
            header_cbor=_hdr(99),
        )
        assert result.adopted is False

    def test_fragment_trimmed_to_k(self, chain_db):
        # k=10, add 15 blocks
        prev = _hash(0)
        for i in range(1, 16):
            chain_db.add_block(
                slot=i,
                block_hash=_hash(i),
                predecessor_hash=prev,
                block_number=i,
                cbor_bytes=f"b{i}".encode(),
                header_cbor=_hdr(i),
            )
            prev = _hash(i)
        frag = chain_db.get_current_chain()
        assert len(frag) <= 10


class TestChainSelectionResult:
    """Test ChainSelectionResult fields for different scenarios."""

    def test_fork_switch_result(self, chain_db):
        # Build chain: 0 → 1 → 2
        chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        # Fork: 0 → 1 → 3 (block_number=3, better than 2)
        result = chain_db.add_block(
            slot=3,
            block_hash=_hash(3),
            predecessor_hash=_hash(1),
            block_number=3,
            cbor_bytes=b"b3",
            header_cbor=_hdr(3),
        )
        assert result.adopted is True
        assert result.rollback_depth == 1
        assert _hash(2) in result.removed_hashes
        assert result.intersection_hash == _hash(1)

    def test_fragment_correct_after_fork_switch(self, chain_db):
        chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        chain_db.add_block(
            slot=3,
            block_hash=_hash(3),
            predecessor_hash=_hash(1),
            block_number=3,
            cbor_bytes=b"b3",
            header_cbor=_hdr(3),
        )
        frag = chain_db.get_current_chain()
        hashes = [e.block_hash for e in frag]
        assert _hash(1) in hashes
        assert _hash(3) in hashes
        assert _hash(2) not in hashes  # orphaned

    def test_below_immutable_tip_not_adopted(self, chain_db):
        """Block below immutable tip should be ignored."""
        # Manually set immutable tip
        chain_db._immutable_tip_block_number = 5
        result = chain_db.add_block(
            slot=3,
            block_hash=_hash(3),
            predecessor_hash=_hash(2),
            block_number=3,
            cbor_bytes=b"b3",
            header_cbor=_hdr(3),
        )
        assert result.adopted is False
