"""Epoch boundary processing — stake snapshots, reward distribution, nonce evolution.

At the boundary between epoch N and epoch N+1, the Cardano node performs several
critical state transitions:

1. **Stake snapshot** — capture the stake distribution for leader election
   using the 2-epoch lag rule (snapshot from epoch N-2 is used in epoch N).
2. **Reward calculation** — compute and distribute rewards for epoch N.
3. **Nonce evolution** — derive the new epoch nonce from VRF outputs.
4. **Protocol parameter updates** — apply any queued parameter changes.
5. **Pool retirement** — execute scheduled pool retirements (POOLREAP).

This module orchestrates the TICK / NEWEPOCH transition rules.

Spec references:
    * Shelley ledger formal spec, Section 11 (Epoch boundary rules)
    * Shelley ledger formal spec, Figure 43 (TICK transition)
    * Shelley ledger formal spec, Figure 44 (NEWEPOCH transition)
    * Shelley ledger formal spec, Figure 45 (EPOCH transition)

Haskell references:
    * ``Cardano.Ledger.Shelley.Rules.Tick`` — TICK transition
    * ``Cardano.Ledger.Shelley.Rules.NewEpoch`` — NEWEPOCH transition
    * ``Cardano.Ledger.Shelley.Rules.Epoch`` — EPOCH sub-transition
    * ``Cardano.Ledger.Shelley.Rules.PoolReap`` — pool retirement
    * ``Cardano.Ledger.Shelley.Rules.Snap`` — snapshot management
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from pycardano.certificate import PoolParams

from vibe.cardano.consensus.nonce import EpochNonce, evolve_nonce
from vibe.cardano.consensus.rewards import (
    MemberRewardResult,
    PoolRewardParams,
    RewardPot,
    member_rewards,
    pool_reward,
    total_reward_pot,
)

__all__ = [
    "EpochTransition",
    "PendingParamUpdate",
    "StakeSnapshot",
    "compute_stake_distribution",
    "process_epoch_boundary",
    "relative_stake",
]


# ---------------------------------------------------------------------------
# Stake distribution snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StakeSnapshot:
    """Snapshot of the stake distribution at an epoch boundary.

    Cardano uses a 2-epoch lag for stake:

        Epoch N-2 end -> snapshot taken
        Epoch N-1     -> snapshot is "set" (immutable)
        Epoch N       -> snapshot used for leader election

    This ensures leader election is deterministic — all nodes agree on the
    stake distribution used for slot assignment.

    Spec ref: Shelley spec Section 11, Figure 46 (SNAP rule).
    Haskell ref: ``SnapShot`` in ``Cardano.Ledger.Shelley.LedgerState``
        contains ``ssStake`` (delegator stake), ``ssDelegations``, ``ssPoolParams``.

    Attributes:
        pool_stakes: Mapping from pool_key_hash -> total stake delegated to
            that pool (including the operator's pledge), in lovelace.
        total_stake: Sum of all pool_stakes values.
        pool_params: Mapping from pool_key_hash -> PoolParams at snapshot time.
    """

    pool_stakes: dict[bytes, int] = field(default_factory=dict)
    """pool_key_hash -> total delegated stake (lovelace)."""

    total_stake: int = 0
    """Sum of all pool stakes."""

    pool_params: dict[bytes, PoolParams] = field(default_factory=dict)
    """pool_key_hash -> PoolParams at the time of the snapshot."""


def compute_stake_distribution(
    utxo_stakes: dict[bytes, int],
    delegations: dict[bytes, bytes],
    pool_registrations: dict[bytes, PoolParams],
) -> StakeSnapshot:
    """Compute the stake distribution from UTxO data and delegations.

    For each registered stake credential that has a delegation:
        1. Look up its total stake from the UTxO set.
        2. Find which pool it delegates to.
        3. Aggregate stake per pool.

    Spec ref: Shelley spec Section 11, SNAP rule — computes the stake
        distribution by resolving delegations against the UTxO set.
    Haskell ref: ``stakeDistr`` in ``Cardano.Ledger.Shelley.LedgerState``

    Args:
        utxo_stakes: Mapping from stake_credential_hash -> total lovelace
            controlled by that credential (sum of all UTxO outputs whose
            staking credential matches).
        delegations: Mapping from stake_credential_hash -> pool_key_hash.
        pool_registrations: Mapping from pool_key_hash -> PoolParams
            (only registered pools are valid delegation targets).

    Returns:
        StakeSnapshot with per-pool aggregated stakes.
    """
    pool_stakes: dict[bytes, int] = {}

    # Initialize all registered pools with zero stake
    for pool_id in pool_registrations:
        pool_stakes[pool_id] = 0

    # Aggregate delegated stake per pool
    for cred_hash, pool_id in delegations.items():
        # Only count delegations to registered pools
        if pool_id not in pool_registrations:
            continue

        stake = utxo_stakes.get(cred_hash, 0)
        if stake > 0:
            pool_stakes[pool_id] = pool_stakes.get(pool_id, 0) + stake

    # Compute total stake
    total = sum(pool_stakes.values())

    return StakeSnapshot(
        pool_stakes=pool_stakes,
        total_stake=total,
        pool_params=dict(pool_registrations),
    )


def relative_stake(pool_id: bytes, snapshot: StakeSnapshot) -> Fraction:
    """Compute a pool's relative stake as an exact fraction.

    Returns sigma = pool_stake / total_stake.  Returns Fraction(0) if
    the pool is not in the snapshot or total_stake is zero.

    This fraction is used directly in the VRF leader-check threshold
    calculation.

    Spec ref: Shelley spec Section 5.5.3 — sigma in reward formula.
    Haskell ref: ``poolStake`` in ``Cardano.Ledger.Shelley.Rewards``

    Args:
        pool_id: 28-byte pool key hash.
        snapshot: The stake snapshot.

    Returns:
        Exact rational relative stake in [0, 1].
    """
    if snapshot.total_stake == 0:
        return Fraction(0)

    stake = snapshot.pool_stakes.get(pool_id, 0)
    return Fraction(stake, snapshot.total_stake)


# ---------------------------------------------------------------------------
# Protocol parameter updates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PendingParamUpdate:
    """A protocol parameter update queued for application at an epoch boundary.

    Spec ref: Shelley spec Section 11, PPUP rule.
    Haskell ref: ``ProposedPPUpdates`` in ``Cardano.Ledger.Shelley.PParams``
    """

    epoch: int
    """Epoch at which this update takes effect."""

    updates: dict[str, Any]
    """Parameter name -> new value.  Keys match ShelleyProtocolParams field names."""


# ---------------------------------------------------------------------------
# Epoch transition result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpochTransition:
    """Result of processing an epoch boundary.

    Captures all the state changes that occur at the transition from one
    epoch to the next.

    Haskell ref: The NEWEPOCH transition produces updated ``EpochState``
        containing new nonce, rewards, snapshots, and protocol params.
    """

    new_epoch: int
    """The epoch number we are transitioning INTO."""

    new_nonce: EpochNonce
    """The evolved epoch nonce for the new epoch."""

    stake_snapshot: StakeSnapshot
    """The stake snapshot taken at this boundary (to be used 2 epochs later)."""

    reward_pot: RewardPot
    """The reward pot breakdown for this epoch."""

    pool_rewards: list[MemberRewardResult]
    """Per-pool reward distribution results."""

    total_rewards_distributed: int
    """Total lovelace distributed as rewards (should be <= rewards_pot)."""

    retired_pools: list[bytes]
    """Pool key hashes of pools retired at this boundary."""

    updated_params: dict[str, Any]
    """Protocol parameters that were updated at this boundary (may be empty)."""


# ---------------------------------------------------------------------------
# Pool retirement (POOLREAP)
# ---------------------------------------------------------------------------


def _process_pool_retirements(
    retiring: dict[bytes, int],
    current_epoch: int,
) -> tuple[list[bytes], dict[bytes, int]]:
    """Execute pool retirements scheduled for the current epoch.

    Spec ref: Shelley spec, POOLREAP transition rule.
    Haskell ref: ``Cardano.Ledger.Shelley.Rules.PoolReap``

    Args:
        retiring: Mapping from pool_key_hash -> scheduled retirement epoch.
        current_epoch: The epoch we are entering.

    Returns:
        Tuple of (list of retired pool IDs, updated retiring map with
        retired pools removed).
    """
    retired: list[bytes] = []
    remaining: dict[bytes, int] = {}

    for pool_id, retire_epoch in retiring.items():
        if retire_epoch <= current_epoch:
            retired.append(pool_id)
        else:
            remaining[pool_id] = retire_epoch

    return retired, remaining


# ---------------------------------------------------------------------------
# Epoch boundary processing — the main orchestrator
# ---------------------------------------------------------------------------


def process_epoch_boundary(
    new_epoch: int,
    prev_nonce: EpochNonce,
    eta_v: bytes,
    extra_entropy: bytes | None,
    utxo_stakes: dict[bytes, int],
    delegations: dict[bytes, bytes],
    pool_registrations: dict[bytes, PoolParams],
    retiring: dict[bytes, int],
    delegator_stakes_per_pool: dict[bytes, dict[bytes, int]],
    reserves: int,
    rho: Fraction,
    tau: Fraction,
    fees: int,
    n_opt: int,
    a0: Fraction,
    pending_updates: list[PendingParamUpdate] | None = None,
) -> EpochTransition:
    """Process an epoch boundary — the TICK/NEWEPOCH transition.

    Called when the first block of a new epoch is seen.  This is the
    top-level orchestrator that:

    1. Takes a stake snapshot (SNAP rule)
    2. Calculates rewards for the previous epoch (REWARD rule)
    3. Evolves the nonce (OVERLAY/UPDN rules)
    4. Applies pending protocol parameter updates (PPUP rule)
    5. Executes pool retirements (POOLREAP rule)

    Spec ref: Shelley spec Section 11, NEWEPOCH transition.
    Haskell ref: ``shelleyNewEpochTransition`` in
        ``Cardano.Ledger.Shelley.Rules.NewEpoch``

    Args:
        new_epoch: The epoch number we are transitioning into.
        prev_nonce: The epoch nonce from the previous epoch.
        eta_v: Accumulated VRF hash from the stability window (32 bytes).
        extra_entropy: Optional extra entropy from protocol param updates.
        utxo_stakes: stake_credential_hash -> total lovelace for snapshot.
        delegations: stake_credential_hash -> pool_key_hash.
        pool_registrations: pool_key_hash -> PoolParams.
        retiring: pool_key_hash -> retirement epoch.
        delegator_stakes_per_pool: pool_key_hash -> {cred_hash -> stake}
            for member reward distribution.
        reserves: Current reserves in lovelace.
        rho: Monetary expansion rate.
        tau: Treasury tax rate.
        fees: Total fees collected in the epoch.
        n_opt: Desired number of pools (nOpt / k).
        a0: Pledge influence factor.
        pending_updates: Protocol parameter updates queued for this epoch.

    Returns:
        EpochTransition capturing all state changes.
    """
    # Step 1: Stake snapshot
    snapshot = compute_stake_distribution(
        utxo_stakes, delegations, pool_registrations
    )

    # Step 2: Reward calculation
    pot = total_reward_pot(reserves, rho, tau, fees)

    pool_reward_results: list[MemberRewardResult] = []
    total_distributed = 0

    for pool_id, pool_stake in snapshot.pool_stakes.items():
        if pool_stake == 0:
            continue

        params = pool_registrations.get(pool_id)
        if params is None:
            continue

        # Build pool reward params
        prp = PoolRewardParams(
            pool_id=pool_id,
            pledge=params.pledge if hasattr(params, 'pledge') else 0,
            cost=params.cost if hasattr(params, 'cost') else 0,
            margin=Fraction(
                params.margin.numerator, params.margin.denominator
            ) if hasattr(params, 'margin') and params.margin is not None
            else Fraction(0),
            pool_stake=pool_stake,
        )

        # Calculate optimal pool reward
        pr = pool_reward(prp, snapshot.total_stake, pot.rewards_pot, n_opt, a0)

        # Distribute among operator and delegators
        pool_delegators = delegator_stakes_per_pool.get(pool_id, {})
        result = member_rewards(prp, pr, pool_delegators)

        pool_reward_results.append(result)
        total_distributed += result.operator_reward + sum(
            result.member_rewards.values()
        )

    # Step 3: Nonce evolution
    new_nonce = evolve_nonce(prev_nonce, eta_v, extra_entropy)

    # Step 4: Protocol parameter updates
    applied_updates: dict[str, Any] = {}
    if pending_updates:
        for update in pending_updates:
            if update.epoch == new_epoch:
                applied_updates.update(update.updates)

    # Step 5: Pool retirements
    retired_pools, _remaining_retiring = _process_pool_retirements(
        retiring, new_epoch
    )

    return EpochTransition(
        new_epoch=new_epoch,
        new_nonce=new_nonce,
        stake_snapshot=snapshot,
        reward_pot=pot,
        pool_rewards=pool_reward_results,
        total_rewards_distributed=total_distributed,
        retired_pools=retired_pools,
        updated_params=applied_updates,
    )
