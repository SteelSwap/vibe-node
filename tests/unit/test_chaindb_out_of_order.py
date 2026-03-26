"""Tests for ChainDB out-of-order block arrival (multi-peer support)."""

from __future__ import annotations

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB


def _make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte hash from an integer."""
    return n.to_bytes(32, "big")


def _make_chaindb(tmp_path, k: int = 10) -> ChainDB:
    """Create a ChainDB with disk-backed stores (matches existing test pattern)."""
    imm = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=1000)
    vol = VolatileDB(db_dir=tmp_path / "volatile")
    led = LedgerDB(k=k, snapshot_dir=tmp_path / "ledger")
    return ChainDB(immutable_db=imm, volatile_db=vol, ledger_db=led, k=k)


class TestOutOfOrderArrival:
    """Verify ChainDB handles blocks arriving out of chain order."""

    @pytest.mark.asyncio
    async def test_successor_arrives_before_predecessor(self, tmp_path):
        """Block N+2 arrives before N+1. After N+1 arrives, chain extends to N+2."""
        db = _make_chaindb(tmp_path)

        # Block 1 (genesis child)
        r1 = await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )
        assert r1.adopted

        # Block 3 arrives BEFORE block 2 — predecessor not yet stored
        r3 = await db.add_block(
            slot=3, block_hash=_make_hash(3), predecessor_hash=_make_hash(2),
            block_number=3, cbor_bytes=b"block3",
        )
        # Block 3 stored but chain can't extend (predecessor not reachable)
        assert db._tip.block_number == 1

        # Block 2 arrives — fills the gap
        r2 = await db.add_block(
            slot=2, block_hash=_make_hash(2), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2",
        )
        # Now chain should extend through 1 -> 2 -> 3
        assert r2.adopted
        assert db._tip.block_number == 3

    @pytest.mark.asyncio
    async def test_multiple_successors_picks_longest(self, tmp_path):
        """Multiple forward paths from a new block — picks the longest."""
        db = _make_chaindb(tmp_path)

        # Block 1
        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Blocks 3, 4, 5 arrive (chain fragment without block 2)
        for i in [3, 4, 5]:
            await db.add_block(
                slot=i, block_hash=_make_hash(i), predecessor_hash=_make_hash(i - 1),
                block_number=i, cbor_bytes=b"block",
            )
        assert db._tip.block_number == 1  # can't extend yet

        # Block 2 fills the gap — chain extends to 5
        await db.add_block(
            slot=2, block_hash=_make_hash(2), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2",
        )
        assert db._tip.block_number == 5

    @pytest.mark.asyncio
    async def test_unreachable_block_stored_but_no_switch(self, tmp_path):
        """Block whose predecessor is not reachable is stored but tip unchanged."""
        db = _make_chaindb(tmp_path)

        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Block on a different chain (predecessor 99, not stored)
        await db.add_block(
            slot=10, block_hash=_make_hash(10), predecessor_hash=_make_hash(99),
            block_number=10, cbor_bytes=b"orphan",
        )
        assert db._tip.block_number == 1
        assert _make_hash(10) in db.volatile_db._blocks

    @pytest.mark.asyncio
    async def test_sibling_chain_picked_when_longer(self, tmp_path):
        """When gap-filler arrives, evaluate ALL successor paths from predecessor."""
        db = _make_chaindb(tmp_path)

        # Main chain: 0 -> 1
        await db.add_block(
            slot=1, block_hash=_make_hash(1), predecessor_hash=_make_hash(0),
            block_number=1, cbor_bytes=b"block1",
        )

        # Fork A (stored out of order): 1 -> 2a -> 3a
        await db.add_block(
            slot=3, block_hash=_make_hash(30), predecessor_hash=_make_hash(20),
            block_number=3, cbor_bytes=b"block3a",
        )
        await db.add_block(
            slot=2, block_hash=_make_hash(20), predecessor_hash=_make_hash(1),
            block_number=2, cbor_bytes=b"block2a",
        )
        # Should extend to 3a via successor walk
        assert db._tip.block_number == 3
