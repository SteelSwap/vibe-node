"""Tests for the transaction mempool.

Tests cover:
    - Add valid transaction, verify it's in snapshot
    - Add invalid transaction, verify rejection
    - Remove transaction by ID
    - Capacity enforcement (reject when full)
    - Re-validation removes expired/double-spent txs on tip change
    - get_txs_for_block returns prefix that fits
    - Concurrent add from multiple tasks
    - Hypothesis: mempool size never exceeds capacity
    - Duplicate transaction rejection
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
    MempoolValidationError,
    _compute_tx_id,
)
from vibe.cardano.mempool.types import MempoolConfig

# ---------------------------------------------------------------------------
# Mock validator
# ---------------------------------------------------------------------------


class MockValidator:
    """Mock transaction validator for testing.

    Accepts all transactions by default. Can be configured to reject
    specific transactions or all transactions after a certain point.
    Tracks applied transactions to simulate UTxO state.
    """

    def __init__(self) -> None:
        self.reject_ids: set[bytes] = set()
        self.reject_all: bool = False
        self.applied_txs: list[bytes] = []
        self._saved_states: list[list[bytes]] = []

    def validate_tx(self, tx_cbor: bytes, current_slot: int) -> list[str]:
        """Validate — reject if tx_id is in reject_ids or reject_all is set."""
        tx_id = _compute_tx_id(tx_cbor)
        if self.reject_all:
            return ["MockRejection: reject_all is set"]
        if tx_id in self.reject_ids:
            return [f"MockRejection: tx {tx_id.hex()[:16]} is rejected"]
        # Check for double-spend: if tx_cbor was already applied, reject.
        if tx_cbor in self.applied_txs:
            return ["MockDoubleSpend: transaction already applied"]
        return []

    def apply_tx(self, tx_cbor: bytes, current_slot: int) -> None:
        """Apply — record the transaction."""
        self.applied_txs.append(tx_cbor)

    def snapshot_state(self) -> Any:
        """Save current state."""
        return list(self.applied_txs)

    def restore_state(self, state: Any) -> None:
        """Restore state."""
        self.applied_txs = list(state)


def make_tx(seed: int, size: int = 100) -> bytes:
    """Create a fake transaction of a given size with a unique seed."""
    # Pad to the desired size with the seed repeated.
    base = seed.to_bytes(4, "big")
    return (base * ((size // len(base)) + 1))[:size]


# ---------------------------------------------------------------------------
# Basic operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_valid_tx_appears_in_snapshot():
    """Add a valid tx and verify it shows up in the snapshot."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=100)

    tx = make_tx(1, 200)
    vtx = await pool.add_tx(tx)

    assert vtx.tx_cbor == tx
    assert vtx.tx_size == 200
    assert vtx.tx_id == _compute_tx_id(tx)

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 1
    assert snap.tickets[0].validated_tx.tx_id == vtx.tx_id
    assert snap.slot == 100
    assert snap.total_size_bytes == 200


@pytest.mark.asyncio
async def test_add_invalid_tx_rejected():
    """Add an invalid tx and verify it's rejected with MempoolValidationError."""
    validator = MockValidator()
    tx = make_tx(1, 100)
    tx_id = _compute_tx_id(tx)
    validator.reject_ids.add(tx_id)

    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    with pytest.raises(MempoolValidationError) as exc_info:
        await pool.add_tx(tx)

    assert exc_info.value.tx_id == tx_id
    assert len(exc_info.value.errors) == 1

    # Mempool should still be empty.
    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 0
    assert snap.total_size_bytes == 0


@pytest.mark.asyncio
async def test_add_duplicate_tx_rejected():
    """Adding the same tx twice raises MempoolDuplicateError."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx = make_tx(42, 100)
    await pool.add_tx(tx)

    with pytest.raises(MempoolDuplicateError):
        await pool.add_tx(tx)

    assert pool.size == 1


@pytest.mark.asyncio
async def test_remove_txs_by_id():
    """Remove specific txs by their IDs."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    tx3 = make_tx(3, 150)

    vtx1 = await pool.add_tx(tx1)
    vtx2 = await pool.add_tx(tx2)
    vtx3 = await pool.add_tx(tx3)

    # Remove tx2.
    removed = await pool.remove_txs({vtx2.tx_id})
    assert removed == 1

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 2
    remaining_ids = {t.validated_tx.tx_id for t in snap.tickets}
    assert vtx1.tx_id in remaining_ids
    assert vtx3.tx_id in remaining_ids
    assert vtx2.tx_id not in remaining_ids
    assert snap.total_size_bytes == 250  # 100 + 150


@pytest.mark.asyncio
async def test_remove_nonexistent_tx_is_noop():
    """Removing a tx that doesn't exist returns 0 and changes nothing."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx = make_tx(1, 100)
    await pool.add_tx(tx)

    removed = await pool.remove_txs({b"\x00" * 32})
    assert removed == 0
    assert pool.size == 1


# ---------------------------------------------------------------------------
# Capacity enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capacity_enforcement_rejects_when_full():
    """Reject a tx when adding it would exceed capacity."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=300)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    # Fill up to 200 bytes.
    tx1 = make_tx(1, 200)
    await pool.add_tx(tx1)

    # Try to add 150 bytes — would total 350, exceeding 300.
    tx2 = make_tx(2, 150)
    with pytest.raises(MempoolCapacityError) as exc_info:
        await pool.add_tx(tx2)

    assert exc_info.value.needed == 150
    assert exc_info.value.available == 100
    assert exc_info.value.capacity == 300

    # Mempool should still have only tx1.
    assert pool.size == 1
    assert pool.total_size_bytes == 200


@pytest.mark.asyncio
async def test_capacity_allows_exact_fit():
    """A tx that exactly fills remaining capacity should be accepted."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=300)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 200)
    await pool.add_tx(tx1)

    tx2 = make_tx(2, 100)  # Exactly 300 total.
    vtx2 = await pool.add_tx(tx2)
    assert vtx2.tx_size == 100
    assert pool.total_size_bytes == 300


# ---------------------------------------------------------------------------
# Re-validation on tip change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_with_ledger_removes_invalid_txs():
    """Re-validation removes txs that are now invalid after tip change."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    tx3 = make_tx(3, 150)

    vtx1 = await pool.add_tx(tx1)
    vtx2 = await pool.add_tx(tx2)
    vtx3 = await pool.add_tx(tx3)

    # Now simulate a tip change where tx2 becomes invalid.
    tx2_id = _compute_tx_id(tx2)
    validator.reject_ids.add(tx2_id)
    # Reset applied state to simulate fresh ledger state.
    validator.applied_txs.clear()

    removed = await pool.sync_with_ledger(new_slot=50)

    assert tx2_id in removed
    assert len(removed) == 1

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 2
    assert snap.slot == 50
    assert snap.total_size_bytes == 250  # 100 + 150

    # Verify ordering is preserved — tx1 before tx3.
    assert snap.tickets[0].validated_tx.tx_id == vtx1.tx_id
    assert snap.tickets[1].validated_tx.tx_id == vtx3.tx_id


@pytest.mark.asyncio
async def test_sync_with_ledger_removes_all_if_all_invalid():
    """If all txs become invalid on tip change, mempool empties."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    await pool.add_tx(tx1)
    await pool.add_tx(tx2)

    # Reject everything.
    validator.reject_all = True
    validator.applied_txs.clear()

    removed = await pool.sync_with_ledger(new_slot=99)
    assert len(removed) == 2

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 0
    assert snap.total_size_bytes == 0


# ---------------------------------------------------------------------------
# Block selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_txs_for_block_returns_prefix():
    """get_txs_for_block returns the largest prefix that fits."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    tx3 = make_tx(3, 150)

    vtx1 = await pool.add_tx(tx1)
    vtx2 = await pool.add_tx(tx2)
    vtx3 = await pool.add_tx(tx3)

    # Request up to 250 bytes — should get tx1 (100) + tx2 (200) = 300 > 250,
    # so only tx1 fits then tx2 doesn't fit.
    # Wait — 100 + 200 = 300 > 250 is wrong.  100 <= 250, then 100 + 200 = 300 > 250.
    # So result should be [tx1] only.
    result = await pool.get_txs_for_block(max_size=250)
    assert len(result) == 1
    assert result[0].tx_id == vtx1.tx_id

    # Request up to 300 — all first two fit.
    result = await pool.get_txs_for_block(max_size=300)
    assert len(result) == 2
    assert result[0].tx_id == vtx1.tx_id
    assert result[1].tx_id == vtx2.tx_id

    # Request up to 500 — all three fit.
    result = await pool.get_txs_for_block(max_size=500)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_txs_for_block_empty_mempool():
    """get_txs_for_block on empty mempool returns empty list."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    result = await pool.get_txs_for_block(max_size=1000)
    assert result == []


@pytest.mark.asyncio
async def test_get_txs_for_block_zero_max_size():
    """get_txs_for_block with max_size=0 returns nothing."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    await pool.add_tx(make_tx(1, 100))

    result = await pool.get_txs_for_block(max_size=0)
    assert result == []


# ---------------------------------------------------------------------------
# Helper methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_tx():
    """has_tx returns True for present txs, False otherwise."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx = make_tx(1, 100)
    vtx = await pool.add_tx(tx)

    assert await pool.has_tx(vtx.tx_id) is True
    assert await pool.has_tx(b"\x00" * 32) is False


@pytest.mark.asyncio
async def test_get_tx_ids_and_sizes():
    """get_tx_ids_and_sizes returns all txs in order."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 200)
    vtx1 = await pool.add_tx(tx1)
    vtx2 = await pool.add_tx(tx2)

    ids_and_sizes = await pool.get_tx_ids_and_sizes()
    assert len(ids_and_sizes) == 2
    assert ids_and_sizes[0] == (vtx1.tx_id, 100)
    assert ids_and_sizes[1] == (vtx2.tx_id, 200)


@pytest.mark.asyncio
async def test_get_tx_by_id():
    """get_tx returns CBOR bytes for known txs, None for unknown."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx = make_tx(1, 100)
    vtx = await pool.add_tx(tx)

    result = await pool.get_tx(vtx.tx_id)
    assert result == tx

    assert await pool.get_tx(b"\x00" * 32) is None


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_adds():
    """Multiple concurrent add_tx calls don't corrupt state."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=100000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    num_tasks = 50
    txs = [make_tx(i, 100) for i in range(num_tasks)]

    async def add_one(tx: bytes) -> None:
        await pool.add_tx(tx)

    await asyncio.gather(*[add_one(tx) for tx in txs])

    assert pool.size == num_tasks
    assert pool.total_size_bytes == num_tasks * 100

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == num_tasks

    # All ticket numbers should be unique.
    ticket_nos = [t.ticket_no for t in snap.tickets]
    assert len(set(ticket_nos)) == num_tasks


@pytest.mark.asyncio
async def test_concurrent_add_and_remove():
    """Concurrent adds and removes don't corrupt state."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=100000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    # Pre-populate with some txs to remove.
    pre_txs = [make_tx(i, 100) for i in range(10)]
    pre_vtxs = []
    for tx in pre_txs:
        pre_vtxs.append(await pool.add_tx(tx))

    # Concurrently add new txs and remove old ones.
    new_txs = [make_tx(i + 100, 100) for i in range(10)]

    async def add_new(tx: bytes) -> None:
        await pool.add_tx(tx)

    async def remove_old(vtx) -> None:
        await pool.remove_txs({vtx.tx_id})

    tasks = []
    for tx in new_txs:
        tasks.append(add_new(tx))
    for vtx in pre_vtxs:
        tasks.append(remove_old(vtx))

    await asyncio.gather(*tasks)

    # Should have exactly the 10 new txs.
    assert pool.size == 10
    assert pool.total_size_bytes == 1000


# ---------------------------------------------------------------------------
# Ticket ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_numbers_are_monotonic():
    """Ticket numbers increase monotonically even after removals."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=10000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    tx1 = make_tx(1, 100)
    tx2 = make_tx(2, 100)
    vtx1 = await pool.add_tx(tx1)
    vtx2 = await pool.add_tx(tx2)

    # Remove tx1.
    await pool.remove_txs({vtx1.tx_id})

    # Add tx3 — should get ticket_no > tx2's.
    tx3 = make_tx(3, 100)
    vtx3 = await pool.add_tx(tx3)

    snap = await pool.get_snapshot()
    assert len(snap.tickets) == 2
    # tx2 has ticket_no=1, tx3 has ticket_no=2.
    assert snap.tickets[0].ticket_no < snap.tickets[1].ticket_no


# ---------------------------------------------------------------------------
# Hypothesis property: size invariant
# ---------------------------------------------------------------------------


@settings(
    max_examples=50,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    tx_sizes=st.lists(
        st.integers(min_value=1, max_value=500),
        min_size=1,
        max_size=20,
    ),
    capacity=st.integers(min_value=100, max_value=5000),
)
@pytest.mark.asyncio
async def test_property_size_never_exceeds_capacity(tx_sizes: list[int], capacity: int):
    """Hypothesis property: mempool total_size_bytes never exceeds capacity."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=capacity)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    for i, size in enumerate(tx_sizes):
        tx = make_tx(i, size)
        try:
            await pool.add_tx(tx)
        except MempoolCapacityError, MempoolValidationError, MempoolDuplicateError:
            pass

        assert (
            pool.total_size_bytes <= capacity
        ), f"Invariant violated: total_size_bytes={pool.total_size_bytes} > capacity={capacity}"


# ---------------------------------------------------------------------------
# Repr and len
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repr_and_len():
    """__repr__ and __len__ work as expected."""
    validator = MockValidator()
    config = MempoolConfig(capacity_bytes=1000)
    pool = Mempool(config=config, validator=validator, current_slot=0)

    assert len(pool) == 0
    assert "txs=0" in repr(pool)
    assert "1000" in repr(pool)

    await pool.add_tx(make_tx(1, 100))
    assert len(pool) == 1
