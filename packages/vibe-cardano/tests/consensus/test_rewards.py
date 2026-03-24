"""Tests for vibe.cardano.consensus.rewards — per-epoch reward calculation.

Tests cover:
1. Reward pot splitting (rho/tau monetary policy)
2. Individual pool reward calculation with pledge influence
3. Member reward distribution (operator cost, margin, proportional)
4. Edge cases: zero stake, zero rewards, saturated pools
5. Hypothesis: rewards non-negative, total distributed <= pot
"""

from __future__ import annotations

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.consensus.rewards import (
    PoolRewardParams,
    member_rewards,
    pool_reward,
    total_reward_pot,
)

# ---------------------------------------------------------------------------
# Mainnet-like protocol parameters for testing
# ---------------------------------------------------------------------------

# Mainnet rho = 0.003 (0.3% monetary expansion per epoch)
MAINNET_RHO = Fraction(3, 1000)

# Mainnet tau = 0.2 (20% treasury tax)
MAINNET_TAU = Fraction(2, 10)

# Mainnet nOpt = 500 (desired number of pools)
MAINNET_N_OPT = 500

# Mainnet a0 = 0.3 (pledge influence)
MAINNET_A0 = Fraction(3, 10)


# ---------------------------------------------------------------------------
# Reward pot tests
# ---------------------------------------------------------------------------


class TestTotalRewardPot:
    """Reward pot calculation: monetary expansion + fees, split by tau."""

    def test_basic_split(self) -> None:
        """Basic reward pot with simple numbers."""
        pot = total_reward_pot(
            reserves=1_000_000_000_000,  # 1T lovelace
            rho=Fraction(1, 100),  # 1%
            tau=Fraction(1, 5),  # 20%
            fees=500_000_000,  # 500 ADA in fees
        )
        # monetary_expansion = floor(1T * 0.01) = 10B
        assert pot.monetary_expansion == 10_000_000_000
        # total_pot = 10B + 500M = 10.5B
        assert pot.total_pot == 10_500_000_000
        # treasury_cut = floor(10.5B * 0.2) = 2.1B
        assert pot.treasury_cut == 2_100_000_000
        # rewards = 10.5B - 2.1B = 8.4B
        assert pot.rewards_pot == 8_400_000_000

    def test_mainnet_scale(self) -> None:
        """Mainnet-scale numbers: ~14B ADA reserves."""
        pot = total_reward_pot(
            reserves=14_000_000_000_000_000,  # 14B ADA = 14e15 lovelace
            rho=MAINNET_RHO,
            tau=MAINNET_TAU,
            fees=200_000_000_000,  # 200K ADA fees
        )
        # monetary_expansion = floor(14e15 * 3/1000) = 42e12
        assert pot.monetary_expansion == 42_000_000_000_000
        assert pot.total_pot == 42_000_000_000_000 + 200_000_000_000
        # Treasury gets 20%
        assert pot.treasury_cut == int(Fraction(pot.total_pot) * MAINNET_TAU)
        assert pot.rewards_pot == pot.total_pot - pot.treasury_cut

    def test_zero_reserves(self) -> None:
        """Zero reserves means only fees contribute to rewards."""
        pot = total_reward_pot(reserves=0, rho=MAINNET_RHO, tau=MAINNET_TAU, fees=1_000_000)
        assert pot.monetary_expansion == 0
        assert pot.total_pot == 1_000_000
        assert pot.rewards_pot > 0

    def test_zero_fees(self) -> None:
        """Zero fees means only monetary expansion contributes."""
        pot = total_reward_pot(
            reserves=1_000_000_000, rho=Fraction(1, 10), tau=Fraction(1, 10), fees=0
        )
        assert pot.monetary_expansion == 100_000_000
        assert pot.total_pot == 100_000_000

    def test_zero_everything(self) -> None:
        """No reserves, no fees, no rewards."""
        pot = total_reward_pot(reserves=0, rho=MAINNET_RHO, tau=MAINNET_TAU, fees=0)
        assert pot.monetary_expansion == 0
        assert pot.total_pot == 0
        assert pot.treasury_cut == 0
        assert pot.rewards_pot == 0

    def test_tau_zero_means_no_treasury(self) -> None:
        """If tau=0, all rewards go to stakers."""
        pot = total_reward_pot(
            reserves=1_000_000_000, rho=Fraction(1, 10), tau=Fraction(0), fees=0
        )
        assert pot.treasury_cut == 0
        assert pot.rewards_pot == pot.total_pot

    def test_tau_one_means_all_treasury(self) -> None:
        """If tau=1, all rewards go to treasury."""
        pot = total_reward_pot(
            reserves=1_000_000_000, rho=Fraction(1, 10), tau=Fraction(1), fees=0
        )
        assert pot.treasury_cut == pot.total_pot
        assert pot.rewards_pot == 0

    def test_conservation(self) -> None:
        """Treasury + rewards = total pot."""
        pot = total_reward_pot(
            reserves=9_876_543_210, rho=Fraction(7, 1000), tau=Fraction(19, 100), fees=123_456_789
        )
        assert pot.treasury_cut + pot.rewards_pot == pot.total_pot


# ---------------------------------------------------------------------------
# Pool reward tests
# ---------------------------------------------------------------------------


def _make_pool(
    pool_id: bytes = b"\x01" * 28,
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


class TestPoolReward:
    """Individual pool reward calculation with pledge influence."""

    def test_basic_pool_reward(self) -> None:
        """A pool with reasonable stake gets a positive reward."""
        pool = _make_pool(pool_stake=50_000_000_000_000)
        total_stake = 25_000_000_000_000_000  # 25B ADA
        rewards_pot = 30_000_000_000_000  # 30M ADA

        pr = pool_reward(pool, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)
        assert pr > 0

    def test_zero_stake_pool_gets_nothing(self) -> None:
        pool = _make_pool(pool_stake=0)
        pr = pool_reward(pool, 1_000_000, 1_000_000, MAINNET_N_OPT, MAINNET_A0)
        assert pr == 0

    def test_zero_total_stake(self) -> None:
        pool = _make_pool(pool_stake=100)
        pr = pool_reward(pool, 0, 1_000_000, MAINNET_N_OPT, MAINNET_A0)
        assert pr == 0

    def test_zero_rewards_pot(self) -> None:
        pool = _make_pool()
        pr = pool_reward(pool, 1_000_000_000_000, 0, MAINNET_N_OPT, MAINNET_A0)
        assert pr == 0

    def test_higher_pledge_higher_reward(self) -> None:
        """Higher pledge should produce higher reward (a0 influence)."""
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        low_pledge = _make_pool(pledge=100_000_000_000)  # 100K ADA
        high_pledge = _make_pool(pledge=5_000_000_000_000)  # 5M ADA

        r_low = pool_reward(low_pledge, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)
        r_high = pool_reward(high_pledge, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)

        assert r_high > r_low

    def test_saturated_pool_capped(self) -> None:
        """A pool above saturation gets capped at z = 1/nOpt."""
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        # Saturation point: total_stake / nOpt = 50B lovelace
        normal = _make_pool(pool_stake=50_000_000_000_000)  # exactly at saturation
        oversaturated = _make_pool(pool_stake=100_000_000_000_000)  # 2x saturation

        r_normal = pool_reward(normal, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)
        r_over = pool_reward(oversaturated, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)

        # Oversaturated pool should NOT get more reward than saturated pool
        assert r_over == r_normal

    def test_a0_zero_no_pledge_influence(self) -> None:
        """With a0=0, pledge has no influence on rewards."""
        total_stake = 25_000_000_000_000_000
        rewards_pot = 30_000_000_000_000

        low_pledge = _make_pool(pledge=1_000_000)
        high_pledge = _make_pool(pledge=5_000_000_000_000)

        r_low = pool_reward(low_pledge, total_stake, rewards_pot, MAINNET_N_OPT, Fraction(0))
        r_high = pool_reward(high_pledge, total_stake, rewards_pot, MAINNET_N_OPT, Fraction(0))

        assert r_low == r_high

    def test_reward_is_integer(self) -> None:
        """Pool reward must be an integer (floor of rational calculation)."""
        pool = _make_pool()
        pr = pool_reward(
            pool, 25_000_000_000_000_000, 30_000_000_000_000, MAINNET_N_OPT, MAINNET_A0
        )
        assert isinstance(pr, int)


# ---------------------------------------------------------------------------
# Member reward distribution tests
# ---------------------------------------------------------------------------


class TestMemberRewards:
    """Distribution of pool rewards to operator and delegators."""

    def test_basic_distribution(self) -> None:
        """Rewards are split between operator and delegators."""
        pool = _make_pool(
            pledge=10_000_000_000_000,
            cost=340_000_000,
            margin=Fraction(5, 100),  # 5% margin
            pool_stake=100_000_000_000_000,
        )
        delegators = {
            b"\xaa" * 28: 40_000_000_000_000,  # 40K ADA
            b"\xbb" * 28: 50_000_000_000_000,  # 50K ADA
        }

        result = member_rewards(pool, 5_000_000_000, delegators)
        assert result.total_pool_reward == 5_000_000_000
        assert result.operator_reward > 0
        assert len(result.member_rewards) == 2

    def test_zero_reward(self) -> None:
        """Zero total reward means nothing to distribute."""
        pool = _make_pool()
        result = member_rewards(pool, 0, {b"\xaa" * 28: 1_000_000})
        assert result.operator_reward == 0
        assert result.member_rewards == {}

    def test_cost_comes_first(self) -> None:
        """Pool cost is taken before margin."""
        pool = _make_pool(cost=1_000_000, margin=Fraction(0), pool_stake=100)
        result = member_rewards(pool, 1_000_000, {})
        # All reward goes to cost, nothing left for margin or members
        assert result.operator_reward == 1_000_000

    def test_cost_exceeds_reward(self) -> None:
        """If cost exceeds total reward, operator gets all of it."""
        pool = _make_pool(cost=10_000_000, margin=Fraction(0), pool_stake=100)
        result = member_rewards(pool, 5_000_000, {})
        # Cost is capped at total reward
        assert result.operator_reward == 5_000_000

    def test_proportional_to_stake(self) -> None:
        """Delegators get rewards proportional to their stake."""
        pool = _make_pool(
            pledge=0,
            cost=0,
            margin=Fraction(0),
            pool_stake=100_000,
        )
        delegators = {
            b"\xaa" * 28: 75_000,  # 75%
            b"\xbb" * 28: 25_000,  # 25%
        }

        result = member_rewards(pool, 1_000_000, delegators)
        r_a = result.member_rewards.get(b"\xaa" * 28, 0)
        r_b = result.member_rewards.get(b"\xbb" * 28, 0)

        # 75% should get ~3x the reward of 25%
        assert r_a == 3 * r_b

    def test_total_distributed_lte_pot(self) -> None:
        """Total distributed rewards must not exceed the pool reward."""
        pool = _make_pool(
            pledge=5_000_000_000_000,
            cost=340_000_000,
            margin=Fraction(3, 100),
            pool_stake=50_000_000_000_000,
        )
        delegators = {
            b"\xaa" * 28: 20_000_000_000_000,
            b"\xbb" * 28: 15_000_000_000_000,
            b"\xcc" * 28: 10_000_000_000_000,
        }

        total_pool_r = 5_000_000_000
        result = member_rewards(pool, total_pool_r, delegators)

        total_distributed = result.operator_reward + sum(result.member_rewards.values())
        assert total_distributed <= total_pool_r


# ---------------------------------------------------------------------------
# Hypothesis property-based tests
# ---------------------------------------------------------------------------


class TestRewardProperties:
    """Property-based tests for reward calculations."""

    @given(
        reserves=st.integers(min_value=0, max_value=45_000_000_000_000_000),
        fees=st.integers(min_value=0, max_value=1_000_000_000_000),
    )
    @settings(max_examples=50)
    def test_reward_pot_conservation(self, reserves: int, fees: int) -> None:
        """treasury_cut + rewards_pot == total_pot always."""
        pot = total_reward_pot(reserves, MAINNET_RHO, MAINNET_TAU, fees)
        assert pot.treasury_cut + pot.rewards_pot == pot.total_pot

    @given(
        reserves=st.integers(min_value=0, max_value=45_000_000_000_000_000),
        fees=st.integers(min_value=0, max_value=1_000_000_000_000),
    )
    @settings(max_examples=50)
    def test_reward_pot_non_negative(self, reserves: int, fees: int) -> None:
        """All reward pot components are non-negative."""
        pot = total_reward_pot(reserves, MAINNET_RHO, MAINNET_TAU, fees)
        assert pot.monetary_expansion >= 0
        assert pot.total_pot >= 0
        assert pot.treasury_cut >= 0
        assert pot.rewards_pot >= 0

    @given(
        pool_stake=st.integers(min_value=1, max_value=100_000_000_000_000),
        pledge=st.integers(min_value=0, max_value=50_000_000_000_000),
        rewards_pot=st.integers(min_value=0, max_value=50_000_000_000_000),
    )
    @settings(max_examples=50)
    def test_pool_reward_non_negative(
        self, pool_stake: int, pledge: int, rewards_pot: int
    ) -> None:
        """Pool reward is always non-negative."""
        pledge = min(pledge, pool_stake)
        pool = _make_pool(pledge=pledge, pool_stake=pool_stake)
        total_stake = 25_000_000_000_000_000
        pr = pool_reward(pool, total_stake, rewards_pot, MAINNET_N_OPT, MAINNET_A0)
        assert pr >= 0

    @given(
        total_pool_reward=st.integers(min_value=0, max_value=10_000_000_000),
        n_delegators=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=50)
    def test_member_rewards_lte_pool_reward(
        self, total_pool_reward: int, n_delegators: int
    ) -> None:
        """Total member rewards + operator reward <= total pool reward."""
        pool_stake = 100_000_000_000
        delegators = {bytes([i]) * 28: pool_stake // n_delegators for i in range(n_delegators)}

        pool = _make_pool(
            pledge=10_000_000_000,
            cost=340_000_000,
            margin=Fraction(5, 100),
            pool_stake=pool_stake,
        )

        result = member_rewards(pool, total_pool_reward, delegators)
        total_distributed = result.operator_reward + sum(result.member_rewards.values())
        assert total_distributed <= total_pool_reward
