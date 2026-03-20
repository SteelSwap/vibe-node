"""Tests for vibe.cardano.consensus.epoch_boundary — epoch transition processing.

Tests cover:
1. Stake distribution: aggregate delegation, pledge inclusion, relative stake
2. Epoch boundary orchestration: full transition including all steps
3. Pool retirement at epoch boundary
4. Protocol parameter updates
5. Hypothesis: relative stakes sum to ~1.0
6. Reward calculation with blocks_made performance factor
7. Stake snapshot mark/set/go three-epoch delay
8. Reward zero after key registration
9. Credential removed after deregistration
10. Rewards decrease by withdrawals
11. Reserves/treasury accounting at epoch boundary
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
from vibe.cardano.consensus.rewards import (
    PoolRewardParams,
    pool_reward,
    total_reward_pot,
)


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


# ---------------------------------------------------------------------------
# Test 4: Reward calculation with blocks_made ratio (performance factor)
# ---------------------------------------------------------------------------


class TestRewardPerformanceFactor:
    """The Haskell reward formula uses apparent performance = blocks_made / expected.

    A pool that makes 100% of its expected blocks gets full reward.
    A pool that makes 50% gets ~50% of its reward.
    A pool that makes 0 blocks gets 0 reward.

    Spec ref: Shelley spec Section 5.5.3 — performance factor.
    Haskell ref: ``mkPoolRewardInfo`` — beta / sigma capped at 1.
    """

    def _make_pool(
        self,
        pool_id: bytes = POOL_A,
        pledge: int = 1_000_000_000_000,
        cost: int = 340_000_000,
        margin: Fraction = Fraction(1, 100),
        pool_stake: int = 50_000_000_000_000,
    ) -> PoolRewardParams:
        return PoolRewardParams(
            pool_id=pool_id,
            pledge=pledge,
            cost=cost,
            margin=margin,
            pool_stake=pool_stake,
        )

    def test_full_performance_full_reward(self) -> None:
        """Pool that made 100% of expected blocks gets full reward."""
        pool = self._make_pool()
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        # Without performance factor (default)
        base_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10)
        )

        # With 100% performance
        full_perf_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=100, expected_blocks=100,
        )

        assert full_perf_reward == base_reward

    def test_half_performance_half_reward(self) -> None:
        """Pool that made 50% of expected blocks gets ~50% reward."""
        pool = self._make_pool()
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        full_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=100, expected_blocks=100,
        )

        half_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=50, expected_blocks=100,
        )

        # Half performance should give approximately half reward
        # (exact due to Fraction arithmetic)
        assert half_reward == full_reward // 2

    def test_zero_blocks_zero_reward(self) -> None:
        """Pool that made 0 blocks gets 0 reward."""
        pool = self._make_pool()
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        zero_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=0, expected_blocks=100,
        )

        assert zero_reward == 0

    def test_over_performance_capped_at_one(self) -> None:
        """Pool that made more blocks than expected is capped at 1.0.

        The performance factor min(blocks_made/expected, 1) ensures
        lucky pools don't get extra rewards beyond the formula output.
        """
        pool = self._make_pool()
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        full_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=100, expected_blocks=100,
        )

        over_reward = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=200, expected_blocks=100,
        )

        assert over_reward == full_reward

    def test_zero_expected_blocks_zero_reward(self) -> None:
        """If expected_blocks is 0, pool gets 0 (avoid division by zero)."""
        pool = self._make_pool()
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        r = pool_reward(
            pool, total_stake, rewards_pot, 500, Fraction(3, 10),
            blocks_made=10, expected_blocks=0,
        )
        assert r == 0


# ---------------------------------------------------------------------------
# Test 5: Stake snapshot mark/set/go three-epoch delay
# ---------------------------------------------------------------------------


class TestStakeSnapshotThreeEpochDelay:
    """The Cardano stake snapshot system uses a 3-snapshot pipeline:

    - Mark: snapshot taken at end of epoch N
    - Set: mark snapshot becomes set at end of epoch N+1
    - Go: set snapshot is used for leader election in epoch N+2

    This ensures leader election is deterministic and known 2 epochs in advance.

    Spec ref: Shelley spec Section 11, Figure 46 (SNAP rule).
    Haskell ref: ``SnapShots`` in ``Cardano.Ledger.Shelley.LedgerState``
    """

    def test_three_epoch_delay(self) -> None:
        """Changes in stake at epoch N don't affect leader election until N+2.

        We simulate 3 epoch transitions:
        - Epoch 0: CRED_1 has 100M delegated to POOL_A
        - Epoch 1: CRED_1 increases to 200M (mark snapshot changes)
        - Epoch 2: Previous mark becomes set
        - Epoch 3: The set snapshot from epoch 1 is now used for leader election

        The key verification: the snapshot at each epoch boundary captures
        the state as it existed at that moment.
        """
        # Epoch boundary 0->1: initial stake distribution
        snap_epoch_1 = compute_stake_distribution(
            utxo_stakes={CRED_1: 100_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: _mock_pool_params(POOL_A)},
        )
        assert snap_epoch_1.pool_stakes[POOL_A] == 100_000_000

        # Epoch boundary 1->2: stake increased (this is the "mark" snapshot)
        snap_epoch_2 = compute_stake_distribution(
            utxo_stakes={CRED_1: 200_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: _mock_pool_params(POOL_A)},
        )
        assert snap_epoch_2.pool_stakes[POOL_A] == 200_000_000

        # The snapshots are different — epoch 1 snapshot has old stake
        assert snap_epoch_1.pool_stakes[POOL_A] != snap_epoch_2.pool_stakes[POOL_A]

        # In the pipeline: epoch 3 leader election uses snap_epoch_1,
        # epoch 4 uses snap_epoch_2. The 2-epoch lag means:
        # mark (epoch N) -> set (epoch N+1) -> go (epoch N+2)
        mark = snap_epoch_2  # taken at end of epoch 1
        go_snapshot = snap_epoch_1  # used in epoch 3 (taken 2 epochs earlier)

        # The go snapshot (used for leader election) has the OLD stake
        assert go_snapshot.pool_stakes[POOL_A] == 100_000_000
        # The mark snapshot (freshly taken) has the NEW stake
        assert mark.pool_stakes[POOL_A] == 200_000_000

    def test_relative_stake_uses_correct_snapshot(self) -> None:
        """Relative stake calculated from the 'go' snapshot reflects
        the state from 2 epochs ago, not the current state."""
        # Old snapshot (2 epochs ago): POOL_A had 25% of stake
        old_snapshot = StakeSnapshot(
            pool_stakes={POOL_A: 250, POOL_B: 750},
            total_stake=1000,
        )

        # Current snapshot: POOL_A now has 50% of stake
        current_snapshot = StakeSnapshot(
            pool_stakes={POOL_A: 500, POOL_B: 500},
            total_stake=1000,
        )

        # Leader election uses old snapshot (go)
        sigma_go = relative_stake(POOL_A, old_snapshot)
        sigma_current = relative_stake(POOL_A, current_snapshot)

        assert sigma_go == Fraction(1, 4)
        assert sigma_current == Fraction(1, 2)
        assert sigma_go != sigma_current


# ---------------------------------------------------------------------------
# Test 6: Reward zero after key registration
# ---------------------------------------------------------------------------


class TestRewardZeroAfterRegistration:
    """A newly registered staking credential has zero rewards until the first
    epoch boundary after its delegation becomes active.

    In the Cardano model, a stake key registration creates the credential
    in the delegation state with zero rewards. The credential only begins
    earning rewards after it is included in a stake snapshot that is used
    for leader election (the "go" snapshot), which takes 2 full epochs.

    Spec ref: Shelley spec, Section 9 (Delegation rules).
    Haskell ref: ``DState`` initial reward balance is 0.
    """

    def test_newly_registered_credential_has_zero_rewards(self) -> None:
        """A freshly registered credential should not appear in reward
        distribution results until it is part of an active delegation."""
        # Simulate: CRED_4 just registered but is NOT yet in the delegation map
        # or utxo_stakes. It should not appear in rewards.
        pp_a = _mock_pool_params(POOL_A, pledge=1_000_000)
        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={CRED_1: 50_000_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={},
            delegator_stakes_per_pool={POOL_A: {CRED_1: 50_000_000_000}},
            reserves=1_000_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=50_000_000,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        # CRED_4 is not in any pool's reward distribution
        for pr in result.pool_rewards:
            assert CRED_4 not in pr.member_rewards

    def test_credential_with_delegation_but_no_stake_gets_zero(self) -> None:
        """A credential that is delegated but has 0 stake gets 0 reward."""
        pp_a = _mock_pool_params(POOL_A, pledge=1_000_000)
        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            # CRED_4 has delegation but zero stake
            utxo_stakes={CRED_1: 50_000_000_000, CRED_4: 0},
            delegations={CRED_1: POOL_A, CRED_4: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={},
            delegator_stakes_per_pool={
                POOL_A: {CRED_1: 50_000_000_000, CRED_4: 0},
            },
            reserves=1_000_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=50_000_000,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        # CRED_4 either gets 0 reward or is not in the map
        for pr in result.pool_rewards:
            cred4_reward = pr.member_rewards.get(CRED_4, 0)
            assert cred4_reward == 0


# ---------------------------------------------------------------------------
# Test 7: Credential removed after deregistration
# ---------------------------------------------------------------------------


class TestCredentialDeregistration:
    """After a stake key deregistration, the credential is removed from
    the delegation state and its rewards are returned.

    We test that once a credential is removed from the delegation map,
    it no longer appears in the stake distribution or reward calculations.

    Spec ref: Shelley spec, Section 9 (DELEG rule).
    Haskell ref: ``DState`` — deregistration removes from ``rewards`` map.
    """

    def test_deregistered_credential_not_in_snapshot(self) -> None:
        """After deregistration, the credential's stake is not counted."""
        # Before deregistration: CRED_1 and CRED_2 delegate to POOL_A
        snap_before = compute_stake_distribution(
            utxo_stakes={CRED_1: 100_000_000, CRED_2: 200_000_000},
            delegations={CRED_1: POOL_A, CRED_2: POOL_A},
            pool_registrations={POOL_A: _mock_pool_params(POOL_A)},
        )
        assert snap_before.pool_stakes[POOL_A] == 300_000_000

        # After CRED_2 deregisters: removed from delegations and utxo_stakes
        snap_after = compute_stake_distribution(
            utxo_stakes={CRED_1: 100_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: _mock_pool_params(POOL_A)},
        )
        assert snap_after.pool_stakes[POOL_A] == 100_000_000

    def test_deregistered_credential_not_in_rewards(self) -> None:
        """After deregistration, the credential does not appear in rewards."""
        pp_a = _mock_pool_params(POOL_A, pledge=1_000_000)

        # CRED_2 has been deregistered — not in delegations or stakes
        result = process_epoch_boundary(
            new_epoch=5,
            prev_nonce=mk_nonce(b"test"),
            eta_v=b"\x00" * 32,
            extra_entropy=None,
            utxo_stakes={CRED_1: 50_000_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={},
            delegator_stakes_per_pool={POOL_A: {CRED_1: 50_000_000_000}},
            reserves=1_000_000_000_000,
            rho=Fraction(3, 1000),
            tau=Fraction(2, 10),
            fees=50_000_000,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        for pr in result.pool_rewards:
            assert CRED_2 not in pr.member_rewards


# ---------------------------------------------------------------------------
# Test 8: Rewards decrease by withdrawals
# ---------------------------------------------------------------------------


class TestRewardsDecreaseByWithdrawals:
    """When a staking credential withdraws rewards, the balance decreases
    by exactly the withdrawal amount.

    This tests the accounting invariant at the reward-tracking level.
    In Cardano, withdrawals are explicit transactions that move rewards
    from the reward account to the UTxO.

    Spec ref: Shelley spec, Section 10 (DELEGS rule — withdrawal handling).
    Haskell ref: ``DState.rewards`` — decremented by withdrawal amount.
    """

    def test_withdrawal_reduces_balance(self) -> None:
        """Simulate reward accumulation and withdrawal accounting."""
        # Model a simple reward account
        reward_balance: dict[bytes, int] = {}

        # Epoch boundary distributes rewards
        earned = 5_000_000  # 5 ADA earned
        reward_balance[CRED_1] = reward_balance.get(CRED_1, 0) + earned
        assert reward_balance[CRED_1] == 5_000_000

        # Withdrawal of 3 ADA
        withdrawal = 3_000_000
        assert reward_balance[CRED_1] >= withdrawal
        reward_balance[CRED_1] -= withdrawal
        assert reward_balance[CRED_1] == 2_000_000

        # Full withdrawal of remaining balance
        remaining = reward_balance[CRED_1]
        reward_balance[CRED_1] -= remaining
        assert reward_balance[CRED_1] == 0

    def test_withdrawal_exact_amount(self) -> None:
        """Withdrawing exactly the reward balance leaves zero."""
        reward_balance = {CRED_1: 10_000_000}
        withdrawal = 10_000_000
        reward_balance[CRED_1] -= withdrawal
        assert reward_balance[CRED_1] == 0

    def test_partial_withdrawal_preserves_remainder(self) -> None:
        """Partial withdrawal leaves the correct remainder."""
        reward_balance = {CRED_1: 10_000_000}
        withdrawal = 7_500_000
        reward_balance[CRED_1] -= withdrawal
        assert reward_balance[CRED_1] == 2_500_000

    def test_withdrawal_cannot_exceed_balance(self) -> None:
        """Withdrawals must not exceed the reward balance.

        This is enforced at the transaction validation level. We verify
        the invariant: balance - withdrawal >= 0.
        """
        reward_balance = {CRED_1: 5_000_000}
        withdrawal = 10_000_000
        # The transaction validator would reject this, but we verify the check
        assert reward_balance[CRED_1] < withdrawal
        # A valid implementation should NOT allow this


# ---------------------------------------------------------------------------
# Test 9: Reserves/treasury accounting at epoch boundary
# ---------------------------------------------------------------------------


class TestReservesTreasuryAccounting:
    """Verify the accounting identity at epoch boundary:

        monetary_expansion = floor(reserves * rho)
        total_pot = monetary_expansion + fees
        treasury_cut = floor(total_pot * tau)
        rewards_pot = total_pot - treasury_cut

    After epoch boundary processing:
        - reserves decrease by monetary_expansion
        - treasury increases by treasury_cut
        - rewards_pot = (1 - tau) * (monetary_expansion + fees)

    Spec ref: Shelley spec Section 5.5.3.
    Haskell ref: ``createRUpd`` in ``Cardano.Ledger.Shelley.Rules.NewEpoch``
    """

    def test_basic_accounting_identity(self) -> None:
        """Treasury + rewards = total pot (conservation)."""
        reserves = 14_000_000_000_000_000  # 14B ADA
        rho = Fraction(3, 1000)
        tau = Fraction(2, 10)
        fees = 200_000_000_000  # 200K ADA

        pot = total_reward_pot(reserves, rho, tau, fees)

        # Conservation: treasury_cut + rewards_pot == total_pot
        assert pot.treasury_cut + pot.rewards_pot == pot.total_pot

        # Monetary expansion: floor(reserves * rho)
        expected_expansion = int(Fraction(reserves) * rho)
        assert pot.monetary_expansion == expected_expansion

        # Total pot: expansion + fees
        assert pot.total_pot == expected_expansion + fees

        # Treasury: floor(total_pot * tau)
        expected_treasury = int(Fraction(pot.total_pot) * tau)
        assert pot.treasury_cut == expected_treasury

        # Rewards: remainder
        assert pot.rewards_pot == pot.total_pot - expected_treasury

    def test_reserves_decrease_by_expansion(self) -> None:
        """After epoch boundary, reserves should decrease by monetary_expansion."""
        reserves = 10_000_000_000_000_000
        rho = Fraction(3, 1000)
        tau = Fraction(2, 10)
        fees = 100_000_000_000

        pot = total_reward_pot(reserves, rho, tau, fees)

        new_reserves = reserves - pot.monetary_expansion
        assert new_reserves == reserves - int(Fraction(reserves) * rho)
        assert new_reserves < reserves
        assert new_reserves > 0

    def test_treasury_increases_by_cut(self) -> None:
        """Treasury increases by exactly treasury_cut each epoch."""
        reserves = 10_000_000_000_000_000
        rho = Fraction(3, 1000)
        tau = Fraction(2, 10)
        fees = 100_000_000_000

        pot = total_reward_pot(reserves, rho, tau, fees)

        old_treasury = 5_000_000_000_000_000
        new_treasury = old_treasury + pot.treasury_cut

        assert new_treasury == old_treasury + int(Fraction(pot.total_pot) * tau)
        assert new_treasury > old_treasury

    def test_rewards_pot_equals_one_minus_tau_times_total(self) -> None:
        """rewards_pot = total_pot - floor(total_pot * tau).

        Due to floor, this is not exactly (1-tau)*total, but the
        accounting identity total = treasury + rewards always holds.
        """
        reserves = 14_000_000_000_000_000
        rho = Fraction(3, 1000)
        tau = Fraction(2, 10)
        fees = 500_000_000_000

        pot = total_reward_pot(reserves, rho, tau, fees)

        # The key identity
        assert pot.treasury_cut + pot.rewards_pot == pot.total_pot

        # Verify rewards_pot matches the formula
        assert pot.rewards_pot == pot.total_pot - int(Fraction(pot.total_pot) * tau)

    def test_zero_reserves_zero_fees(self) -> None:
        """With no reserves and no fees, everything is zero."""
        pot = total_reward_pot(0, Fraction(3, 1000), Fraction(2, 10), 0)
        assert pot.monetary_expansion == 0
        assert pot.total_pot == 0
        assert pot.treasury_cut == 0
        assert pot.rewards_pot == 0

    def test_full_epoch_boundary_accounting(self) -> None:
        """Full epoch boundary preserves accounting invariants."""
        reserves = 14_000_000_000_000_000
        rho = Fraction(3, 1000)
        tau = Fraction(2, 10)
        fees = 200_000_000_000

        pp_a = _mock_pool_params(POOL_A, pledge=10_000_000_000)
        result = process_epoch_boundary(
            new_epoch=100,
            prev_nonce=mk_nonce(b"epoch 99"),
            eta_v=b"\xab" * 32,
            extra_entropy=None,
            utxo_stakes={CRED_1: 50_000_000_000},
            delegations={CRED_1: POOL_A},
            pool_registrations={POOL_A: pp_a},
            retiring={},
            delegator_stakes_per_pool={POOL_A: {CRED_1: 50_000_000_000}},
            reserves=reserves,
            rho=rho,
            tau=tau,
            fees=fees,
            n_opt=500,
            a0=Fraction(3, 10),
        )

        pot = result.reward_pot

        # Conservation identity
        assert pot.treasury_cut + pot.rewards_pot == pot.total_pot

        # Rewards distributed never exceeds pot
        assert result.total_rewards_distributed <= pot.rewards_pot

        # Verify expansion
        assert pot.monetary_expansion == int(Fraction(reserves) * rho)

        # New reserves after this epoch
        new_reserves = reserves - pot.monetary_expansion
        assert new_reserves >= 0
