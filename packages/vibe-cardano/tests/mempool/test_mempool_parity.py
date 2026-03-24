"""Haskell test parity — mempool edge cases and invariants.

This module covers mempool behaviors that the Haskell node tests exercise
but our existing tests do not:

    1.  Capacity enforcement edge cases (1-byte over, exactly at boundary)
    2.  Eviction under pressure (remove frees space, then add succeeds)
    3.  Re-validation on rollback (partial and cascading invalidation)
    4.  Tx ordering by fee proxy (insertion order == ticket order)
    5.  Concurrent add/remove/snapshot consistency
    6.  Snapshot isolation (mutations after snapshot are invisible)
    7.  Re-validation preserves ticket order of surviving txs
    8.  Capacity reclaimed after sync_with_ledger removes txs
    9.  Double sync_with_ledger is idempotent when nothing changes
    10. Evict_expired with no timeout configured is a no-op
    11. Remove all txs then re-add fills from scratch
    12. Available_bytes property tracks correctly through lifecycle

Haskell references:
    Test.Consensus.Mempool.Fairness
    Test.Consensus.Mempool.StateMachine
    Ouroboros.Consensus.Mempool.Impl.Pure (pureSyncWithLedger invariants)
    Ouroboros.Consensus.Mempool.TxSeq (capacity, ordering invariants)

Spec reference:
    Ouroboros consensus spec — mempool as pure function from
    (ledger state, tx) -> (ledger state', [error])
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vibe.cardano.mempool.mempool import (
    Mempool,
    MempoolCapacityError,
    MempoolDuplicateError,
    MempoolEvent,
    MempoolValidationError,
    _compute_tx_id,
)
from vibe.cardano.mempool.types import MempoolConfig

# ---------------------------------------------------------------------------
# Mock validator with configurable rejection
# ---------------------------------------------------------------------------


class _MockValidator:
    """Configurable mock validator for parity tests.

    Supports:
    - Per-ID rejection (reject_ids)
    - Per-slot rejection (reject_after_slot — all txs fail if slot > threshold)
    - Applied tx tracking for state save/restore
    """

    def __init__(self) -> None:
        self.reject_ids: set[bytes] = set()
        self.reject_all: bool = False
        self.reject_after_slot: int | None = None
        self.applied_txs: list[bytes] = []

    def validate_tx(self, tx_cbor: bytes, current_slot: int) -> list[str]:
        tx_id = _compute_tx_id(tx_cbor)
        if self.reject_all:
            return ["reject_all"]
        if self.reject_after_slot is not None and current_slot > self.reject_after_slot:
            return [f"expired at slot {current_slot}"]
        if tx_id in self.reject_ids:
            return ["rejected_by_id"]
        return []

    def apply_tx(self, tx_cbor: bytes, current_slot: int) -> None:
        self.applied_txs.append(tx_cbor)

    def snapshot_state(self) -> Any:
        return list(self.applied_txs)

    def restore_state(self, state: Any) -> None:
        self.applied_txs = list(state)


def _make_tx(seed: int, size: int = 100) -> bytes:
    """Create a fake transaction of a given size with a unique seed."""
    base = seed.to_bytes(4, "big")
    return (base * ((size // len(base)) + 1))[:size]


# ---------------------------------------------------------------------------
# 1. Capacity enforcement edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_one_byte_over():
    """Reject a tx that exceeds capacity by exactly 1 byte.

    Haskell ref: implTryAddTx checks (txsSize + txSize > capacity).
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=200), validator=v, current_slot=0)

    await pool.add_tx(_make_tx(1, 100))
    # 100 in pool, capacity 200, try to add 101 -> total 201 > 200
    with pytest.raises(MempoolCapacityError) as exc:
        await pool.add_tx(_make_tx(2, 101))
    assert exc.value.needed == 101
    assert exc.value.available == 100


@pytest.mark.asyncio
async def test_capacity_single_tx_exactly_fills():
    """A single tx whose size == capacity is accepted into an empty pool."""
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=500), validator=v, current_slot=0)

    vtx = await pool.add_tx(_make_tx(1, 500))
    assert pool.total_size_bytes == 500
    assert pool.available_bytes == 0

    # Next add must fail.
    with pytest.raises(MempoolCapacityError):
        await pool.add_tx(_make_tx(2, 1))


@pytest.mark.asyncio
async def test_capacity_single_tx_too_large_for_empty_pool():
    """A single tx larger than capacity is rejected even in empty pool."""
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=100), validator=v, current_slot=0)

    with pytest.raises(MempoolCapacityError) as exc:
        await pool.add_tx(_make_tx(1, 101))
    assert exc.value.capacity == 100
    assert exc.value.available == 100
    assert exc.value.needed == 101


# ---------------------------------------------------------------------------
# 2. Eviction under pressure (remove frees space, then add succeeds)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_eviction_frees_capacity_for_new_tx():
    """After removing a tx, a previously rejected tx can be added.

    Haskell ref: implRemoveTxs frees capacity; subsequent implTryAddTx
    can succeed where it previously would have failed.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=300), validator=v, current_slot=0)

    vtx1 = await pool.add_tx(_make_tx(1, 200))
    # Can't add 200 more (total would be 400 > 300)
    with pytest.raises(MempoolCapacityError):
        await pool.add_tx(_make_tx(2, 200))

    # Remove tx1, freeing 200 bytes.
    await pool.remove_txs({vtx1.tx_id})
    assert pool.total_size_bytes == 0

    # Now the 200-byte tx fits.
    vtx2 = await pool.add_tx(_make_tx(2, 200))
    assert pool.size == 1
    assert pool.total_size_bytes == 200


@pytest.mark.asyncio
async def test_expired_eviction_frees_capacity():
    """evict_expired frees capacity, allowing new txs to be added."""
    v = _MockValidator()
    config = MempoolConfig(capacity_bytes=300, tx_timeout_slots=50)
    pool = Mempool(config=config, validator=v, current_slot=0)

    await pool.add_tx(_make_tx(1, 200))
    assert pool.available_bytes == 100

    # Advance and evict.
    evicted = await pool.evict_expired(current_slot=50)
    assert len(evicted) == 1
    assert pool.available_bytes == 300

    # Now a 250-byte tx fits.
    await pool.add_tx(_make_tx(2, 250))
    assert pool.total_size_bytes == 250


# ---------------------------------------------------------------------------
# 3. Re-validation on rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revalidation_partial_invalidation():
    """sync_with_ledger removes only the txs that fail re-validation.

    Haskell ref: pureSyncWithLedger re-validates each tx in order,
    removing failures but keeping valid ones.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    txs = [_make_tx(i, 100) for i in range(5)]
    vtxs = [await pool.add_tx(tx) for tx in txs]

    # Invalidate txs at index 1 and 3.
    v.reject_ids.add(vtxs[1].tx_id)
    v.reject_ids.add(vtxs[3].tx_id)
    v.applied_txs.clear()

    removed = await pool.sync_with_ledger(new_slot=10)
    assert set(removed) == {vtxs[1].tx_id, vtxs[3].tx_id}
    assert pool.size == 3

    snap = await pool.get_snapshot()
    snap_ids = [t.validated_tx.tx_id for t in snap.tickets]
    assert snap_ids == [vtxs[0].tx_id, vtxs[2].tx_id, vtxs[4].tx_id]


@pytest.mark.asyncio
async def test_revalidation_cascading_all_removed():
    """When all txs become invalid on rollback, pool empties cleanly.

    Haskell ref: pureSyncWithLedger can produce an empty mempool.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    for i in range(10):
        await pool.add_tx(_make_tx(i, 50))
    assert pool.size == 10

    v.reject_all = True
    v.applied_txs.clear()

    removed = await pool.sync_with_ledger(new_slot=100)
    assert len(removed) == 10
    assert pool.size == 0
    assert pool.total_size_bytes == 0


@pytest.mark.asyncio
async def test_revalidation_preserves_ticket_order():
    """Surviving txs after re-validation keep their original ticket order.

    Haskell ref: pureSyncWithLedger preserves the order of remaining
    TxTickets — they are not re-numbered.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    txs = [_make_tx(i, 100) for i in range(5)]
    vtxs = [await pool.add_tx(tx) for tx in txs]

    # Remove tx at index 2.
    v.reject_ids.add(vtxs[2].tx_id)
    v.applied_txs.clear()

    await pool.sync_with_ledger(new_slot=5)

    snap = await pool.get_snapshot()
    ticket_nos = [t.ticket_no for t in snap.tickets]
    # Original tickets: 0,1,2,3,4 -> surviving: 0,1,3,4
    assert ticket_nos == [0, 1, 3, 4]
    # Strictly increasing.
    for i in range(1, len(ticket_nos)):
        assert ticket_nos[i] > ticket_nos[i - 1]


# ---------------------------------------------------------------------------
# 4. Tx ordering follows insertion (FIFO), not fee
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insertion_order_determines_block_selection():
    """Block selection returns txs in insertion order regardless of size.

    Haskell ref: Mempool is a FIFO queue (TxSeq). The block forger
    takes a prefix, not a fee-sorted selection.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=50000), validator=v, current_slot=0)

    # Add txs of varying sizes in a specific order.
    sizes = [500, 100, 300, 50, 400]
    vtxs = []
    for i, size in enumerate(sizes):
        vtxs.append(await pool.add_tx(_make_tx(i, size)))

    result = await pool.get_txs_for_block(max_size=50000)
    result_sizes = [vtx.tx_size for vtx in result]
    assert result_sizes == sizes, "Block selection must follow insertion order"


# ---------------------------------------------------------------------------
# 5. Concurrent add/remove/snapshot consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_add_remove_snapshot_consistency():
    """Concurrent adds, removes, and snapshots produce consistent state.

    The lock ensures that at any point, the snapshot agrees with the
    internal counters.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=100000), validator=v, current_slot=0)

    # Pre-populate.
    pre_vtxs = [await pool.add_tx(_make_tx(i, 100)) for i in range(20)]

    errors: list[str] = []

    async def add_task(seed: int) -> None:
        try:
            await pool.add_tx(_make_tx(seed, 100))
        except MempoolCapacityError, MempoolDuplicateError:
            pass

    async def remove_task(tx_id: bytes) -> None:
        await pool.remove_txs({tx_id})

    async def snapshot_task() -> None:
        snap = await pool.get_snapshot()
        # Snapshot internal consistency: total_size == sum of tx sizes.
        computed = sum(t.validated_tx.tx_size for t in snap.tickets)
        if computed != snap.total_size_bytes:
            errors.append(
                f"Snapshot inconsistency: computed={computed} vs reported={snap.total_size_bytes}"
            )

    tasks = []
    for i in range(20):
        tasks.append(add_task(100 + i))
    for vtx in pre_vtxs[:10]:
        tasks.append(remove_task(vtx.tx_id))
    for _ in range(5):
        tasks.append(snapshot_task())

    await asyncio.gather(*tasks)
    assert errors == [], f"Consistency errors: {errors}"


# ---------------------------------------------------------------------------
# 6. Snapshot isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_isolation():
    """Mutations after snapshot do not affect the snapshot.

    Haskell ref: getSnapshot returns a frozen MempoolSnapshot.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    vtx1 = await pool.add_tx(_make_tx(1, 100))
    vtx2 = await pool.add_tx(_make_tx(2, 200))

    # Take snapshot.
    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 2
    assert snap.total_size_bytes == 300

    # Mutate the pool.
    await pool.remove_txs({vtx1.tx_id})
    await pool.add_tx(_make_tx(3, 150))

    # Snapshot is unchanged.
    assert len(snap.tickets) == 2
    assert snap.total_size_bytes == 300
    snap_ids = {t.validated_tx.tx_id for t in snap.tickets}
    assert vtx1.tx_id in snap_ids
    assert vtx2.tx_id in snap_ids


# ---------------------------------------------------------------------------
# 7. Capacity reclaimed after sync_with_ledger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_reclaimed_after_sync():
    """sync_with_ledger reclaims capacity from removed txs.

    Haskell ref: pureSyncWithLedger updates the internal size counter.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=500), validator=v, current_slot=0)

    vtx1 = await pool.add_tx(_make_tx(1, 200))
    vtx2 = await pool.add_tx(_make_tx(2, 200))
    assert pool.available_bytes == 100

    # Invalidate tx1 and sync.
    v.reject_ids.add(vtx1.tx_id)
    v.applied_txs.clear()
    await pool.sync_with_ledger(new_slot=10)

    assert pool.available_bytes == 300  # 500 - 200
    assert pool.total_size_bytes == 200

    # Now we can add a 300-byte tx.
    await pool.add_tx(_make_tx(3, 300))
    assert pool.total_size_bytes == 500


# ---------------------------------------------------------------------------
# 8. Double sync_with_ledger idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_double_sync_idempotent():
    """Calling sync_with_ledger twice without changes is idempotent.

    Haskell ref: pureSyncWithLedger applied to a mempool already in sync
    with the ledger state removes nothing.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    for i in range(5):
        await pool.add_tx(_make_tx(i, 100))

    v.applied_txs.clear()
    removed1 = await pool.sync_with_ledger(new_slot=10)
    assert len(removed1) == 0

    v.applied_txs.clear()
    removed2 = await pool.sync_with_ledger(new_slot=10)
    assert len(removed2) == 0

    assert pool.size == 5
    assert pool.total_size_bytes == 500


# ---------------------------------------------------------------------------
# 9. Evict_expired with no timeout is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_no_timeout_configured():
    """evict_expired returns empty list when tx_timeout_slots is None.

    This matches the Haskell node behavior: without explicit timeout,
    txs are only removed by re-validation (TTL in tx body).
    """
    v = _MockValidator()
    config = MempoolConfig(capacity_bytes=10000, tx_timeout_slots=None)
    pool = Mempool(config=config, validator=v, current_slot=0)

    await pool.add_tx(_make_tx(1, 100))

    evicted = await pool.evict_expired(current_slot=999999)
    assert evicted == []
    assert pool.size == 1


# ---------------------------------------------------------------------------
# 10. Remove all then re-add
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_all_then_readd():
    """After removing all txs, pool can be filled again from scratch.

    Ticket numbers continue incrementing (never reset).
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=1000), validator=v, current_slot=0)

    # First generation.
    gen1 = [await pool.add_tx(_make_tx(i, 100)) for i in range(5)]
    gen1_ids = {vtx.tx_id for vtx in gen1}
    await pool.remove_txs(gen1_ids)

    assert pool.size == 0
    assert pool.total_size_bytes == 0

    # Second generation.
    gen2 = [await pool.add_tx(_make_tx(i + 100, 100)) for i in range(5)]

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 5
    assert snap.total_size_bytes == 500

    # Ticket numbers should continue from where gen1 left off.
    first_ticket = snap.tickets[0].ticket_no
    assert first_ticket >= 5, f"Ticket numbers should not reset; got {first_ticket}"


# ---------------------------------------------------------------------------
# 11. Available_bytes tracks correctly through lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_available_bytes_lifecycle():
    """available_bytes is accurate at every step: add, remove, sync, evict."""
    v = _MockValidator()
    config = MempoolConfig(capacity_bytes=1000, tx_timeout_slots=100)
    pool = Mempool(config=config, validator=v, current_slot=0)

    assert pool.available_bytes == 1000

    # Add 300.
    vtx1 = await pool.add_tx(_make_tx(1, 300))
    assert pool.available_bytes == 700

    # Add 200.
    vtx2 = await pool.add_tx(_make_tx(2, 200))
    assert pool.available_bytes == 500

    # Remove vtx1.
    await pool.remove_txs({vtx1.tx_id})
    assert pool.available_bytes == 800

    # Sync that invalidates vtx2.
    v.reject_ids.add(vtx2.tx_id)
    v.applied_txs.clear()
    await pool.sync_with_ledger(new_slot=10)
    assert pool.available_bytes == 1000

    # Add and evict.
    await pool.add_tx(_make_tx(3, 400))
    assert pool.available_bytes == 600
    await pool.evict_expired(current_slot=110)
    assert pool.available_bytes == 1000


# ---------------------------------------------------------------------------
# 12. Event callbacks on capacity rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_rejection_fires_callback():
    """Capacity-based rejection fires TX_REJECTED with reason='capacity'.

    Haskell ref: TraceMempoolRejectedTx in
    Ouroboros.Consensus.Mempool.Impl.Common
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=100), validator=v, current_slot=0)

    events: list[tuple[str, dict]] = []
    pool.on_event(lambda et, d: events.append((et, d)))

    await pool.add_tx(_make_tx(1, 100))

    with pytest.raises(MempoolCapacityError):
        await pool.add_tx(_make_tx(2, 50))

    rejected = [(e, d) for e, d in events if e == MempoolEvent.TX_REJECTED]
    assert len(rejected) == 1
    assert rejected[0][1]["reason"] == "capacity"


# ---------------------------------------------------------------------------
# 13. Hypothesis: add-remove-add cycle never violates capacity
# ---------------------------------------------------------------------------


@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    ops=st.lists(
        st.tuples(
            st.sampled_from(["add", "remove"]),
            st.integers(min_value=0, max_value=99),
            st.integers(min_value=10, max_value=200),
        ),
        min_size=5,
        max_size=30,
    ),
    capacity=st.integers(min_value=200, max_value=2000),
)
@pytest.mark.asyncio
async def test_property_add_remove_cycle_capacity_invariant(
    ops: list[tuple[str, int, int]], capacity: int
):
    """Hypothesis: interleaved add/remove never causes size > capacity.

    Haskell ref: the mempool internal invariant that totalSize <= capacity
    holds across all sequences of add/remove operations.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=capacity), validator=v, current_slot=0)
    added_ids: list[bytes] = []

    for op, seed, size in ops:
        if op == "add":
            tx = _make_tx(seed + 1000, size)
            try:
                vtx = await pool.add_tx(tx)
                added_ids.append(vtx.tx_id)
            except MempoolCapacityError, MempoolDuplicateError, MempoolValidationError:
                pass
        elif op == "remove" and added_ids:
            tx_id = added_ids.pop(0)
            await pool.remove_txs({tx_id})

        assert pool.total_size_bytes <= capacity
        assert pool.available_bytes >= 0
        assert pool.total_size_bytes + pool.available_bytes == capacity


# ---------------------------------------------------------------------------
# 14. Hypothesis: snapshot agrees with size properties
# ---------------------------------------------------------------------------


@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    tx_count=st.integers(min_value=0, max_value=15),
)
@pytest.mark.asyncio
async def test_property_snapshot_size_agreement(tx_count: int):
    """Hypothesis: snapshot total_size_bytes == sum of individual tx sizes."""
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=100000), validator=v, current_slot=0)

    for i in range(tx_count):
        await pool.add_tx(_make_tx(i, 50 + i * 10))

    snap = await pool.get_snapshot()
    computed = sum(t.validated_tx.tx_size for t in snap.tickets)
    assert snap.total_size_bytes == computed
    assert len(snap.tickets) == tx_count


# ---------------------------------------------------------------------------
# 15. get_txs_for_block stops at first tx that doesn't fit (prefix, not knapsack)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_block_selection_stops_at_first_oversize():
    """Block selection is prefix-based: stops at first tx that doesn't fit.

    It does NOT skip large txs to include smaller ones later.
    This is critical Haskell parity — the Haskell node uses prefix selection,
    not knapsack optimization.

    Haskell ref: getSnapshotFor uses a simple prefix scan.
    """
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=50000), validator=v, current_slot=0)

    # Add: 100, 500, 50 (in that order)
    await pool.add_tx(_make_tx(1, 100))
    await pool.add_tx(_make_tx(2, 500))
    await pool.add_tx(_make_tx(3, 50))

    # max_size=200: first tx (100) fits, second (500) doesn't -> stop.
    # The third tx (50) would fit but is not considered.
    result = await pool.get_txs_for_block(max_size=200)
    assert len(result) == 1
    assert result[0].tx_size == 100


# ---------------------------------------------------------------------------
# 16. Mempool slot advances correctly through sync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_advances_through_sync():
    """current_slot updates to new_slot after sync_with_ledger."""
    v = _MockValidator()
    pool = Mempool(config=MempoolConfig(capacity_bytes=10000), validator=v, current_slot=0)

    assert pool.current_slot == 0

    await pool.sync_with_ledger(new_slot=100)
    assert pool.current_slot == 100

    await pool.sync_with_ledger(new_slot=200)
    assert pool.current_slot == 200
