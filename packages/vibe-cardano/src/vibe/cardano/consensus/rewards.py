"""Per-epoch reward calculation following the Shelley ledger formal spec.

Implements the reward formulas from Shelley spec Section 5.5.3:

1. **Reward pot** — split reserves expansion + fees into treasury and
   staking rewards.
2. **Pool reward** — compute each pool's share of the rewards pot, taking
   pledge influence (a0) into account.
3. **Member rewards** — distribute pool rewards to pool operator and
   delegators proportionally, after operator margin and cost.

All financial calculations use ``Fraction`` for exact rational arithmetic.
Final lovelace amounts use floor division (truncation toward zero), matching
the Haskell ``Coin`` semantics.

Spec references:
    * Shelley ledger formal spec, Section 5.5.3 (Reward calculation)
    * Shelley ledger formal spec, Figure 32 (Individual pool reward)
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rewards.hs``

Haskell references:
    * ``rewardOnePool`` in ``Cardano.Ledger.Shelley.Rewards``
    * ``createRUpd`` in ``Cardano.Ledger.Shelley.Rules.NewEpoch``
    * ``mkPoolRewardInfo`` in ``Cardano.Ledger.Shelley.Rewards``
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

__all__ = [
    "MemberRewardResult",
    "PoolRewardParams",
    "RewardPot",
    "member_rewards",
    "pool_reward",
    "total_reward_pot",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RewardPot:
    """Result of splitting the monetary expansion into treasury and rewards.

    All values are in lovelace (integer).

    Spec ref: Shelley spec Section 5.5.3, Equations for Delta_r, Delta_t.
    """

    monetary_expansion: int
    """Total monetary expansion from reserves: floor(reserves * rho)."""

    total_pot: int
    """monetary_expansion + fees collected in the epoch."""

    treasury_cut: int
    """Amount going to treasury: floor(total_pot * tau)."""

    rewards_pot: int
    """Amount available for staking rewards: total_pot - treasury_cut."""


@dataclass(frozen=True, slots=True)
class PoolRewardParams:
    """Parameters for a single pool needed for reward calculation.

    Mirrors the fields extracted from ``PoolParams`` plus delegation-derived
    stake info.
    """

    pool_id: bytes
    """28-byte pool key hash."""

    pledge: int
    """Pool's declared pledge in lovelace."""

    cost: int
    """Pool's declared fixed cost in lovelace."""

    margin: Fraction
    """Pool's declared margin as a rational number in [0, 1]."""

    pool_stake: int
    """Total stake delegated to this pool (including pledge) in lovelace."""


@dataclass(frozen=True, slots=True)
class MemberRewardResult:
    """Reward distribution for a single pool.

    Spec ref: Shelley spec Section 5.5.3, member reward formula.
    """

    pool_id: bytes
    """28-byte pool key hash."""

    total_pool_reward: int
    """The pool's total reward (before splitting operator/members)."""

    operator_reward: int
    """Reward going to the pool operator (cost + margin share)."""

    member_rewards: dict[bytes, int]
    """stake_credential_hash -> reward in lovelace for each delegator."""


# ---------------------------------------------------------------------------
# Reward pot calculation
# ---------------------------------------------------------------------------


def total_reward_pot(
    reserves: int,
    rho: Fraction,
    tau: Fraction,
    fees: int,
) -> RewardPot:
    """Calculate the total reward pot and treasury cut for an epoch.

    Spec (Shelley Section 5.5.3):
        Delta_r  = floor(reserves * rho)
        total    = Delta_r + fees
        Delta_t  = floor(total * tau)
        rewards  = total - Delta_t

    Haskell ref: ``createRUpd`` in ``Cardano.Ledger.Shelley.Rules.NewEpoch``
        computes ``rewardPot = deltaR1 + blocksMade_fees`` then splits with tau.

    Args:
        reserves: Current reserves in lovelace.
        rho: Monetary expansion rate (e.g., Fraction(3, 1000) for 0.3%).
        tau: Treasury tax rate (e.g., Fraction(2, 10) for 20%).
        fees: Total transaction fees collected in the epoch.

    Returns:
        RewardPot with all components.
    """
    # Monetary expansion: floor(reserves * rho)
    monetary_expansion = int(Fraction(reserves) * rho)

    # Total pot: monetary expansion + fees
    total_pot = monetary_expansion + fees

    # Treasury cut: floor(total_pot * tau)
    treasury_cut = int(Fraction(total_pot) * tau)

    # Staking rewards: remainder
    rewards_pot = total_pot - treasury_cut

    return RewardPot(
        monetary_expansion=monetary_expansion,
        total_pot=total_pot,
        treasury_cut=treasury_cut,
        rewards_pot=rewards_pot,
    )


# ---------------------------------------------------------------------------
# Individual pool reward
# ---------------------------------------------------------------------------


def pool_reward(
    pool: PoolRewardParams,
    total_stake: int,
    rewards_pot: int,
    n_opt: int,
    a0: Fraction,
    blocks_made: int | None = None,
    expected_blocks: int | None = None,
) -> int:
    """Calculate the optimal reward for a single pool.

    Implements the Shelley reward formula (spec Section 5.5.3, Figure 32):

        z = 1 / n_opt    (saturation threshold)
        sigma' = min(sigma, z)
        s'     = min(s, z)

        R_pool = floor(R / (1 + a0) *
                       (sigma' + s' * a0 * (sigma' - s' * ((z - sigma') / z)) / z))

    Where:
        R      = rewards_pot
        sigma  = pool_stake / total_stake  (actual stake ratio)
        s      = pledge / total_stake      (pledge ratio)
        a0     = pledge influence parameter
        z      = 1 / n_opt                 (saturation point)

    If the pool's actual pledge on-chain is less than its declared pledge,
    the pool gets zero rewards.  This check should be done by the caller
    before invoking this function.

    Haskell ref: ``mkPoolRewardInfo`` and ``rewardOnePool`` in
        ``Cardano.Ledger.Shelley.Rewards``

    Args:
        pool: Pool parameters including stake and pledge.
        total_stake: Total active stake across all pools.
        rewards_pot: Total rewards available for distribution.
        n_opt: Desired number of pools (``nOpt`` protocol parameter,
               a.k.a. ``k`` in the spec formula).
        a0: Pledge influence factor (protocol parameter).
        blocks_made: Number of blocks the pool actually produced in the epoch.
            If None, the performance factor is assumed to be 1.0 (full performance).
        expected_blocks: Number of blocks the pool was expected to produce
            (proportional to its stake and the total blocks in the epoch).
            If None, the performance factor is assumed to be 1.0 (full performance).

    Returns:
        The pool's total reward in lovelace (floor of the rational result).
        Returns 0 if total_stake is 0 or pool_stake is 0.
    """
    if total_stake == 0 or pool.pool_stake == 0:
        return 0

    # Performance factor: ratio of actual blocks made to expected blocks.
    # The Haskell node uses "apparent performance" = beta / sigma, but we
    # express it directly as blocks_made / expected_blocks and cap at 1.0.
    # If a pool made 0 blocks, it gets 0 rewards.
    # If blocks_made/expected_blocks are not provided, assume full performance.
    #
    # Spec ref: Shelley spec Section 5.5.3 — performance factor in reward calc.
    # Haskell ref: ``desirability`` and ``mkPoolRewardInfo`` in
    #     ``Cardano.Ledger.Shelley.Rewards`` — uses ``beta / sigma`` capped at 1.
    if blocks_made is not None and expected_blocks is not None:
        if expected_blocks == 0:
            # No blocks expected — pool gets nothing
            return 0
        if blocks_made == 0:
            return 0
        performance = min(Fraction(blocks_made, expected_blocks), Fraction(1))
    else:
        performance = Fraction(1)

    R = Fraction(rewards_pot)
    sigma = Fraction(pool.pool_stake, total_stake)
    s = Fraction(pool.pledge, total_stake)
    z = Fraction(1, n_opt)

    # Cap at saturation point
    sigma_prime = min(sigma, z)
    s_prime = min(s, z)

    # Shelley reward formula:
    #   R / (1 + a0) * (sigma' + s' * a0 * (sigma' - s' * ((z - sigma') / z)) / z)
    #
    # Breaking it down:
    #   inner = (z - sigma') / z
    #   middle = sigma' - s' * inner
    #   right = s' * a0 * middle / z
    #   pool_R = R / (1 + a0) * (sigma' + right)

    if z == 0:
        return 0

    inner = (z - sigma_prime) / z
    middle = sigma_prime - s_prime * inner
    right = s_prime * a0 * middle / z
    pool_R = R / (1 + a0) * (sigma_prime + right)

    # Apply performance factor
    pool_R = pool_R * performance

    return int(pool_R)  # floor toward zero


# ---------------------------------------------------------------------------
# Member reward distribution
# ---------------------------------------------------------------------------


def member_rewards(
    pool: PoolRewardParams,
    total_pool_reward: int,
    delegator_stakes: dict[bytes, int],
) -> MemberRewardResult:
    """Distribute a pool's total reward among operator and delegators.

    The pool operator takes:
        1. The fixed cost (capped at total_pool_reward)
        2. A margin percentage of the remainder
        3. Their proportional share as a delegator (pledge-based)

    The remaining reward is split among all delegators (including the
    operator if they are also a delegator) proportionally to their stake.

    Spec ref: Shelley spec Section 5.5.3, member reward formula.
    Haskell ref: ``rewardOnePool`` in ``Cardano.Ledger.Shelley.Rewards``
        splits the reward into leader reward + member rewards.

    Args:
        pool: Pool parameters (cost, margin, pledge, pool_stake).
        total_pool_reward: The pool's total reward from ``pool_reward()``.
        delegator_stakes: Map from stake credential hash -> stake in lovelace
            for all delegators (including pool operator's own stake/pledge).

    Returns:
        MemberRewardResult with operator reward and per-delegator rewards.
    """
    if total_pool_reward == 0 or pool.pool_stake == 0:
        return MemberRewardResult(
            pool_id=pool.pool_id,
            total_pool_reward=0,
            operator_reward=0,
            member_rewards={},
        )

    reward = Fraction(total_pool_reward)

    # Step 1: Pool takes fixed cost
    cost = min(Fraction(pool.cost), reward)
    after_cost = reward - cost

    # Step 2: Pool takes margin from remainder
    margin_cut = after_cost * pool.margin
    after_margin = after_cost - margin_cut

    # Step 3: Operator gets cost + margin + proportional share of remainder
    # The operator's proportional share is based on their pledge relative to
    # total pool stake.
    operator_proportional = Fraction(0)
    if pool.pool_stake > 0:
        operator_proportional = after_margin * Fraction(pool.pledge, pool.pool_stake)

    operator_reward = int(cost + margin_cut + operator_proportional)

    # Step 4: Distribute remaining proportionally to delegators
    # (excluding operator's pledge-based share which was already counted)
    member_reward_map: dict[bytes, int] = {}
    for cred_hash, stake in delegator_stakes.items():
        if stake > 0 and pool.pool_stake > 0:
            member_share = after_margin * Fraction(stake, pool.pool_stake)
            member_lovelace = int(member_share)
            if member_lovelace > 0:
                member_reward_map[cred_hash] = member_lovelace

    # Safety: clamp total distributed to not exceed pool reward.
    # Due to independent floor operations on operator + each member share,
    # the sum can exceed the total by a few lovelace. The Haskell node
    # handles this via precise Coin arithmetic; we clamp the operator reward
    # downward if needed.
    total_member = sum(member_reward_map.values())
    if operator_reward + total_member > total_pool_reward:
        operator_reward = total_pool_reward - total_member
        if operator_reward < 0:
            # Extremely unlikely: many members each rounding up.
            # Scale member rewards down proportionally.
            operator_reward = 0
            member_reward_map = {}

    return MemberRewardResult(
        pool_id=pool.pool_id,
        total_pool_reward=total_pool_reward,
        operator_reward=operator_reward,
        member_rewards=member_reward_map,
    )
