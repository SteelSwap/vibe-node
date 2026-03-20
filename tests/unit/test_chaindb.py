"""Tests for vibe.cardano.storage.chaindb — ChainDB coordinator.

Covers the test specifications from the database for the storage subsystem:
- test_chain_selection_prefers_higher_select_view
- test_chain_selection_equal_select_view_incomparable
- test_chain_selection_rejects_fork_beyond_k
- test_get_block_queries_volatile_first_then_immutable
- test_get_block_component_not_in_volatile_falls_back_to_immutable
- test_blocks_is_union_of_volatile_and_immutable
- test_ignore_block_older_than_immutable_tip
- test_ignore_block_equal_to_immutable_tip
- test_accept_block_one_above_immutable_tip
- test_immutable_tip_never_rolled_back
"""

from __future__ import annotations

import os
import struct

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import BlockInfo, VolatileDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte block hash from an integer."""
    return n.to_bytes(32, "big")


GENESIS_HASH = make_hash(0)


def make_block_cbor(slot: int, block_number: int) -> bytes:
    """Create fake CBOR bytes that encode slot and block number.

    Not real CBOR — just deterministic bytes for round-trip testing.
    """
    return struct.pack(">QI", slot, block_number) + b"\x00" * 20


async def add_chain(
    chain_db: ChainDB,
    start_slot: int,
    count: int,
    start_block_number: int = 1,
    predecessor: bytes | None = None,
    hash_offset: int = 1,
) -> list[tuple[int, bytes, bytes, int, bytes]]:
    """Add a linear chain of blocks to the ChainDB.

    Returns list of (slot, hash, predecessor_hash, block_number, cbor) tuples.
    """
    blocks = []
    pred = predecessor or GENESIS_HASH
    for i in range(count):
        slot = start_slot + i
        bn = start_block_number + i
        bh = make_hash(hash_offset + i)
        cbor = make_block_cbor(slot, bn)
        await chain_db.add_block(slot, bh, pred, bn, cbor)
        blocks.append((slot, bh, pred, bn, cbor))
        pred = bh
    return blocks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_db(tmp_path):
    """Create a ChainDB with k=3 for fast testing."""
    imm = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=1000)
    vol = VolatileDB(db_dir=tmp_path / "volatile")
    led = LedgerDB(k=3, snapshot_dir=tmp_path / "ledger")
    return ChainDB(immutable_db=imm, volatile_db=vol, ledger_db=led, k=3)


@pytest.fixture
def chain_db_k10(tmp_path):
    """Create a ChainDB with k=10 for immutable-tip tests."""
    imm = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=1000)
    vol = VolatileDB(db_dir=tmp_path / "volatile")
    led = LedgerDB(k=10, snapshot_dir=tmp_path / "ledger")
    return ChainDB(immutable_db=imm, volatile_db=vol, ledger_db=led, k=10)


# ---------------------------------------------------------------------------
# Test: add blocks and verify tip advances
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_block_updates_tip(chain_db):
    """Adding blocks should advance the chain tip."""
    assert await chain_db.get_tip() is None

    blocks = await add_chain(chain_db, start_slot=1, count=3)
    tip = await chain_db.get_tip()
    assert tip is not None
    assert tip[0] == 3  # slot
    assert tip[1] == blocks[2][1]  # hash of last block


@pytest.mark.asyncio
async def test_tip_advances_with_each_block(chain_db):
    """Tip should update after every block with a higher block_number."""
    for i in range(1, 6):
        await chain_db.add_block(
            slot=i,
            block_hash=make_hash(i),
            predecessor_hash=make_hash(i - 1) if i > 1 else GENESIS_HASH,
            block_number=i,
            cbor_bytes=make_block_cbor(i, i),
        )
        tip = await chain_db.get_tip()
        assert tip is not None
        assert tip[0] == i
        assert tip[1] == make_hash(i)


# ---------------------------------------------------------------------------
# Test: chain selection picks longest chain
# test_chain_selection_prefers_higher_select_view
# test_chain_selection_equal_select_view_incomparable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_selection_prefers_higher_block_number(chain_db):
    """Chain with higher block_number should be selected as tip.

    Spec: test_chain_selection_prefers_higher_select_view
    """
    # Chain A: blocks 1,2,3
    await add_chain(chain_db, start_slot=1, count=3, hash_offset=100)

    # Chain B (fork from genesis): blocks 1,2,3,4 — higher block_number
    await add_chain(chain_db, start_slot=10, count=4, hash_offset=200)

    tip = await chain_db.get_tip()
    assert tip is not None
    # Chain B has block_number 4 at slot 13
    assert tip[0] == 13
    assert tip[1] == make_hash(203)


@pytest.mark.asyncio
async def test_chain_selection_equal_block_number_keeps_existing(chain_db):
    """When two chains have equal block_number, keep the current tip.

    Spec: test_chain_selection_equal_select_view_incomparable
    """
    # Chain A: blocks 1,2,3
    blocks_a = await add_chain(chain_db, start_slot=1, count=3, hash_offset=100)

    # Chain B (fork from genesis): also blocks 1,2,3 — same height
    blocks_b = await add_chain(chain_db, start_slot=10, count=3, hash_offset=200)

    tip = await chain_db.get_tip()
    assert tip is not None
    # Chain A was added first and has block_number=3, chain B also has 3
    # Since equal, we keep the first tip (chain A)
    assert tip[1] == blocks_a[2][1]


# ---------------------------------------------------------------------------
# Test: blocks move from volatile to immutable after k confirmations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocks_promoted_to_immutable_after_k(chain_db):
    """Blocks should move from volatile to immutable when chain grows past k.

    With k=3, after adding blocks 1..7, blocks 1..4 should be in immutable
    (tip block_number=7, immutable tip = 7-3 = 4).
    """
    blocks = await add_chain(chain_db, start_slot=1, count=7)

    # The immutable tip should have advanced
    imm_tip_slot = chain_db.immutable_db.get_tip_slot()
    assert imm_tip_slot is not None
    assert imm_tip_slot == 4  # block_number 4 is at slot 4

    # Blocks 1-4 should be in immutable
    for slot, bh, _, bn, cbor in blocks[:4]:
        result = await chain_db.immutable_db.get_block(bh)
        assert result == cbor, f"Block at slot {slot} missing from immutable"

    # Blocks 5-7 should still be in volatile (or possibly GC'd from volatile
    # if they were below the GC threshold — but blocks 5-7 are above slot 4)
    for slot, bh, _, bn, cbor in blocks[4:]:
        result = await chain_db.volatile_db.get_block(bh)
        assert result == cbor, f"Block at slot {slot} missing from volatile"


@pytest.mark.asyncio
async def test_gc_cleans_volatile_after_promotion(chain_db):
    """After promotion, volatile GC should remove finalized blocks.

    With k=3, after adding blocks 1..7, blocks 1..4 get promoted and
    GC'd from volatile.
    """
    blocks = await add_chain(chain_db, start_slot=1, count=7)

    # Blocks at or below immutable slot 4 should be gone from volatile
    for slot, bh, _, bn, cbor in blocks[:4]:
        result = await chain_db.volatile_db.get_block(bh)
        assert result is None, (
            f"Block at slot {slot} should have been GC'd from volatile"
        )


# ---------------------------------------------------------------------------
# Test: block lookup searches volatile then immutable
# test_get_block_queries_volatile_first_then_immutable
# test_get_block_component_not_in_volatile_falls_back_to_immutable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_block_searches_volatile_then_immutable(chain_db):
    """get_block should check volatile first, then fall back to immutable.

    Spec: test_get_block_queries_volatile_first_then_immutable
    """
    blocks = await add_chain(chain_db, start_slot=1, count=7)

    # Block at slot 2 (promoted to immutable, GC'd from volatile)
    result = await chain_db.get_block(blocks[1][1])
    assert result == blocks[1][4], "Should find promoted block via immutable"

    # Block at slot 6 (still in volatile)
    result = await chain_db.get_block(blocks[5][1])
    assert result == blocks[5][4], "Should find volatile block"

    # Non-existent block
    result = await chain_db.get_block(make_hash(999))
    assert result is None


@pytest.mark.asyncio
async def test_get_block_fallback_to_immutable(chain_db):
    """Block not in volatile but in immutable should be found.

    Spec: test_get_block_component_not_in_volatile_falls_back_to_immutable
    """
    blocks = await add_chain(chain_db, start_slot=1, count=7)

    # Slot 1 block: promoted to immutable, GC'd from volatile
    bh = blocks[0][1]
    assert await chain_db.volatile_db.get_block(bh) is None
    assert await chain_db.immutable_db.get_block(bh) is not None

    # ChainDB should still find it
    result = await chain_db.get_block(bh)
    assert result == blocks[0][4]


# ---------------------------------------------------------------------------
# Test: blocks is union of volatile and immutable
# test_blocks_is_union_of_volatile_and_immutable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_blocks_accessible(chain_db):
    """Every added block should be accessible via get_block, regardless
    of which sub-store holds it.

    Spec: test_blocks_is_union_of_volatile_and_immutable
    """
    blocks = await add_chain(chain_db, start_slot=1, count=7)

    for slot, bh, _, bn, cbor in blocks:
        result = await chain_db.get_block(bh)
        assert result == cbor, f"Block at slot {slot} not found"


# ---------------------------------------------------------------------------
# Test: ignore blocks at or below immutable tip
# test_ignore_block_older_than_immutable_tip
# test_ignore_block_equal_to_immutable_tip
# test_accept_block_one_above_immutable_tip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignore_block_older_than_immutable_tip(chain_db):
    """A block with blockNo < immutable tip blockNo should be ignored.

    Spec: test_ignore_block_older_than_immutable_tip
    """
    # Build chain long enough to advance immutable tip
    await add_chain(chain_db, start_slot=1, count=7)
    # Immutable tip is at block_number=4

    # Try to add a block with block_number=2 (below immutable tip)
    old_hash = make_hash(900)
    vol_count_before = chain_db.volatile_db.block_count
    await chain_db.add_block(
        slot=50,
        block_hash=old_hash,
        predecessor_hash=GENESIS_HASH,
        block_number=2,
        cbor_bytes=make_block_cbor(50, 2),
    )
    # Should not have been added to volatile
    assert chain_db.volatile_db.block_count == vol_count_before
    assert await chain_db.volatile_db.get_block(old_hash) is None


@pytest.mark.asyncio
async def test_ignore_block_equal_to_immutable_tip(chain_db):
    """A block with blockNo == immutable tip blockNo should be ignored.

    Spec: test_ignore_block_equal_to_immutable_tip
    """
    await add_chain(chain_db, start_slot=1, count=7)
    # Immutable tip at block_number=4

    eq_hash = make_hash(901)
    await chain_db.add_block(
        slot=51,
        block_hash=eq_hash,
        predecessor_hash=GENESIS_HASH,
        block_number=4,
        cbor_bytes=make_block_cbor(51, 4),
    )
    assert await chain_db.volatile_db.get_block(eq_hash) is None


@pytest.mark.asyncio
async def test_accept_block_one_above_immutable_tip(chain_db):
    """A block with blockNo == immutableTipBlockNo + 1 should be accepted.

    Spec: test_accept_block_one_above_immutable_tip
    """
    await add_chain(chain_db, start_slot=1, count=7)
    # Immutable tip at block_number=4

    new_hash = make_hash(902)
    await chain_db.add_block(
        slot=52,
        block_hash=new_hash,
        predecessor_hash=make_hash(4),
        block_number=5,
        cbor_bytes=make_block_cbor(52, 5),
    )
    # Should be in volatile
    assert await chain_db.volatile_db.get_block(new_hash) is not None


# ---------------------------------------------------------------------------
# Test: immutable tip never rolls back
# test_immutable_tip_never_rolled_back
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_immutable_tip_never_rolls_back(chain_db_k10):
    """The immutable tip should only advance, never retreat.

    Spec: test_immutable_tip_never_rolled_back
    """
    db = chain_db_k10  # k=10

    # Build a chain of 15 blocks — immutable tip advances to blockNo 5
    await add_chain(db, start_slot=1, count=15)

    imm_bn_1 = db._immutable_tip_block_number
    assert imm_bn_1 is not None
    assert imm_bn_1 == 5  # 15 - 10 = 5

    # Extend the chain further
    await add_chain(
        db,
        start_slot=16,
        count=5,
        start_block_number=16,
        predecessor=make_hash(15),
        hash_offset=100,
    )

    imm_bn_2 = db._immutable_tip_block_number
    assert imm_bn_2 is not None
    assert imm_bn_2 >= imm_bn_1, "Immutable tip must not roll back"
    assert imm_bn_2 == 10  # 20 - 10 = 10


# ---------------------------------------------------------------------------
# Test: explicit advance_immutable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advance_immutable_explicit(chain_db):
    """Explicitly advancing the immutable tip should move blocks."""
    # Add 5 blocks (not enough for automatic promotion with k=3)
    blocks = await add_chain(chain_db, start_slot=1, count=3)

    # All should be in volatile
    for _, bh, _, _, cbor in blocks:
        assert await chain_db.volatile_db.get_block(bh) == cbor

    # Manually advance immutable to slot 2
    copied = await chain_db.advance_immutable(2)
    assert copied == 2  # blocks at slot 1 and 2

    # Blocks 1-2 should now be in immutable
    for _, bh, _, _, cbor in blocks[:2]:
        assert await chain_db.immutable_db.get_block(bh) == cbor

    # Block 3 should still be in volatile
    assert await chain_db.volatile_db.get_block(blocks[2][1]) is not None


# ---------------------------------------------------------------------------
# Test: empty ChainDB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_chaindb_tip_is_none(chain_db):
    """An empty ChainDB should return None for tip."""
    assert await chain_db.get_tip() is None


@pytest.mark.asyncio
async def test_empty_chaindb_get_block_returns_none(chain_db):
    """An empty ChainDB should return None for any block lookup."""
    assert await chain_db.get_block(make_hash(42)) is None


# ---------------------------------------------------------------------------
# Test: repr
# ---------------------------------------------------------------------------


def test_repr_empty(chain_db):
    """Repr of empty ChainDB should be informative."""
    r = repr(chain_db)
    assert "empty" in r
    assert "k=3" in r


@pytest.mark.asyncio
async def test_repr_with_blocks(chain_db):
    """Repr of ChainDB with blocks should show tip info."""
    await add_chain(chain_db, start_slot=1, count=2)
    r = repr(chain_db)
    assert "slot=2" in r
    assert "blockNo=2" in r


# ---------------------------------------------------------------------------
# Test: chain selection rejects fork beyond k
# test_chain_selection_rejects_fork_beyond_k
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_blocks_older_than_immutable_ignored(chain_db):
    """A fork with blocks older than the immutable tip is rejected.

    Spec: test_chain_selection_rejects_fork_beyond_k

    With k=3, after building a 7-block chain (immutable tip at blockNo=4),
    a competing fork starting at blockNo=1 should have its early blocks
    ignored because they're at or below the immutable tip.
    """
    await add_chain(chain_db, start_slot=1, count=7)
    # Immutable tip at blockNo=4

    # Try a competing fork from genesis with block_numbers 1-3
    # These should all be ignored (below immutable tip)
    for i in range(1, 4):
        fork_hash = make_hash(800 + i)
        await chain_db.add_block(
            slot=100 + i,
            block_hash=fork_hash,
            predecessor_hash=make_hash(800 + i - 1) if i > 1 else GENESIS_HASH,
            block_number=i,
            cbor_bytes=make_block_cbor(100 + i, i),
        )
        assert await chain_db.volatile_db.get_block(fork_hash) is None

    # Tip should still be the original chain
    tip = await chain_db.get_tip()
    assert tip is not None
    assert tip[0] == 7
