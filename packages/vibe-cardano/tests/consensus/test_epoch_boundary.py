"""Tests for vibe.cardano.consensus.epoch_boundary — epoch transition processing.

Tests cover:
1. Stake distribution: aggregate delegation, pledge inclusion, relative stake
2. Epoch boundary orchestration: full transition including all steps
3. Pool retirement at epoch boundary
4. Protocol parameter updates
5. Hypothesis: relative stakes sum to ~1.0
"""

from __future__ import annotations

from fractions import Fraction
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.epoch_boundary import (
    EpochTransition,
    PendingParamUpdate,
    StakeSnapshot,
    compute_stake_distribution,
    process_epoch_boundary,
    relative_stake,
)
from vibe.cardano.consensus.nonce import EpochNonce, mk_nonce


# ---------------------------------------------------------------------------
# Mock PoolParams — lightweight stand-in for pycardano.PoolParams
# ---------------------------------------------------------------------------


def _mock_pool_params(
    pool_id: bytes,
    pledge: int = 1_000_000_000_000,
    cost: int = 340_000_000,
    margin_num: int = 1,
    margin_den: int = 100,
) -> MagicMock:
    """Create a mock PoolParams with the fields we access."""
    pp = MagicMock()
    pp.operator = pool_id
    pp.pledge = pledge
    pp.cost = cost
    pp.margin = MagicMock()
    pp.margin.numerator = margin_num
    pp.margin.denominator = margin_den
    return pp


# Stable pool IDs for testing
POOL_A = b"\x01" * 28
POOL_B = b"\x02" * 28
POOL_C = b"\x03" * 28
CRED_1 = b"\x11" * 28
CRED_2 = b"\x22" * 28
CRED_3 = b"\x33" * 28
CRED_4 = b"\x44" * 28


# ---------------------------------------------------------------------------
# Stake distribution tests
# ---------------------------------------------------------------------------


class TestComputeStakeDistribution:
    """Stake distribution snapshot computation."""

    def test_basic_aggregation(self) -> None:
        """Stake is aggregated per pool across multiple delegators."""
        utxo_stakes = {
            CRED_1: 100_000_000,
            CRED_2: 200_000_000,
            CRED_3: 300_000_000,
        }
        delegations = {
            CRED_1: POOL_A,
            CRED_2: POOL_A,
            CRED_3: POOL_B,
        }
        pool_regs = {
            POOL_A: _mock_pool_params(POOL_A),
            POOL_B: _mock_pool_params(POOL_B),
        }

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)

        assert snapshot.pool_stakes[POOL_A] == 300_000_000  # CRED_1 + CRED_2
        assert snapshot.pool_stakes[POOL_B] == 300_000_000  # CRED_3
        assert snapshot.total_stake == 600_000_000

    def test_unregistered_pool_ignored(self) -> None:
        """Delegations to unregistered pools are not counted."""
        utxo_stakes = {CRED_1: 100_000_000}
        delegations = {CRED_1: POOL_C}  # POOL_C not registered
        pool_regs = {POOL_A: _mock_pool_params(POOL_A)}

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)
        assert snapshot.pool_stakes.get(POOL_C) is None
        assert snapshot.pool_stakes[POOL_A] == 0
        assert snapshot.total_stake == 0

    def test_undelegated_stake_not_counted(self) -> None:
        """Stake without a delegation is not counted."""
        utxo_stakes = {CRED_1: 100_000_000, CRED_2: 200_000_000}
        delegations = {CRED_1: POOL_A}  # CRED_2 has no delegation
        pool_regs = {POOL_A: _mock_pool_params(POOL_A)}

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)
        assert snapshot.pool_stakes[POOL_A] == 100_000_000
        assert snapshot.total_stake == 100_000_000

    def test_zero_stake_credential(self) -> None:
        """Credentials with zero stake don't affect pool stakes."""
        utxo_stakes = {CRED_1: 0}
        delegations = {CRED_1: POOL_A}
        pool_regs = {POOL_A: _mock_pool_params(POOL_A)}

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)
        assert snapshot.pool_stakes[POOL_A] == 0

    def test_empty_inputs(self) -> None:
        """No UTxOs, no delegations, no pools -> empty snapshot."""
        snapshot = compute_stake_distribution({}, {}, {})
        assert snapshot.pool_stakes == {}
        assert snapshot.total_stake == 0

    def test_pool_params_preserved(self) -> None:
        """Pool params are captured in the snapshot."""
        pp_a = _mock_pool_params(POOL_A, pledge=5_000_000)
        pool_regs = {POOL_A: pp_a}

        snapshot = compute_stake_distribution({}, {}, pool_regs)
        assert snapshot.pool_params[POOL_A] is pp_a

    def test_multiple_pools(self) -> None:
        """Multiple pools with different stake levels."""
        utxo_stakes = {
            CRED_1: 1_000_000,
            CRED_2: 2_000_000,
            CRED_3: 3_000_000,
            CRED_4: 4_000_000,
        }
        delegations = {
            CRED_1: POOL_A,
            CRED_2: POOL_B,
            CRED_3: POOL_A,
            CRED_4: POOL_B,
        }
        pool_regs = {
            POOL_A: _mock_pool_params(POOL_A),
            POOL_B: _mock_pool_params(POOL_B),
        }

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)
        assert snapshot.pool_stakes[POOL_A] == 4_000_000  # CRED_1 + CRED_3
        assert snapshot.pool_stakes[POOL_B] == 6_000_000  # CRED_2 + CRED_4
        assert snapshot.total_stake == 10_000_000


# ---------------------------------------------------------------------------
# Relative stake tests
# ---------------------------------------------------------------------------


class TestRelativeStake:
    """Relative stake calculation."""

    def test_basic_fraction(self) -> None:
        """Pool with 1/4 of total stake."""
        snapshot = StakeSnapshot(
            pool_stakes={POOL_A: 250, POOL_B: 750},
            total_stake=1000,
        )
        assert relative_stake(POOL_A, snapshot) == Fraction(1, 4)
        assert relative_stake(POOL_B, snapshot) == Fraction(3, 4)

    def test_unknown_pool(self) -> None:
        """Unknown pool returns zero relative stake."""
        snapshot = StakeSnapshot(pool_stakes={POOL_A: 1000}, total_stake=1000)
        assert relative_stake(POOL_C, snapshot) == Fraction(0)

    def test_zero_total_stake(self) -> None:
        """Zero total stake returns zero."""
        snapshot = StakeSnapshot(pool_stakes={}, total_stake=0)
        assert relative_stake(POOL_A, snapshot) == Fraction(0)

    def test_single_pool_full_stake(self) -> None:
        """Single pool with all the stake."""
        snapshot = StakeSnapshot(pool_stakes={POOL_A: 1000}, total_stake=1000)
        assert relative_stake(POOL_A, snapshot) == Fraction(1)


# ---------------------------------------------------------------------------
# Pool retirement tests
# ---------------------------------------------------------------------------


class TestPoolRetirement:
    """Pool retirement via process_epoch_boundary."""

    def test_pool_retired_at_scheduled_epoch(self) -> None:
        """Pool scheduled for retirement at epoch 10 is retired when epoch 10 starts."""
        result = process_epoch_boundary(
            new_epoch=10,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={POOL_A: 10},
            delegator_stakes_per_pool={},
            reserves=1_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=0,
            n_opt=500,
            a0=Fraction(3, 10),
        )
        assert POOL_A in result.retired_pools

    def test_pool_not_retired_early(self) -> None:
        """Pool scheduled for epoch 15 is NOT retired at epoch 10."""
        result = process_epoch_boundary(
            new_epoch=10,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={POOL_A: 15},
            delegator_stakes_per_pool={},
            reserves=1_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=0,
            n_opt=500,
            a0=Fraction(3, 10),
        )
        assert POOL_A not in result.retired_pools


# ---------------------------------------------------------------------------
# Protocol parameter update tests
# ---------------------------------------------------------------------------


class TestProtocolParamUpdates:
    """Protocol parameter updates at epoch boundary."""

    def test_update_applied_at_matching_epoch(self) -> None:
        updates = [PendingParamUpdate(epoch=5, updates={"min_fee_a": 50})]
        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={},
            delegator_stakes_per_pool={},
            reserves=0,
            rho=Fraction(0),
            tau=Fraction(0),
            fees=0,
            n_opt=500,
            a0=Fraction(0),
            pending_updates=updates,
        )
        assert result.updated_params == {"min_fee_a": 50}

    def test_update_not_applied_wrong_epoch(self) -> None:
        updates = [PendingParamUpdate(epoch=10, updates={"min_fee_a": 50})]
        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={},
            delegator_stakes_per_pool={},
            reserves=0,
            rho=Fraction(0),
            tau=Fraction(0),
            fees=0,
            n_opt=500,
            a0=Fraction(0),
            pending_updates=updates,
        )
        assert result.updated_params == {}


# ---------------------------------------------------------------------------
# Full epoch boundary processing tests
# ---------------------------------------------------------------------------


class TestProcessEpochBoundary:
    """Full epoch boundary transition orchestration."""

    def test_basic_transition(self) -> None:
        """Basic epoch transition with pools and delegators."""
        pp_a = _mock_pool_params(POOL_A, pledge=10_000_000_000)
        pp_b = _mock_pool_params(POOL_B, pledge=5_000_000_000)

        result = process_epoch_boundary(
            new_epoch=100,
            prev_nonce=mk_nonce(b"epoch 99"),
            eta_v=b"\xab" * 32,
            extra_entropy=None,
            utxo_stakes={
                CRED_1: 50_000_000_000,
                CRED_2: 30_000_000_000,
                CRED_3: 20_000_000_000,
            },
            delegations={
                CRED_1: POOL_A,
                CRED_2: POOL_A,
                CRED_3: POOL_B,
            },
            pool_registrations={POOL_A: pp_a, POOL_B: pp_b},
            retiring={},
            delegator_stakes_per_pool={
                POOL_A: {CRED_1: 50_000_000_000, CRED_2: 30_000_000_000},
                POOL_B: {CRED_3: 20_000_000_000},
            },
            reserves=14_000_000_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=100_000_000,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        assert isinstance(result, EpochTransition)
        assert result.new_epoch == 100
        assert isinstance(result.new_nonce, EpochNonce)
        assert result.stake_snapshot.total_stake == 100_000_000_000
        assert result.reward_pot.rewards_pot > 0
        assert result.total_rewards_distributed >= 0
        assert result.total_rewards_distributed <= result.reward_pot.rewards_pot
        assert result.retired_pools == []
        assert result.updated_params == {}

    def test_nonce_is_evolved(self) -> None:
        """The new nonce differs from the previous nonce."""
        prev = mk_nonce(b"some nonce")
        result = process_epoch_boundary(
            new_epoch=1,
            prev_nonce=prev,
            eta_v=b"\xff" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={},
            delegator_stakes_per_pool={},
            reserves=0,
            rho=Fraction(0),
            tau=Fraction(0),
            fees=0,
            n_opt=500,
            a0=Fraction(0),
        )
        assert result.new_nonce != prev

    def test_empty_epoch(self) -> None:
        """An epoch with no pools, no stake, no fees still produces a valid transition."""
        result = process_epoch_boundary(
            new_epoch=1,
            prev_nonce=mk_nonce(b"genesis"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={},
            delegations={},
            pool_registrations={},
            retiring={},
            delegator_stakes_per_pool={},
            reserves=0,
            rho=Fraction(0),
            tau=Fraction(0),
            fees=0,
            n_opt=500,
            a0=Fraction(0),
        )
        assert result.new_epoch == 1
        assert result.total_rewards_distributed == 0
        assert result.retired_pools == []

    def test_retirement_and_rewards_together(self) -> None:
        """Pools can be retired and rewards distributed in the same epoch."""
        pp_a = _mock_pool_params(POOL_A, pledge=1_000_000_000)

        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x11" * 32,
            extra_entropy=None,
            utxo_stakes={CRED_1: 50_000_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={POOL_B: 5},  # POOL_B retiring
            delegator_stakes_per_pool={
                POOL_A: {CRED_1: 50_000_000_000},
            },
            reserves=1_000_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=50_000_000,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        assert POOL_B in result.retired_pools
        assert result.total_rewards_distributed > 0


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestEpochBoundaryProperties:
    """Property-based tests for epoch boundary processing."""

    @given(
        n_pools=st.integers(min_value=1, max_value=5),
        n_delegators=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=30)
    def test_relative_stakes_sum_to_one(
        self, n_pools: int, n_delegators: int
    ) -> None:
        """Relative stakes of all pools should sum to 1 when all stake is delegated."""
        pool_ids = [bytes([i]) * 28 for i in range(1, n_pools + 1)]
        cred_ids = [bytes([i + 100]) * 28 for i in range(n_delegators)]

        # Each delegator gets 1M lovelace
        utxo_stakes = {c: 1_000_000 for c in cred_ids}

        # Round-robin delegation
        delegations = {c: pool_ids[i % n_pools] for i, c in enumerate(cred_ids)}
        pool_regs = {pid: _mock_pool_params(pid) for pid in pool_ids}

        snapshot = compute_stake_distribution(utxo_stakes, delegations, pool_regs)

        if snapshot.total_stake > 0:
            total_relative = sum(
                relative_stake(pid, snapshot) for pid in pool_ids
            )
            assert total_relative == Fraction(1)

    @given(
        reserves=st.integers(min_value=0, max_value=45_000_000_000_000_000),
        fees=st.integers(min_value=0, max_value=1_000_000_000_000),
    )
    @settings(max_examples=30)
    def test_rewards_distributed_lte_pot(self, reserves: int, fees: int) -> None:
        """Total rewards distributed never exceeds the rewards pot."""
        pp_a = _mock_pool_params(POOL_A, pledge=1_000_000)

        result = process_epoch_boundary(
            new_epoch=1,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={CRED_1: 1_000_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={},
            delegator_stakes_per_pool={POOL_A: {CRED_1: 1_000_000_000}},
            reserves=reserves,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=fees,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        assert result.total_rewards_distributed <= result.reward_pot.rewards_pot
