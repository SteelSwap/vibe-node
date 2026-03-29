"""Tests for ChainFollower with ChainDB-backed chain fragment."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.chainsync import ORIGIN, Point
from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB


def _hash(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _hdr(n: int) -> list:
    return [6, b"hdr" + n.to_bytes(4, "big")]


@pytest.fixture
def chain_db(tmp_path):
    vol = VolatileDB(db_dir=None)
    imm = ImmutableDB(base_dir=tmp_path / "imm")
    led = LedgerDB()
    return ChainDB(imm, vol, led, k=10)


class TestFollowerBasic:
    def test_new_follower_at_origin(self, chain_db):
        f = chain_db.new_follower()
        assert f.client_point is ORIGIN or f.client_point == ORIGIN
        assert f._pending_rollback is None

    def test_close_follower(self, chain_db):
        f = chain_db.new_follower()
        assert f.id in chain_db._followers
        chain_db.close_follower(f.id)
        assert f.id not in chain_db._followers

    def test_multiple_followers(self, chain_db):
        f1 = chain_db.new_follower()
        f2 = chain_db.new_follower()
        assert f1.id != f2.id
        assert len(chain_db._followers) == 2


class TestFollowerInstruction:
    @pytest.mark.asyncio
    async def test_await_on_empty(self, chain_db):
        f = chain_db.new_follower()
        action, _, _, _ = await asyncio.wait_for(f.instruction(), timeout=0.3)
        assert action == "await"

    @pytest.mark.asyncio
    async def test_roll_forward(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        action, header, point, tip = await f.instruction()
        assert action == "roll_forward"
        assert point == Point(slot=1, hash=_hash(1))
        assert header == _hdr(1)

    @pytest.mark.asyncio
    async def test_advances_through_chain(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        a1, _, p1, _ = await f.instruction()
        assert a1 == "roll_forward"
        assert p1 == Point(slot=1, hash=_hash(1))
        a2, _, p2, _ = await f.instruction()
        assert a2 == "roll_forward"
        assert p2 == Point(slot=2, hash=_hash(2))

    @pytest.mark.asyncio
    async def test_two_followers_independent(self, chain_db):
        f1 = chain_db.new_follower()
        f2 = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        a1, _, _, _ = await f1.instruction()
        a2, _, _, _ = await f1.instruction()
        assert a1 == "roll_forward"
        assert a2 == "roll_forward"
        b1, _, p1, _ = await f2.instruction()
        assert b1 == "roll_forward"
        assert p1 == Point(slot=1, hash=_hash(1))


class TestFollowerForkSwitch:
    @pytest.mark.asyncio
    async def test_rollback_on_fork(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        await f.instruction()  # block 1
        await f.instruction()  # block 2
        # Fork: 1 → 3 (better, block_number=3)
        await chain_db.add_block(
            slot=3,
            block_hash=_hash(3),
            predecessor_hash=_hash(1),
            block_number=3,
            cbor_bytes=b"b3",
            header_cbor=_hdr(3),
        )
        action, _, point, _ = await f.instruction()
        assert action == "roll_backward"
        assert point == Point(slot=1, hash=_hash(1))
        action2, _, point2, _ = await f.instruction()
        assert action2 == "roll_forward"
        assert point2 == Point(slot=3, hash=_hash(3))

    @pytest.mark.asyncio
    async def test_unaffected_follower_continues(self, chain_db):
        f_affected = chain_db.new_follower()
        f_safe = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        await f_affected.instruction()  # block 1
        await f_affected.instruction()  # block 2
        await f_safe.instruction()  # block 1 only
        await chain_db.add_block(
            slot=3,
            block_hash=_hash(3),
            predecessor_hash=_hash(1),
            block_number=3,
            cbor_bytes=b"b3",
            header_cbor=_hdr(3),
        )
        a_aff, _, _, _ = await f_affected.instruction()
        assert a_aff == "roll_backward"
        # All followers roll back on fork switch (prevents UnexpectedBlockNo)
        a_safe, _, _, _ = await f_safe.instruction()
        assert a_safe == "roll_backward"
        # After rollback, next instruction should serve the new chain
        a_safe2, _, p_safe2, _ = await f_safe.instruction()
        assert a_safe2 == "roll_forward"


class TestFollowerFindIntersect:
    @pytest.mark.asyncio
    async def test_intersect_with_known_point(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        await chain_db.add_block(
            slot=2,
            block_hash=_hash(2),
            predecessor_hash=_hash(1),
            block_number=2,
            cbor_bytes=b"b2",
            header_cbor=_hdr(2),
        )
        point, tip = await f.find_intersect(
            [
                Point(slot=2, hash=_hash(2)),
                Point(slot=1, hash=_hash(1)),
            ]
        )
        assert point == Point(slot=2, hash=_hash(2))
        assert f.client_point == Point(slot=2, hash=_hash(2))

    @pytest.mark.asyncio
    async def test_intersect_falls_back_to_origin(self, chain_db):
        f = chain_db.new_follower()
        await chain_db.add_block(
            slot=1,
            block_hash=_hash(1),
            predecessor_hash=_hash(0),
            block_number=1,
            cbor_bytes=b"b1",
            header_cbor=_hdr(1),
        )
        point, tip = await f.find_intersect(
            [
                Point(slot=99, hash=_hash(99)),
            ]
        )
        assert point is ORIGIN or point == ORIGIN
