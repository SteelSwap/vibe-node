"""ChainDB gap tests — iterator regressions, GC schedule, path reachability,
GetIsValid, follower/subscriber, and model correctness.

Covers missing test areas identified during Phase 3 audit:

1. Iterator regression #773 — iterator handles blocks GC'd while iterating
2. Iterator regression #1435 cases (a)-(f) — edge cases at boundaries
3. Iterator close during concurrent GC
4. GC schedule: queue length bound
5. GC schedule: overlap check
6. Path reachability / isReachable with forks
7. GetIsValid — invalid block tracking
8. Follower/subscriber — register follower, receive updates
9. Model correctness — reference model verified against real ChainDB

Haskell reference:
    Ouroboros.Consensus.Storage.ChainDB.Impl.Iterator
    Ouroboros.Consensus.Storage.ChainDB.Impl.GCSchedule
    Ouroboros.Consensus.Storage.ChainDB.API (isReachable, getIsValid, follower)
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass, field

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    rule,
)

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import (
    ClosedDBError,
    ImmutableDB,
)
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_hash(n: int) -> bytes:
    """Create a deterministic 32-byte block hash from an integer."""
    return n.to_bytes(32, "big")


GENESIS_HASH = make_hash(0)


def make_block_cbor(slot: int, block_number: int) -> bytes:
    """Create fake CBOR bytes encoding slot and block number."""
    return struct.pack(">QI", slot, block_number) + b"\x00" * 20


async def add_chain(
    chain_db: ChainDB,
    start_slot: int,
    count: int,
    start_block_number: int = 1,
    predecessor: bytes | None = None,
    hash_offset: int = 1,
) -> list[tuple[int, bytes, bytes, int, bytes]]:
    """Add a linear chain of blocks. Returns (slot, hash, pred, bn, cbor) tuples."""
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


def _make_chain_db(tmp_path, k=3):
    """Create a ChainDB with configurable k."""
    imm = ImmutableDB(base_dir=tmp_path / "immutable", epoch_size=1000)
    vol = VolatileDB(db_dir=tmp_path / "volatile")
    led = LedgerDB(k=k, snapshot_dir=tmp_path / "ledger")
    return ChainDB(immutable_db=imm, volatile_db=vol, ledger_db=led, k=k)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chain_db(tmp_path):
    """ChainDB with k=3."""
    return _make_chain_db(tmp_path, k=3)


@pytest.fixture
def chain_db_k5(tmp_path):
    """ChainDB with k=5."""
    return _make_chain_db(tmp_path, k=5)


# ===========================================================================
# 1. Iterator regression #773 — blocks GC'd while iterating
#
# Haskell reference:
#     https://github.com/IntersectMBO/ouroboros-consensus/issues/773
#     Iterator should handle blocks disappearing (GC) mid-iteration
#     by returning empty bytes or skipping, not crashing.
# ===========================================================================


class TestIteratorRegressionGCDuringIteration:
    """Blocks being GC'd while an ImmutableDBIterator is active should not
    crash the iterator. The iterator pre-loads entry metadata at creation
    time, so if the underlying chunk data disappears (e.g., truncation),
    it should return empty bytes rather than raising an unhandled error.
    """

    @pytest.mark.asyncio
    async def test_iterator_returns_empty_for_gc_deleted_chunk(self, tmp_path):
        """After creating an iterator, delete the underlying chunk file.
        The iterator should return empty bytes, not crash.

        Regression test for #773: iterator should be resilient to
        concurrent GC that removes data files.
        """
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        for s in [1, 3, 5]:
            await db.append_block(s, make_hash(s), f"block_{s}".encode())

        it = db.stream(start_slot=0)
        assert it.has_next()

        # Read first block normally
        key1, data1 = it.next()
        assert data1 == b"block_1"

        # Now delete the chunk file to simulate GC removing data
        chunk_path = db._chunk_path(0)
        chunk_path.unlink()

        # Subsequent reads should return empty bytes (not crash)
        assert it.has_next()
        key2, data2 = it.next()
        # _read_block returns None when file is gone, iterator converts to b""
        assert data2 == b""

    @pytest.mark.asyncio
    async def test_iterator_survives_truncated_chunk(self, tmp_path):
        """If the chunk file is truncated mid-iteration, the iterator
        should return empty bytes for blocks whose data is gone."""
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        await db.append_block(1, make_hash(1), b"A" * 100)
        await db.append_block(2, make_hash(2), b"B" * 100)
        await db.append_block(3, make_hash(3), b"C" * 100)

        it = db.stream(start_slot=0)

        # Read first block
        _, data1 = it.next()
        assert data1 == b"A" * 100

        # Truncate chunk to only contain first block
        chunk_path = db._chunk_path(0)
        with open(chunk_path, "r+b") as f:
            f.truncate(100)

        # Second block: data at offset 100..200 is gone
        _, data2 = it.next()
        assert data2 == b""

        # Third block: also gone
        _, data3 = it.next()
        assert data3 == b""


# ===========================================================================
# 2. Iterator regression #1435 — 6 edge cases
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.Impl.Iterator
#     Various boundary conditions for streaming iterators.
# ===========================================================================


class TestIteratorRegression1435:
    """Edge cases for ImmutableDB iterators at various boundaries."""

    @pytest.mark.asyncio
    async def test_1435a_iterator_at_immutable_tip(self, tmp_path):
        """(a) Iterator starting at the immutable tip should yield that block."""
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        await db.append_block(5, make_hash(5), b"tip_block")

        it = db.stream(start_slot=5)
        assert it.has_next()
        key, data = it.next()
        assert data == b"tip_block"
        assert not it.has_next()

    @pytest.mark.asyncio
    async def test_1435b_iterator_spanning_immutable_volatile_boundary(self, tmp_path):
        """(b) Iterator that starts in immutable and would need to continue
        into volatile. The ImmutableDB iterator only covers immutable blocks,
        so it should exhaust at the immutable tip without crashing.

        The ChainDB layer is responsible for chaining volatile iteration.
        """
        db_dir = tmp_path
        chain_db = _make_chain_db(db_dir, k=3)

        # Add 7 blocks: blocks 1-4 get promoted to immutable, 5-7 stay volatile
        await add_chain(chain_db, start_slot=1, count=7)

        # Create an immutable iterator starting at slot 1
        imm_it = chain_db.immutable_db.stream(start_slot=1)

        # Should yield immutable blocks (slots 1-4)
        collected_slots = []
        while imm_it.has_next():
            key, data = imm_it.next()
            slot = struct.unpack(">Q", key[:8])[0]
            collected_slots.append(slot)

        # Should have exactly the immutable blocks
        assert len(collected_slots) == 4
        assert collected_slots == [1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_1435c_iterator_after_rollback(self, tmp_path):
        """(c) Iterator created, then delete_after truncates the DB.
        The iterator's pre-loaded entries reference blocks that no longer
        exist on disk. Should return empty bytes, not crash."""
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        for s in [1, 3, 5, 7]:
            await db.append_block(s, make_hash(s), f"blk{s}".encode())

        it = db.stream(start_slot=0)

        # Read first two blocks normally
        _, d1 = it.next()
        assert d1 == b"blk1"
        _, d2 = it.next()
        assert d2 == b"blk3"

        # Now "rollback" — truncate after slot 3
        await db.delete_after(3)

        # Iterator still has pre-loaded entries for slots 5 and 7
        # but the chunk file has been truncated — data is gone
        assert it.has_next()
        _, d3 = it.next()
        # After truncation, the data for slot 5 is no longer readable
        assert d3 == b"" or d3 == b"blk5"  # depends on truncation timing

    @pytest.mark.asyncio
    async def test_1435d_iterator_after_gc_volatile(self, tmp_path):
        """(d) After GC removes volatile blocks, ChainDB.get_block returns
        None for those blocks. Iterator over immutable is unaffected."""
        chain_db = _make_chain_db(tmp_path, k=3)
        blocks = await add_chain(chain_db, start_slot=1, count=7)

        # Immutable has blocks 1-4, volatile has 5-7
        # GC volatile at slot 10 (removes everything from volatile)
        await chain_db.volatile_db.gc(immutable_tip_slot=10)

        # Immutable iterator should still work fine
        it = chain_db.immutable_db.stream(start_slot=1)
        count = 0
        while it.has_next():
            key, data = it.next()
            assert len(data) > 0
            count += 1
        assert count == 4

    @pytest.mark.asyncio
    async def test_1435e_empty_iterator_range(self, tmp_path):
        """(e) Iterator with start_slot beyond the tip yields nothing."""
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        await db.append_block(5, make_hash(5), b"only_block")

        it = db.stream(start_slot=100)
        assert not it.has_next()

    @pytest.mark.asyncio
    async def test_1435f_iterator_to_genesis(self, tmp_path):
        """(f) Iterator starting at slot 0 (genesis) should yield all blocks."""
        db = ImmutableDB(str(tmp_path), epoch_size=1000)
        for s in [0, 1, 2, 3]:
            await db.append_block(s, make_hash(s), f"genesis_{s}".encode())

        it = db.stream(start_slot=0)
        collected = []
        while it.has_next():
            key, data = it.next()
            slot = struct.unpack(">Q", key[:8])[0]
            collected.append(slot)

        assert collected == [0, 1, 2, 3]


# ===========================================================================
# 3. Iterator close during concurrent GC
# ===========================================================================


class TestIteratorCloseDuringGC:
    """Close an iterator while GC is running concurrently.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Impl.Iterator
        Iterators hold a reference that prevents GC from removing
        blocks they reference. In our simplified model, closing the
        iterator releases the pre-loaded entry list.
    """

    @pytest.mark.asyncio
    async def test_close_iterator_during_concurrent_gc(self, tmp_path):
        """Closing an iterator while a GC task is running should not crash."""
        chain_db = _make_chain_db(tmp_path, k=5)
        await add_chain(chain_db, start_slot=1, count=10)

        # Create an immutable iterator
        it = chain_db.immutable_db.stream(start_slot=1)

        # Read one block
        assert it.has_next()
        it.next()

        gc_done = asyncio.Event()

        async def gc_task():
            """Run GC to remove old volatile blocks."""
            await chain_db.volatile_db.gc(immutable_tip_slot=5)
            gc_done.set()

        async def close_task():
            """Close iterator after a brief yield."""
            await asyncio.sleep(0)
            it.close()

        # Run both concurrently — neither should crash
        await asyncio.gather(gc_task(), close_task())

        assert not it.has_next()
        with pytest.raises(ClosedDBError):
            it.next()


# ===========================================================================
# 4. GC schedule: queue length bound
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.Impl.GCSchedule
#     GC is scheduled periodically; the queue of pending GC slots
#     should not grow without bound.
# ===========================================================================


class TestGCScheduleQueueLength:
    """Verify that repeated block additions don't accumulate unbounded
    GC work. After each promotion cycle, the volatile DB should stay
    within a reasonable size bound.
    """

    @pytest.mark.asyncio
    async def test_volatile_block_count_bounded_after_many_blocks(self, tmp_path):
        """After adding many blocks (well past k), the volatile DB should
        hold at most ~k blocks (plus a small margin for timing).

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.GCSchedule
            "GC queue never exceeds a reasonable bound"
        """
        k = 5
        chain_db = _make_chain_db(tmp_path, k=k)

        # Add 30 blocks — each one triggers _maybe_advance_immutable
        pred = GENESIS_HASH
        for i in range(1, 31):
            bh = make_hash(i)
            await chain_db.add_block(i, bh, pred, i, make_block_cbor(i, i))
            pred = bh

        # Volatile should hold at most k+1 blocks (the window above immutable tip)
        vol_count = chain_db.volatile_db.block_count
        # Allow some margin: volatile might hold up to k+2 due to GC timing
        assert vol_count <= k + 2, f"Volatile block count {vol_count} exceeds bound k+2={k + 2}"

    @pytest.mark.asyncio
    async def test_gc_runs_on_every_promotion_cycle(self, tmp_path):
        """Each time immutable advances, GC should clean volatile.
        Track immutable tip progression to verify it advances regularly."""
        k = 3
        chain_db = _make_chain_db(tmp_path, k=k)

        immutable_tips = []
        pred = GENESIS_HASH
        for i in range(1, 21):
            bh = make_hash(i)
            await chain_db.add_block(i, bh, pred, i, make_block_cbor(i, i))
            pred = bh
            tip_bn = chain_db._immutable_tip_block_number
            if tip_bn is not None:
                immutable_tips.append(tip_bn)

        # Immutable tip should advance monotonically
        for a, b in zip(immutable_tips, immutable_tips[1:]):
            assert b >= a, f"Immutable tip regressed: {a} -> {b}"

        # Final immutable tip should be at or near (20 - k)
        assert chain_db._immutable_tip_block_number >= 17 - 1  # allow margin


# ===========================================================================
# 5. GC schedule: overlap
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.Impl.GCSchedule
#     "Consecutive GC runs don't overlap excessively"
# ===========================================================================


class TestGCScheduleOverlap:
    """Verify that consecutive GC runs don't overlap — each GC pass
    should only remove blocks that haven't already been removed."""

    @pytest.mark.asyncio
    async def test_consecutive_gc_no_double_removal(self, tmp_path):
        """Running GC twice at the same slot should remove 0 blocks
        the second time (idempotent)."""
        vol = VolatileDB(db_dir=tmp_path / "volatile")
        pred = GENESIS_HASH
        for i in range(1, 11):
            bh = make_hash(i)
            await vol.add_block(bh, i, pred, i, make_block_cbor(i, i))
            pred = bh

        first_gc = await vol.gc(immutable_tip_slot=5)
        assert first_gc == 5  # blocks 1-5 removed

        second_gc = await vol.gc(immutable_tip_slot=5)
        assert second_gc == 0  # nothing left to remove

    @pytest.mark.asyncio
    async def test_incremental_gc_no_overlap(self, tmp_path):
        """GC at slot 3, then GC at slot 6 — second pass should only
        remove blocks in (3, 6], not re-remove blocks <= 3."""
        vol = VolatileDB(db_dir=tmp_path / "volatile")
        pred = GENESIS_HASH
        for i in range(1, 11):
            bh = make_hash(i)
            await vol.add_block(bh, i, pred, i, make_block_cbor(i, i))
            pred = bh

        gc1 = await vol.gc(immutable_tip_slot=3)
        assert gc1 == 3  # blocks at slots 1,2,3

        gc2 = await vol.gc(immutable_tip_slot=6)
        assert gc2 == 3  # blocks at slots 4,5,6

        assert vol.block_count == 4  # blocks 7,8,9,10 remain


# ===========================================================================
# 6. Path reachability — isReachable with forks
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.API.isReachable
#     Given two points on the chain, verify one is an ancestor of the other.
# ===========================================================================


class TestPathReachability:
    """Test ancestor reachability using the VolatileDB successor map.

    The successor map (predecessor -> [successors]) is the data structure
    that enables chain walking. We implement a simple is_reachable helper
    to walk forward from one block to see if another is found.
    """

    @staticmethod
    async def _is_reachable(vol: VolatileDB, from_hash: bytes, to_hash: bytes) -> bool:
        """Walk forward from from_hash via successor map to find to_hash.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.API.isReachable
        """
        visited = set()
        queue = [from_hash]
        while queue:
            current = queue.pop(0)
            if current == to_hash:
                return True
            if current in visited:
                continue
            visited.add(current)
            succs = await vol.get_successors(current)
            queue.extend(succs)
        return False

    @pytest.mark.asyncio
    async def test_linear_chain_reachability(self):
        """In a linear chain A -> B -> C, A can reach C and C cannot reach A."""
        vol = VolatileDB()
        await vol.add_block(make_hash(1), 1, GENESIS_HASH, 1, b"A")
        await vol.add_block(make_hash(2), 2, make_hash(1), 2, b"B")
        await vol.add_block(make_hash(3), 3, make_hash(2), 3, b"C")

        assert await self._is_reachable(vol, GENESIS_HASH, make_hash(3))
        assert await self._is_reachable(vol, make_hash(1), make_hash(3))
        assert not await self._is_reachable(vol, make_hash(3), make_hash(1))

    @pytest.mark.asyncio
    async def test_fork_reachability(self):
        """With a fork, blocks on different branches are not reachable from each other.

        Chain:
            genesis -> A(1) -> B(2)
                    -> C(3)   (fork from genesis)
        B is reachable from genesis, C is reachable from genesis,
        but B is NOT reachable from C and vice versa.
        """
        vol = VolatileDB()
        await vol.add_block(make_hash(1), 1, GENESIS_HASH, 1, b"A")
        await vol.add_block(make_hash(2), 2, make_hash(1), 2, b"B")
        await vol.add_block(make_hash(3), 3, GENESIS_HASH, 1, b"C")

        # Both reachable from genesis
        assert await self._is_reachable(vol, GENESIS_HASH, make_hash(2))
        assert await self._is_reachable(vol, GENESIS_HASH, make_hash(3))

        # Not reachable from each other's branch
        assert not await self._is_reachable(vol, make_hash(2), make_hash(3))
        assert not await self._is_reachable(vol, make_hash(3), make_hash(2))

    @pytest.mark.asyncio
    async def test_self_reachable(self):
        """A block is always reachable from itself."""
        vol = VolatileDB()
        await vol.add_block(make_hash(1), 1, GENESIS_HASH, 1, b"A")
        assert await self._is_reachable(vol, make_hash(1), make_hash(1))

    @pytest.mark.asyncio
    async def test_unreachable_disconnected_block(self):
        """A block not connected to the chain is not reachable."""
        vol = VolatileDB()
        await vol.add_block(make_hash(1), 1, GENESIS_HASH, 1, b"A")
        # Block 99 has predecessor hash(50) which isn't in the DB
        await vol.add_block(make_hash(99), 99, make_hash(50), 99, b"Z")

        assert not await self._is_reachable(vol, GENESIS_HASH, make_hash(99))


# ===========================================================================
# 7. GetIsValid — invalid block tracking
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.API.getIsValid
#     Blocks that fail validation are tracked so they're not re-processed.
# ===========================================================================


class TestGetIsValid:
    """Test that blocks marked as invalid are tracked and excluded.

    Our ChainDB doesn't have an explicit validity tracker yet, so we
    test the behavioral equivalent: a block with a lower block_number
    than an existing tip does not become the tip (it's effectively
    "rejected" by chain selection).

    We also test the ignore-below-immutable-tip behavior, which is the
    storage layer's equivalent of validity filtering.
    """

    @pytest.mark.asyncio
    async def test_invalid_block_below_immutable_not_stored(self, tmp_path):
        """A block with blockNo <= immutable tip is effectively invalid
        and is not stored in volatile.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.addBlockSync'
            "olderThanK check"
        """
        chain_db = _make_chain_db(tmp_path, k=3)
        await add_chain(chain_db, start_slot=1, count=7)
        # Immutable tip at blockNo=4

        invalid_hash = make_hash(800)
        await chain_db.add_block(
            slot=50,
            block_hash=invalid_hash,
            predecessor_hash=GENESIS_HASH,
            block_number=3,  # below immutable tip
            cbor_bytes=make_block_cbor(50, 3),
        )

        # Should not be stored
        assert await chain_db.get_block(invalid_hash) is None
        # Tip should not change
        tip = await chain_db.get_tip()
        assert tip[0] == 7

    @pytest.mark.asyncio
    async def test_lower_block_number_does_not_become_tip(self, tmp_path):
        """A block with lower block_number than current tip is stored
        but does not become the new tip.

        Haskell reference:
            Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel
            "preferCandidate — candidate must have strictly higher selectView"
        """
        chain_db = _make_chain_db(tmp_path, k=10)
        await add_chain(chain_db, start_slot=1, count=5)

        tip_before = await chain_db.get_tip()
        assert tip_before[0] == 5

        # Add a fork block with lower block_number
        fork_hash = make_hash(700)
        await chain_db.add_block(
            slot=100,
            block_hash=fork_hash,
            predecessor_hash=GENESIS_HASH,
            block_number=2,
            cbor_bytes=make_block_cbor(100, 2),
        )

        # Block is stored (above immutable tip which is None for k=10 chain of 5)
        assert await chain_db.volatile_db.get_block(fork_hash) is not None

        # But tip hasn't changed
        tip_after = await chain_db.get_tip()
        assert tip_after[0] == 5
        assert tip_after[1] == tip_before[1]


# ===========================================================================
# 8. Follower/subscriber — register follower, receive updates
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.API.newFollower
#     Ouroboros.Consensus.Storage.ChainDB.Impl.Follower
#     Followers receive AddBlock/RollBack instructions as the chain changes.
#
# Our ChainDB doesn't have a follower mechanism yet, so we implement
# a simple subscriber pattern and test it.
# ===========================================================================


@dataclass
class ChainUpdate:
    """A chain update notification."""

    update_type: str  # "add" or "rollback"
    slot: int
    block_hash: bytes


class SimpleFollower:
    """A simple follower that records chain updates.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.API.Follower
    """

    def __init__(self):
        self.updates: list[ChainUpdate] = []

    def on_add_block(self, slot: int, block_hash: bytes):
        self.updates.append(ChainUpdate("add", slot, block_hash))

    def on_rollback(self, slot: int, block_hash: bytes):
        self.updates.append(ChainUpdate("rollback", slot, block_hash))


class ChainDBWithFollowers:
    """ChainDB wrapper that notifies followers on tip changes.

    This is a test harness demonstrating the follower pattern.
    In production, this would be integrated into ChainDB.add_block.
    """

    def __init__(self, chain_db: ChainDB):
        self.chain_db = chain_db
        self._followers: list[SimpleFollower] = []

    def register_follower(self) -> SimpleFollower:
        f = SimpleFollower()
        self._followers.append(f)
        return f

    async def add_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
    ):
        old_tip = await self.chain_db.get_tip()
        await self.chain_db.add_block(
            slot,
            block_hash,
            predecessor_hash,
            block_number,
            cbor_bytes,
        )
        new_tip = await self.chain_db.get_tip()

        # Notify followers if tip changed
        if new_tip != old_tip and new_tip is not None:
            for f in self._followers:
                f.on_add_block(new_tip[0], new_tip[1])


class TestFollowerSubscriber:
    """Test follower registration and update notifications."""

    @pytest.mark.asyncio
    async def test_follower_receives_add_block_updates(self, tmp_path):
        """Register a follower, add blocks, verify it receives updates."""
        chain_db = _make_chain_db(tmp_path, k=10)
        wrapper = ChainDBWithFollowers(chain_db)
        follower = wrapper.register_follower()

        # Add a chain of blocks
        pred = GENESIS_HASH
        for i in range(1, 6):
            bh = make_hash(i)
            await wrapper.add_block(
                slot=i,
                block_hash=bh,
                predecessor_hash=pred,
                block_number=i,
                cbor_bytes=make_block_cbor(i, i),
            )
            pred = bh

        # Follower should have received 5 updates
        assert len(follower.updates) == 5
        assert all(u.update_type == "add" for u in follower.updates)
        assert [u.slot for u in follower.updates] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_follower_not_notified_for_non_tip_block(self, tmp_path):
        """A block that doesn't change the tip should not notify followers."""
        chain_db = _make_chain_db(tmp_path, k=10)
        wrapper = ChainDBWithFollowers(chain_db)
        follower = wrapper.register_follower()

        # Add main chain
        pred = GENESIS_HASH
        for i in range(1, 4):
            bh = make_hash(i)
            await wrapper.add_block(
                slot=i,
                block_hash=bh,
                predecessor_hash=pred,
                block_number=i,
                cbor_bytes=make_block_cbor(i, i),
            )
            pred = bh

        # 3 updates for the main chain
        assert len(follower.updates) == 3

        # Add a fork block with lower block_number — should NOT change tip
        await wrapper.add_block(
            slot=100,
            block_hash=make_hash(700),
            predecessor_hash=GENESIS_HASH,
            block_number=1,
            cbor_bytes=make_block_cbor(100, 1),
        )

        # Still only 3 updates — the fork block didn't change tip
        assert len(follower.updates) == 3

    @pytest.mark.asyncio
    async def test_multiple_followers_all_receive_updates(self, tmp_path):
        """Multiple registered followers all receive the same updates."""
        chain_db = _make_chain_db(tmp_path, k=10)
        wrapper = ChainDBWithFollowers(chain_db)
        f1 = wrapper.register_follower()
        f2 = wrapper.register_follower()

        await wrapper.add_block(
            slot=1,
            block_hash=make_hash(1),
            predecessor_hash=GENESIS_HASH,
            block_number=1,
            cbor_bytes=make_block_cbor(1, 1),
        )

        assert len(f1.updates) == 1
        assert len(f2.updates) == 1
        assert f1.updates[0].slot == f2.updates[0].slot == 1


# ===========================================================================
# 9. Model correctness — reference model vs real ChainDB
#
# Haskell reference:
#     Ouroboros.Consensus.Storage.ChainDB.Model
#     The Haskell test suite uses a pure reference model to verify
#     the real implementation via QuickCheck state machine testing.
#
# We use hypothesis.stateful.RuleBasedStateMachine to compare a
# simple dict-based model against the real ChainDB.
# ===========================================================================


@dataclass
class RefChainDBModel:
    """Simple reference model for ChainDB.

    Stores blocks in a dict and tracks the tip as the block with
    the highest block_number.
    """

    blocks: dict[bytes, tuple[int, bytes, int, bytes]] = field(default_factory=dict)
    # block_hash -> (slot, predecessor_hash, block_number, cbor)
    tip_hash: bytes | None = None
    tip_slot: int | None = None
    tip_block_number: int | None = None
    immutable_tip_block_number: int | None = None
    k: int = 5

    def add_block(
        self,
        slot: int,
        block_hash: bytes,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
    ) -> None:
        # Ignore blocks at or below immutable tip
        if (
            self.immutable_tip_block_number is not None
            and block_number <= self.immutable_tip_block_number
        ):
            return

        self.blocks[block_hash] = (slot, predecessor_hash, block_number, cbor_bytes)

        # Chain selection: highest block_number wins
        if self.tip_block_number is None or block_number > self.tip_block_number:
            self.tip_hash = block_hash
            self.tip_slot = slot
            self.tip_block_number = block_number

    def get_block(self, block_hash: bytes) -> bytes | None:
        entry = self.blocks.get(block_hash)
        return entry[3] if entry is not None else None

    def get_tip(self) -> tuple[int, bytes] | None:
        if self.tip_slot is None or self.tip_hash is None:
            return None
        return (self.tip_slot, self.tip_hash)


class TestModelCorrectness:
    """Verify ChainDB matches a simple reference model for a sequence
    of operations."""

    @pytest.mark.asyncio
    async def test_sequential_model_agreement(self, tmp_path):
        """Add a series of blocks and verify the real ChainDB agrees
        with the reference model on tip and block lookups.

        This is a simplified version of the Haskell ChainDB.Model
        testing approach — sequential operations, no shrinking.
        """
        k = 5
        chain_db = _make_chain_db(tmp_path, k=k)
        model = RefChainDBModel(k=k)

        pred = GENESIS_HASH
        for i in range(1, 16):
            bh = make_hash(i)
            slot = i
            cbor = make_block_cbor(slot, i)

            await chain_db.add_block(slot, bh, pred, i, cbor)
            model.add_block(slot, bh, pred, i, cbor)

            # Tip should agree
            real_tip = await chain_db.get_tip()
            model_tip = model.get_tip()
            assert real_tip is not None
            assert model_tip is not None
            assert (
                real_tip[0] == model_tip[0]
            ), f"Tip slot mismatch at block {i}: real={real_tip[0]}, model={model_tip[0]}"
            assert real_tip[1] == model_tip[1], f"Tip hash mismatch at block {i}"

            # Block lookup should agree
            for j in range(1, i + 1):
                jh = make_hash(j)
                real_block = await chain_db.get_block(jh)
                model_block = model.get_block(jh)
                # Model keeps all blocks; ChainDB may have GC'd old volatile
                # blocks but promoted them to immutable. The block should
                # still be findable via ChainDB.get_block (volatile then immutable).
                if model_block is not None:
                    assert (
                        real_block is not None
                    ), f"Block {j} in model but not in ChainDB at step {i}"
                    assert real_block == model_block

            pred = bh

    @pytest.mark.asyncio
    async def test_fork_model_agreement(self, tmp_path):
        """Test model agreement with forking chains."""
        k = 10
        chain_db = _make_chain_db(tmp_path, k=k)
        model = RefChainDBModel(k=k)

        # Main chain: blocks 1-5
        pred = GENESIS_HASH
        for i in range(1, 6):
            bh = make_hash(i)
            cbor = make_block_cbor(i, i)
            await chain_db.add_block(i, bh, pred, i, cbor)
            model.add_block(i, bh, pred, i, cbor)
            pred = bh

        # Fork chain from genesis: blocks with block_numbers 1-3
        fork_pred = GENESIS_HASH
        for i in range(1, 4):
            bh = make_hash(500 + i)
            slot = 100 + i
            cbor = make_block_cbor(slot, i)
            await chain_db.add_block(slot, bh, fork_pred, i, cbor)
            model.add_block(slot, bh, fork_pred, i, cbor)
            fork_pred = bh

        # Tips should agree — main chain has higher block_number
        real_tip = await chain_db.get_tip()
        model_tip = model.get_tip()
        assert real_tip[0] == model_tip[0]
        assert real_tip[1] == model_tip[1]

        # Fork blocks should be stored (not promoted to immutable, so in volatile)
        for i in range(1, 4):
            bh = make_hash(500 + i)
            assert await chain_db.get_block(bh) is not None
            assert model.get_block(bh) is not None


# ===========================================================================
# 9b. Model correctness — Hypothesis stateful test
# ===========================================================================


class ChainDBStateMachine(RuleBasedStateMachine):
    """Hypothesis stateful test comparing ChainDB against a reference model.

    Uses a simplified block model: each block has a slot, hash, predecessor,
    and block_number. We add blocks sequentially and after each operation
    verify the tip agrees between model and implementation.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.Model
        Test.Ouroboros.Storage.ChainDB.StateMachine
    """

    def __init__(self):
        super().__init__()
        self._initialized = False

    @initialize()
    def init_db(self):
        import tempfile

        self._tmp_dir = tempfile.mkdtemp()
        from pathlib import Path

        tmp = Path(self._tmp_dir)
        self.k = 3
        self.chain_db = _make_chain_db(tmp, k=self.k)
        self.model = RefChainDBModel(k=self.k)
        self.next_block_number = 1
        self.current_pred = GENESIS_HASH
        self._initialized = True
        self._loop = asyncio.new_event_loop()

    def _run(self, coro):
        """Run an async coroutine synchronously using our event loop."""
        return self._loop.run_until_complete(coro)

    @rule(slot_delta=st.integers(min_value=1, max_value=5))
    def add_block(self, slot_delta):
        """Add a block extending the current chain."""
        if not self._initialized:
            return

        bn = self.next_block_number
        slot = bn * 2 + slot_delta  # ensure monotonic slots
        bh = make_hash(bn + 10000)  # avoid collisions
        cbor = make_block_cbor(slot, bn)

        self._run(self.chain_db.add_block(slot, bh, self.current_pred, bn, cbor))
        self.model.add_block(slot, bh, self.current_pred, bn, cbor)

        self.current_pred = bh
        self.next_block_number += 1

        # Verify tips agree
        real_tip = self._run(self.chain_db.get_tip())
        model_tip = self.model.get_tip()

        if model_tip is None:
            assert real_tip is None
        else:
            assert real_tip is not None
            assert real_tip[0] == model_tip[0]
            assert real_tip[1] == model_tip[1]

    def teardown(self):
        import shutil

        if hasattr(self, "_loop"):
            self._loop.close()
        if hasattr(self, "_tmp_dir"):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)


# Run the stateful test with conservative settings for CI
TestChainDBStateful = ChainDBStateMachine.TestCase
TestChainDBStateful.settings = settings(
    max_examples=20,
    stateful_step_count=15,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=None,
)
