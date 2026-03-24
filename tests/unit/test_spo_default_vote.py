"""Tests for SPO default vote logic in Conway governance ratification.

This test suite validates the CONSENSUS-CRITICAL fix for SPO ratification.
The bug: our check_ratification only counted explicit votes in the SPO
denominator, ignoring non-voting pools entirely. The Haskell node's
``spoAcceptedRatio`` (Ratify.hs) counts ALL pools in the stake distribution,
with non-voting pools getting a default vote based on protocol version and
reward account delegation.

Spec ref: Conway formal spec, Section 6 (Ratification).
Haskell ref: ``spoAcceptedRatio`` in ``Cardano.Ledger.Conway.Rules.Ratify``
"""

from __future__ import annotations

from vibe.cardano.ledger.conway import (
    DefaultVote,
    check_ratification,
    default_stake_pool_vote,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    DRep,
    DRepType,
    GovAction,
    GovActionId,
    GovActionType,
    GovernanceState,
    ProposalProcedure,
    RatificationThresholds,
    Vote,
    Voter,
    VoterRole,
    VotingProcedure,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pool_id(n: int) -> bytes:
    """Generate a deterministic 28-byte pool ID."""
    return (n).to_bytes(1, "big") * 28


def _make_anchor() -> Anchor:
    return Anchor(url="https://example.com", data_hash=b"\x00" * 32)


def _make_action_id(n: int = 0) -> GovActionId:
    return GovActionId(tx_id=b"\xaa" * 32, gov_action_index=n)


def _make_proposal(action_type: GovActionType) -> ProposalProcedure:
    return ProposalProcedure(
        deposit=100_000_000_000,
        return_addr=b"\x00" * 29,
        gov_action=GovAction(action_type=action_type),
        anchor=_make_anchor(),
    )


def _spo_threshold() -> RatificationThresholds:
    """SPO-only threshold at 51% for simple testing."""
    return RatificationThresholds(
        cc_threshold=None,
        drep_threshold=None,
        spo_threshold=(51, 100),
    )


# ---------------------------------------------------------------------------
# 1. PV10+ non-voting pool defaults to No (included in denominator)
# ---------------------------------------------------------------------------


def test_pv10_nonvoting_pool_defaults_to_no() -> None:
    """PV >= 10: a non-voting pool with no reward delegation defaults to No.

    The pool's stake stays in the denominator, diluting the Yes ratio.
    """
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.NO_CONFIDENCE,
        protocol_version_major=10,
        reward_account_delegations={},
    )
    assert result == DefaultVote.NO


# ---------------------------------------------------------------------------
# 2. PV9 non-voting pool defaults to Abstain (excluded from denominator)
# ---------------------------------------------------------------------------


def test_pv9_nonvoting_pool_defaults_to_abstain() -> None:
    """PV < 10 (bootstrap phase): non-voting pools abstain, excluded from denominator."""
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.NO_CONFIDENCE,
        protocol_version_major=9,
        reward_account_delegations={},
    )
    assert result == DefaultVote.ABSTAIN


# ---------------------------------------------------------------------------
# 3. PV9 single Yes vote -> 100% ratio (the exploit case)
# ---------------------------------------------------------------------------


def test_pv9_single_yes_vote_100_percent() -> None:
    """Bootstrap phase exploit: with PV9, all non-voters abstain.

    A single Yes vote with 1% of stake achieves 100% ratio because
    non-voters are excluded from the denominator.
    """
    action_id = _make_action_id()
    pool_voter = Voter(role=VoterRole.STAKE_POOL, credential=_pool_id(1))

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                pool_voter: VotingProcedure(vote=Vote.YES),
            }
        },
        pool_stake={
            _pool_id(1): 100,  # 1% stake, votes Yes
            _pool_id(2): 4950,  # 49.5% stake, doesn't vote
            _pool_id(3): 4950,  # 49.5% stake, doesn't vote
        },
        current_protocol_version=(9, 0),  # Bootstrap phase
    )

    # With PV9, non-voters abstain -> denominator is just the 100 stake
    # ratio = 100 / 100 = 100% -> passes 51% threshold
    assert check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 4. PV10+ single Yes vote -> low ratio (fix working)
# ---------------------------------------------------------------------------


def test_pv10_single_yes_vote_low_ratio() -> None:
    """PV10+ fix: non-voters default to No, staying in denominator.

    The same scenario as test 3 but with PV10 -- now the single Yes vote
    only gets 1% ratio, which fails the 51% threshold.
    """
    action_id = _make_action_id()
    pool_voter = Voter(role=VoterRole.STAKE_POOL, credential=_pool_id(1))

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                pool_voter: VotingProcedure(vote=Vote.YES),
            }
        },
        pool_stake={
            _pool_id(1): 100,  # 1% stake, votes Yes
            _pool_id(2): 4950,  # 49.5% stake, doesn't vote -> No
            _pool_id(3): 4950,  # 49.5% stake, doesn't vote -> No
        },
        current_protocol_version=(10, 0),  # Post-bootstrap
    )

    # With PV10, non-voters default to No -> denominator is 10000
    # ratio = 100 / 10000 = 1% -> fails 51% threshold
    assert not check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 5. HardForkInitiation non-voters always abstain regardless of PV
# ---------------------------------------------------------------------------


def test_hardfork_nonvoters_always_abstain() -> None:
    """HardForkInitiation: non-voting pools always abstain, regardless of PV.

    Even at PV10+, non-voters on HardForkInitiation are excluded from
    the denominator (they abstain).
    """
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.HARD_FORK_INITIATION,
        protocol_version_major=10,
        reward_account_delegations={},
    )
    assert result == DefaultVote.ABSTAIN

    # Also at PV9
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.HARD_FORK_INITIATION,
        protocol_version_major=9,
        reward_account_delegations={},
    )
    assert result == DefaultVote.ABSTAIN


def test_hardfork_single_yes_passes_at_pv10() -> None:
    """HardForkInitiation with PV10: single voter with all non-voters abstaining.

    Since HardFork non-voters always abstain, only the single voter
    is in the denominator, giving 100% ratio.
    """
    action_id = _make_action_id()
    pool_voter = Voter(role=VoterRole.STAKE_POOL, credential=_pool_id(1))

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.HARD_FORK_INITIATION)},
        votes={
            action_id: {
                pool_voter: VotingProcedure(vote=Vote.YES),
            }
        },
        pool_stake={
            _pool_id(1): 100,
            _pool_id(2): 4950,
            _pool_id(3): 4950,
        },
        current_protocol_version=(10, 0),
    )

    # HardFork: non-voters abstain even at PV10
    # denominator = 100 (only the voter), yes = 100 -> 100%
    assert check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 6. Reward addr delegated to AlwaysAbstain -> pool excluded from denominator
# ---------------------------------------------------------------------------


def test_always_abstain_delegation_excludes_pool() -> None:
    """Pool reward addr delegated to AlwaysAbstain -> abstain (excluded from denominator)."""
    result = default_stake_pool_vote(
        pool_id=_pool_id(2),
        action_type=GovActionType.NO_CONFIDENCE,
        protocol_version_major=10,
        reward_account_delegations={
            _pool_id(2): DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
        },
    )
    assert result == DefaultVote.ABSTAIN


def test_always_abstain_delegation_ratification() -> None:
    """Stake-weighted: AlwaysAbstain pool excluded from denominator, helping Yes pass."""
    action_id = _make_action_id()
    pool_voter = Voter(role=VoterRole.STAKE_POOL, credential=_pool_id(1))

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                pool_voter: VotingProcedure(vote=Vote.YES),
            }
        },
        pool_stake={
            _pool_id(1): 600,  # Votes Yes
            _pool_id(2): 400,  # Doesn't vote, AlwaysAbstain -> excluded
        },
        current_protocol_version=(10, 0),
        reward_account_delegations={
            _pool_id(2): DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
        },
    )

    # denominator = 1000 - 400 (abstain) = 600, yes = 600 -> 100% -> passes
    assert check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 7. Reward addr delegated to AlwaysNoConfidence + NoConfidence action -> Yes
# ---------------------------------------------------------------------------


def test_always_no_confidence_on_no_confidence_action() -> None:
    """AlwaysNoConfidence delegation + NoConfidence action -> counts as Yes."""
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.NO_CONFIDENCE,
        protocol_version_major=10,
        reward_account_delegations={
            _pool_id(1): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
        },
    )
    assert result == DefaultVote.YES


def test_always_no_confidence_ratification_no_confidence_action() -> None:
    """AlwaysNoConfidence pools count as Yes for NoConfidence actions."""
    action_id = _make_action_id()

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={action_id: {}},  # No explicit votes
        pool_stake={
            _pool_id(1): 600,  # AlwaysNoConfidence -> Yes for NoConfidence
            _pool_id(2): 400,  # No delegation -> No
        },
        current_protocol_version=(10, 0),
        reward_account_delegations={
            _pool_id(1): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
        },
    )

    # denominator = 1000, yes = 600 -> 60% -> passes 51%
    assert check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 8. Reward addr delegated to AlwaysNoConfidence + other action -> No
# ---------------------------------------------------------------------------


def test_always_no_confidence_on_other_action() -> None:
    """AlwaysNoConfidence delegation + non-NoConfidence action -> counts as No."""
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.PARAMETER_CHANGE,
        protocol_version_major=10,
        reward_account_delegations={
            _pool_id(1): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
        },
    )
    assert result == DefaultVote.NO


def test_always_no_confidence_on_hard_fork() -> None:
    """AlwaysNoConfidence on HardForkInitiation -> Abstain (HardFork overrides)."""
    result = default_stake_pool_vote(
        pool_id=_pool_id(1),
        action_type=GovActionType.HARD_FORK_INITIATION,
        protocol_version_major=10,
        reward_account_delegations={
            _pool_id(1): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
        },
    )
    # HardFork override takes precedence over delegation
    assert result == DefaultVote.ABSTAIN


# ---------------------------------------------------------------------------
# 9. Mixed: some pools vote, some use defaults, verify correct ratio
# ---------------------------------------------------------------------------


def test_mixed_explicit_and_default_votes() -> None:
    """Mixed scenario: explicit votes + default votes from various delegations.

    Pool layout (total 10000 stake):
      pool1: 2000 stake, votes Yes explicitly
      pool2: 1500 stake, votes No explicitly
      pool3: 1000 stake, votes Abstain explicitly
      pool4: 2500 stake, no vote, AlwaysNoConfidence -> Yes (NoConfidence action)
      pool5: 1500 stake, no vote, AlwaysAbstain -> Abstain
      pool6: 1500 stake, no vote, no delegation -> No

    Expected:
      yes = 2000 + 2500 = 4500
      abstain = 1000 + 1500 = 2500
      total = 10000
      effective denominator = 10000 - 2500 = 7500
      ratio = 4500 / 7500 = 60% -> passes 51%
    """
    action_id = _make_action_id()

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                Voter(VoterRole.STAKE_POOL, _pool_id(1)): VotingProcedure(vote=Vote.YES),
                Voter(VoterRole.STAKE_POOL, _pool_id(2)): VotingProcedure(vote=Vote.NO),
                Voter(VoterRole.STAKE_POOL, _pool_id(3)): VotingProcedure(vote=Vote.ABSTAIN),
            }
        },
        pool_stake={
            _pool_id(1): 2000,
            _pool_id(2): 1500,
            _pool_id(3): 1000,
            _pool_id(4): 2500,
            _pool_id(5): 1500,
            _pool_id(6): 1500,
        },
        current_protocol_version=(10, 0),
        reward_account_delegations={
            _pool_id(4): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
            _pool_id(5): DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
            # pool6 has no delegation -> defaults to No
        },
    )

    assert check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


def test_mixed_votes_fails_threshold() -> None:
    """Mixed scenario where the ratio doesn't meet threshold.

    Pool layout (total 10000 stake):
      pool1: 1000 stake, votes Yes
      pool2: 3000 stake, votes No
      pool3: 1000 stake, AlwaysNoConfidence -> Yes (NoConfidence)
      pool4: 5000 stake, no delegation -> No

    yes = 1000 + 1000 = 2000
    abstain = 0
    denominator = 10000
    ratio = 2000 / 10000 = 20% -> fails 51%
    """
    action_id = _make_action_id()

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                Voter(VoterRole.STAKE_POOL, _pool_id(1)): VotingProcedure(vote=Vote.YES),
                Voter(VoterRole.STAKE_POOL, _pool_id(2)): VotingProcedure(vote=Vote.NO),
            }
        },
        pool_stake={
            _pool_id(1): 1000,
            _pool_id(2): 3000,
            _pool_id(3): 1000,
            _pool_id(4): 5000,
        },
        current_protocol_version=(10, 0),
        reward_account_delegations={
            _pool_id(3): DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE),
        },
    )

    assert not check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


# ---------------------------------------------------------------------------
# 10. All pools abstain -> denominator is 0, ratio is 0 (safe division)
# ---------------------------------------------------------------------------


def test_all_pools_abstain_safe_division() -> None:
    """When all pools abstain, denominator is 0 and ratification fails safely."""
    action_id = _make_action_id()

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={
            action_id: {
                Voter(VoterRole.STAKE_POOL, _pool_id(1)): VotingProcedure(vote=Vote.ABSTAIN),
            }
        },
        pool_stake={
            _pool_id(1): 5000,  # Votes Abstain explicitly
            _pool_id(2): 5000,  # No vote, AlwaysAbstain -> Abstain
        },
        current_protocol_version=(10, 0),
        reward_account_delegations={
            _pool_id(2): DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
        },
    )

    # denominator = 10000 - 10000 = 0 -> ratification should NOT crash
    # With denominator 0, threshold check returns False -> action not ratified
    assert not check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())


def test_all_pools_abstain_pv9() -> None:
    """PV9: all pools abstain by default (bootstrap), no explicit votes -> safe."""
    action_id = _make_action_id()

    gov_state = GovernanceState(
        proposals={action_id: _make_proposal(GovActionType.NO_CONFIDENCE)},
        votes={action_id: {}},
        pool_stake={
            _pool_id(1): 5000,
            _pool_id(2): 5000,
        },
        current_protocol_version=(9, 0),
    )

    # PV9: all non-voters abstain -> denominator = 0 -> fails safely
    assert not check_ratification(action_id, gov_state, ConwayProtocolParams(), _spo_threshold())
