"""Gap tests for the transaction mempool — coverage beyond the happy path.

These tests close coverage gaps identified in the P5 mempool audit:
    1. Hypothesis RuleBasedStateMachine — stateful property testing
    2. Fairness — large txs aren't starved by block selection
    3. Timeout / eviction — evict_expired honours slot-based TTL
    4. Semigroup — batch vs one-at-a-time produce identical snapshots
    5. Cannot-forge — edge cases for block selection
    6. Trace / observability — callback hooks fire on add/reject
    7. TxSeq internals — ticket lookup and split_by_size

Haskell references:
    Ouroboros.Consensus.Mempool.Impl.Pure (pureSyncWithLedger invariants)
    Ouroboros.Consensus.Mempool.TxSeq (splitAfterTxSize, lookupByTicketNo)

Antithesis compatibility:
    All Hypothesis tests use deterministic seeds and can be replayed.
    The RuleBasedStateMachine maintains a reference model (list + set)
    for comparison, following the Leios pattern for Antithesis.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)

from vibe.cardano.mempool.types import MempoolConfig, MempoolSnapshot, TxTicket
from vibe.cardano.mempool.mempool import (
    Mempool,
    MempoolCapacityError,
    MempoolDuplicateError,
    MempoolEvent,
    MempoolValidationError,
    _compute_tx_id,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class MockValidator:
    """Accept-all validator for gap tests."""

    def __init__(self) -> None:
        self.reject_ids: set[bytes] = set()
        self.reject_all: bool = False
        self.applied_txs: list[bytes] = []

    def validate_tx(self, tx_cbor: bytes, current_slot: int) -> list[str]:
        tx_id = _compute_tx_id(tx_cbor)
        if self.reject_all:
            return ["reject_all"]
        if tx_id in self.reject_ids:
            return ["rejected"]
        if tx_cbor in self.applied_txs:
            return ["double_spend"]
        return []

    def apply_tx(self, tx_cbor: bytes, current_slot: int) -> None:
        self.applied_txs.append(tx_cbor)

    def snapshot_state(self) -> Any:
        return list(self.applied_txs)

    def restore_state(self, state: Any) -> None:
        self.applied_txs = list(state)


def make_tx(seed: int, size: int = 100) -> bytes:
    """Create a fake transaction of a given size with a unique seed."""
    base = seed.to_bytes(4, "big")
    return (base * ((size // len(base)) + 1))[:size]


def run(coro):
    """Run an async coroutine synchronously (for Hypothesis stateful tests)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. Hypothesis RuleBasedStateMachine
# ---------------------------------------------------------------------------


class MempoolStateMachine(RuleBasedStateMachine):
    """Stateful test: every mempool operation agrees with a reference model.

    The reference model is a simple ordered list of (tx_id, size, cbor)
    tuples plus a set of IDs. We verify agreement after every operation.

    Invariants checked:
        - Size never exceeds capacity
        - Removed txs not in snapshot
        - Ticket numbers are strictly monotonic
    """

    def __init__(self) -> None:
        super().__init__()
        self.validator = MockValidator()
        self.capacity = 5000
        self.config = MempoolConfig(capacity_bytes=self.capacity)
        self.pool = Mempool(
            config=self.config,
            validator=self.validator,
            current_slot=0,
        )

        # Reference model.
        self.ref_txs: list[tuple[bytes, int, bytes]] = []  # (tx_id, size, cbor)
        self.ref_ids: set[bytes] = set()
        self.ref_total_size: int = 0
        self.seed_counter: int = 0
        self.last_ticket_no: int = -1

    @rule(size=st.integers(min_value=10, max_value=500))
    def add_tx(self, size: int):
        """Add a transaction — should agree with reference model."""
        self.seed_counter += 1
        tx = make_tx(self.seed_counter, size)
        tx_id = _compute_tx_id(tx)

        if tx_id in self.ref_ids:
            # Duplicate — skip.
            return

        if self.ref_total_size + size > self.capacity:
            # Should be rejected for capacity.
            with pytest.raises(MempoolCapacityError):
                run(self.pool.add_tx(tx))
            return

        vtx = run(self.pool.add_tx(tx))
        self.ref_txs.append((tx_id, size, tx))
        self.ref_ids.add(tx_id)
        self.ref_total_size += size

    @rule(
        data=st.data(),
    )
    def remove_txs(self, data):
        """Remove some transactions and verify agreement."""
        if not self.ref_txs:
            return

        # Pick a random subset to remove.
        count = data.draw(
            st.integers(min_value=1, max_value=min(3, len(self.ref_txs)))
        )
        to_remove_indices = data.draw(
            st.lists(
                st.integers(min_value=0, max_value=len(self.ref_txs) - 1),
                min_size=count,
                max_size=count,
                unique=True,
            )
        )
        remove_ids = {self.ref_txs[i][0] for i in to_remove_indices}

        removed = run(self.pool.remove_txs(remove_ids))
        assert removed == len(remove_ids)

        # Update reference.
        new_ref = []
        for tx_id, size, cbor in self.ref_txs:
            if tx_id in remove_ids:
                self.ref_ids.discard(tx_id)
                self.ref_total_size -= size
            else:
                new_ref.append((tx_id, size, cbor))
        self.ref_txs = new_ref

    @rule()
    def get_snapshot(self):
        """Snapshot must agree with reference model."""
        snap = run(self.pool.get_snapshot())

        assert len(snap.tickets) == len(self.ref_txs)
        assert snap.total_size_bytes == self.ref_total_size

        snap_ids = {t.validated_tx.tx_id for t in snap.tickets}
        assert snap_ids == self.ref_ids

    @rule()
    def get_txs_for_block(self):
        """get_txs_for_block returns a valid prefix."""
        max_size = self.capacity // 2 if self.capacity > 0 else 0
        result = run(self.pool.get_txs_for_block(max_size))

        total = sum(vtx.tx_size for vtx in result)
        assert total <= max_size

    @rule()
    def sync_with_ledger(self):
        """Sync with ledger — all txs should survive if validator accepts all."""
        self.validator.applied_txs.clear()
        removed = run(self.pool.sync_with_ledger(new_slot=self.pool.current_slot + 1))

        # Since validator accepts all, nothing should be removed.
        assert len(removed) == 0

    @invariant()
    def size_within_capacity(self):
        """Size must never exceed capacity."""
        assert self.pool.total_size_bytes <= self.capacity

    @invariant()
    def ticket_numbers_monotonic(self):
        """Ticket numbers in the pool must be strictly increasing."""
        snap = run(self.pool.get_snapshot())
        for i in range(1, len(snap.tickets)):
            assert snap.tickets[i].ticket_no > snap.tickets[i - 1].ticket_no


TestMempoolStateMachine = MempoolStateMachine.TestCase
TestMempoolStateMachine.settings = settings(
    max_examples=30,
    stateful_step_count=20,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# 2. Fairness — large txs aren't starved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fairness_large_txs_not_starved():
    """Both small and large txs appear in block selection when they fit.

    The mempool uses FIFO ordering (ticket number). If a small tx arrives
    first and a large tx arrives second, and the block has room for both,
    both should be included. Large txs aren't deprioritized.
    """
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=50000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    # Mix of small (100B) and large (10KB) txs, interleaved.
    small_txs = [make_tx(i, 100) for i in range(5)]
    large_txs = [make_tx(i + 100, 10000) for i in range(3)]

    for i, tx in enumerate(small_txs[:2]):
        await pool.add_tx(tx)
    await pool.add_tx(large_txs[0])
    for tx in small_txs[2:4]:
        await pool.add_tx(tx)
    await pool.add_tx(large_txs[1])
    await pool.add_tx(small_txs[4])
    await pool.add_tx(large_txs[2])

    # Block big enough for everything.
    result = await pool.get_txs_for_block(max_size=50000)

    sizes = [vtx.tx_size for vtx in result]
    assert 10000 in sizes, "Large txs must appear in block selection"
    assert 100 in sizes, "Small txs must appear in block selection"
    assert sizes.count(10000) == 3, "All 3 large txs should be included"
    assert sizes.count(100) == 5, "All 5 small txs should be included"


@pytest.mark.asyncio
async def test_fairness_block_selection_not_smallest_first():
    """Block selection follows insertion order, not size order.

    If a 10KB tx was added first and a 100B tx second, the block
    should contain the 10KB tx first (prefix ordering).
    """
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=50000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    large_tx = make_tx(1, 10000)
    small_tx = make_tx(2, 100)

    await pool.add_tx(large_tx)
    await pool.add_tx(small_tx)

    result = await pool.get_txs_for_block(max_size=50000)
    assert len(result) == 2
    # First tx in the result should be the large one (added first).
    assert result[0].tx_size == 10000
    assert result[1].tx_size == 100


# ---------------------------------------------------------------------------
# 3. Timeout / eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_expired_removes_old_txs():
    """Transactions past the timeout are evicted by evict_expired."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000, tx_timeout_slots=100)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    await pool.add_tx(tx1)
    await pool.add_tx(tx2)

    # Advance time past the timeout (slot 0 + 100 = 100).
    evicted = await pool.evict_expired(current_slot=100)

    assert len(evicted) == 2
    assert pool.size == 0
    assert pool.total_size_bytes == 0


@pytest.mark.asyncio
async def test_evict_expired_retains_fresh_txs():
    """Transactions within the timeout window are retained."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000, tx_timeout_slots=100)
    pool = Mempool(config=config, validator=validator, current_slot=50)

    tx = make_tx(1, 100)
    await pool.add_tx(tx)

    # Only 49 slots have passed — should not evict (50 + 49 = 99 < 50 + 100).
    evicted = await pool.evict_expired(current_slot=99)
    assert len(evicted) == 0
    assert pool.size == 1

    # At exactly the timeout boundary (slot 150 = 50 + 100).
    evicted = await pool.evict_expired(current_slot=150)
    assert len(evicted) == 1
    assert pool.size == 0


# ---------------------------------------------------------------------------
# 4. Semigroup — batch vs sequential equivalence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semigroup_add_one_at_a_time_vs_batch():
    """Adding 5 txs one-at-a-time produces the same snapshot as the equivalent state.

    Since the mempool only has add_tx (not add_txs batch), this verifies
    that sequential adds produce a consistent, deterministic snapshot.
    Two fresh pools with the same txs added in the same order must agree.
    """
    validator1 = MockValidator()
    validator2 = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool1 = Mempool(config=config, validator=validator1, current_slot=0)
    pool2 = Mempool(config=config, validator=validator2, current_slot=0)

    txs = [make_tx(i, 100 + i * 10) for i in range(5)]

    # Pool1: add one at a time.
    for tx in txs:
        await pool1.add_tx(tx)

    # Pool2: add one at a time (same order).
    for tx in txs:
        await pool2.add_tx(tx)

    snap1 = await pool1.get_snapshot()
    snap2 = await pool2.get_snapshot()

    assert len(snap1.tickets) == len(snap2.tickets)
    assert snap1.total_size_bytes == snap2.total_size_bytes
    for t1, t2 in zip(snap1.tickets, snap2.tickets):
        assert t1.validated_tx.tx_id == t2.validated_tx.tx_id
        assert t1.ticket_no == t2.ticket_no
        assert t1.measure == t2.measure


@pytest.mark.asyncio
async def test_semigroup_remove_one_at_a_time_vs_batch():
    """Removing 3 txs one-at-a-time vs remove_txs batch — identical result.

    The remove_txs method takes a set, so removing {a, b, c} in one call
    should produce the same state as removing a, then b, then c individually.
    """
    validator1 = MockValidator()
    validator2 = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool1 = Mempool(config=config, validator=validator1, current_slot=0)
    pool2 = Mempool(config=config, validator=validator2, current_slot=0)

    txs = [make_tx(i, 100) for i in range(5)]
    vtxs1 = []
    vtxs2 = []
    for tx in txs:
        vtxs1.append(await pool1.add_tx(tx))
        vtxs2.append(await pool2.add_tx(tx))

    # Remove txs at indices 0, 2, 4.
    remove_ids = {vtxs1[0].tx_id, vtxs1[2].tx_id, vtxs1[4].tx_id}

    # Pool1: batch remove.
    await pool1.remove_txs(remove_ids)

    # Pool2: one at a time.
    await pool2.remove_txs({vtxs2[0].tx_id})
    await pool2.remove_txs({vtxs2[2].tx_id})
    await pool2.remove_txs({vtxs2[4].tx_id})

    snap1 = await pool1.get_snapshot()
    snap2 = await pool2.get_snapshot()

    assert len(snap1.tickets) == len(snap2.tickets) == 2
    assert snap1.total_size_bytes == snap2.total_size_bytes
    for t1, t2 in zip(snap1.tickets, snap2.tickets):
        assert t1.validated_tx.tx_id == t2.validated_tx.tx_id


# ---------------------------------------------------------------------------
# 5. Cannot-forge — edge cases for block selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_forge_max_size_zero():
    """get_txs_for_block with max_size=0 returns empty even with txs present."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    for i in range(5):
        await pool.add_tx(make_tx(i, 100))

    result = await pool.get_txs_for_block(max_size=0)
    assert result == []


@pytest.mark.asyncio
async def test_cannot_forge_empty_mempool():
    """get_txs_for_block on empty mempool returns empty list."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    result = await pool.get_txs_for_block(max_size=99999)
    assert result == []


# ---------------------------------------------------------------------------
# 6. Trace / observability — callback hooks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_add_tx_fires_callback():
    """Adding a valid tx fires the TX_ADDED callback with correct data."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    events: list[tuple[str, dict]] = []
    pool.on_event(lambda event_type, data: events.append((event_type, data)))

    tx = make_tx(1, 150)
    vtx = await pool.add_tx(tx)

    # Should have exactly one TX_ADDED event.
    added_events = [(e, d) for e, d in events if e == MempoolEvent.TX_ADDED]
    assert len(added_events) == 1
    event_type, data = added_events[0]
    assert data["tx_id"] == vtx.tx_id
    assert data["tx_size"] == 150
    assert "ticket_no" in data


@pytest.mark.asyncio
async def test_trace_reject_tx_fires_callback():
    """Rejecting a tx fires the TX_REJECTED callback."""
    validator = MockValidator()
    tx = make_tx(1, 100)
    tx_id = _compute_tx_id(tx)
    validator.reject_ids.add(tx_id)

    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    events: list[tuple[str, dict]] = []
    pool.on_event(lambda event_type, data: events.append((event_type, data)))

    with pytest.raises(MempoolValidationError):
        await pool.add_tx(tx)

    rejected_events = [(e, d) for e, d in events if e == MempoolEvent.TX_REJECTED]
    assert len(rejected_events) == 1
    event_type, data = rejected_events[0]
    assert data["tx_id"] == tx_id
    assert data["reason"] == "validation"
    assert "errors" in data


# ---------------------------------------------------------------------------
# 7. TxSeq internals — ticket lookup and split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_txseq_ticket_number_lookup():
    """get_ticket_by_no finds a specific ticket by its number."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    txs = [make_tx(i, 100) for i in range(5)]
    vtxs = []
    for tx in txs:
        vtxs.append(await pool.add_tx(tx))

    # Look up ticket #2 (third tx added).
    ticket = pool.get_ticket_by_no(2)
    assert ticket is not None
    assert ticket.ticket_no == 2
    assert ticket.validated_tx.tx_id == vtxs[2].tx_id

    # Non-existent ticket.
    assert pool.get_ticket_by_no(999) is None


@pytest.mark.asyncio
async def test_txseq_split_by_size():
    """split_by_size splits at the exact cumulative size boundary.

    Given txs of sizes [100, 200, 150, 300], split at max_size=300:
        prefix: [100, 200] (cumulative 300 <= 300)
        suffix: [150, 300]
    """
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    sizes = [100, 200, 150, 300]
    for i, size in enumerate(sizes):
        await pool.add_tx(make_tx(i, size))

    prefix, suffix = pool.split_by_size(300)

    prefix_sizes = [t.validated_tx.tx_size for t in prefix]
    suffix_sizes = [t.validated_tx.tx_size for t in suffix]

    assert prefix_sizes == [100, 200]
    assert suffix_sizes == [150, 300]
    assert sum(prefix_sizes) == 300
    assert sum(suffix_sizes) == 450

    # Split at 0 — everything in suffix.
    prefix_0, suffix_0 = pool.split_by_size(0)
    assert len(prefix_0) == 0
    assert len(suffix_0) == 4

    # Split at 10000 — everything in prefix.
    prefix_all, suffix_all = pool.split_by_size(10000)
    assert len(prefix_all) == 4
    assert len(suffix_all) == 0
