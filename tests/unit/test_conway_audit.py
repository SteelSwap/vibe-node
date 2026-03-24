"""Conway-era audit gap tests — 7 tests from the Haskell test audit.

Tests cover missing governance validation and property checks:
    9.  Stake-weighted DRep voting
    10. SPO voting role
    11. Committee quorum (committeeMinSize)
    12. Hard fork initiation validation
    13. Treasury withdrawal validation
    14. No confidence effects
    15. DRep activity tracking

Spec references:
    - Conway ledger formal spec, Section 5 (Governance)
    - Conway ledger formal spec, Section 6 (Ratification)
    - CIP-1694 (on-chain governance)
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Ratify.hs``
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Gov.hs``
"""

from __future__ import annotations

import hashlib

from vibe.cardano.ledger.conway import (
    _is_drep_active,
    apply_no_confidence,
    check_ratification,
    get_active_dreps,
    validate_hard_fork_initiation,
    validate_spo_vote,
    validate_treasury_withdrawals,
    validate_voting_procedures,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    GovAction,
    GovActionId,
    GovActionType,
    GovernanceState,
    ProposalProcedure,
    Vote,
    Voter,
    VoterRole,
    VotingProcedure,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


TEST_PARAMS = ConwayProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    drep_deposit=500_000_000,
    drep_activity=20,
    gov_action_lifetime=6,
    gov_action_deposit=100_000_000_000,
    committee_min_size=7,
    committee_max_term_length=146,
)


def make_credential(seed: int = 0) -> bytes:
    """Create a deterministic 28-byte credential hash."""
    return hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()


def make_tx_id_bytes(seed: int = 0) -> bytes:
    """Create a deterministic 32-byte tx ID."""
    return hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()


def make_anchor(seed: int = 0) -> Anchor:
    """Create a test anchor."""
    data_hash = hashlib.blake2b(f"anchor-{seed}".encode(), digest_size=32).digest()
    return Anchor(url=f"https://example.com/proposal-{seed}", data_hash=data_hash)


def make_reward_addr(seed: int = 0) -> bytes:
    """Create a 29-byte reward address."""
    return b"\xe0" + make_credential(seed)


def make_gov_action_id(seed: int = 0) -> GovActionId:
    """Create a test governance action ID."""
    return GovActionId(tx_id=make_tx_id_bytes(seed), gov_action_index=0)


def make_proposal(
    seed: int = 0,
    action_type: GovActionType = GovActionType.INFO_ACTION,
    deposit: int | None = None,
    payload=None,
) -> ProposalProcedure:
    """Create a test proposal procedure."""
    if deposit is None:
        deposit = TEST_PARAMS.gov_action_deposit
    return ProposalProcedure(
        deposit=deposit,
        return_addr=make_reward_addr(seed),
        gov_action=GovAction(action_type=action_type, payload=payload),
        anchor=make_anchor(seed),
    )


# ---------------------------------------------------------------------------
# Test 9: Stake-weighted DRep voting
# ---------------------------------------------------------------------------


class TestStakeWeightedDRepVoting:
    """Test that ratification weights DRep votes by delegated stake,
    not just counts them.

    Spec ref: Conway formal spec, Section 6 — DRep votes are weighted
    by delegated stake.
    Haskell ref: ``ratifyAction`` DRep stake calculation in
        ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_large_stake_outweighs_many_small(self):
        """DRep with 1M stake voting Yes should outweigh 10 DReps with 1000 stake voting No.

        This demonstrates that ratification is stake-weighted, not head-count.
        """
        # Create a parameter change proposal (requires 2/3 DRep threshold)
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        # 1 big DRep with 1M stake
        big_drep = make_credential(100)

        # 10 small DReps with 1000 stake each
        small_dreps = [make_credential(i) for i in range(10)]

        dreps_registry = {big_drep: 500_000_000}
        drep_stake = {big_drep: 1_000_000}  # 1M lovelace
        for sd in small_dreps:
            dreps_registry[sd] = 500_000_000
            drep_stake[sd] = 1_000  # 1000 lovelace each

        # Total stake: 1M + 10*1K = 1,010,000
        # big_drep votes YES (1M), small_dreps vote NO (10K total)
        # YES stake ratio = 1M / 1,010,000 ~ 99% >> 2/3

        # CC members to satisfy CC threshold (need >= committee_min_size=7)
        committee = {make_credential(200 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps=dreps_registry,
            drep_stake=drep_stake,
            committee=committee,
            votes={action_id: {}},
        )

        # Big DRep votes YES
        state.votes[action_id][Voter(VoterRole.DREP, big_drep)] = VotingProcedure(vote=Vote.YES)

        # All small DReps vote NO
        for sd in small_dreps:
            state.votes[action_id][Voter(VoterRole.DREP, sd)] = VotingProcedure(vote=Vote.NO)

        # All CC members vote YES
        for cc_cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        # Should pass because 1M YES >> 10K NO in stake weight
        assert check_ratification(action_id, state, TEST_PARAMS)

    def test_many_small_cannot_override_stake(self):
        """10 small-stake DReps voting Yes should not outweigh 1 large-stake DRep voting No."""
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        big_drep = make_credential(100)
        small_dreps = [make_credential(i) for i in range(10)]

        dreps_registry = {big_drep: 500_000_000}
        drep_stake = {big_drep: 1_000_000}
        for sd in small_dreps:
            dreps_registry[sd] = 500_000_000
            drep_stake[sd] = 1_000

        committee = {make_credential(200 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps=dreps_registry,
            drep_stake=drep_stake,
            committee=committee,
            votes={action_id: {}},
        )

        # Big DRep votes NO
        state.votes[action_id][Voter(VoterRole.DREP, big_drep)] = VotingProcedure(vote=Vote.NO)

        # All small DReps vote YES
        for sd in small_dreps:
            state.votes[action_id][Voter(VoterRole.DREP, sd)] = VotingProcedure(vote=Vote.YES)

        # All CC members vote YES
        for cc_cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        # Only 10K YES out of 1,010,000 total = ~1% — not enough for 2/3
        assert not check_ratification(action_id, state, TEST_PARAMS)

    def test_fallback_to_count_without_stake_data(self):
        """Without drep_stake, ratification should fall back to count-based."""
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        drep1 = make_credential(1)
        drep2 = make_credential(2)
        drep3 = make_credential(3)

        # Need >= committee_min_size (7) CC members
        committee = {make_credential(10 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={drep1: 500_000_000, drep2: 500_000_000, drep3: 500_000_000},
            committee=committee,
            votes={action_id: {}},
        )

        # 2 of 3 DReps vote YES (2/3 threshold)
        state.votes[action_id] = {
            Voter(VoterRole.DREP, drep1): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep2): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep3): VotingProcedure(vote=Vote.NO),
        }
        # All CC members vote YES
        for cc_cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        assert check_ratification(action_id, state, TEST_PARAMS)


# ---------------------------------------------------------------------------
# Test 10: SPO voting role
# ---------------------------------------------------------------------------


class TestSPOVotingRole:
    """Test that stake pool operators can vote on governance actions,
    specifically HardForkInitiation which requires SPO votes.

    Spec ref: Conway formal spec, Section 6 — SPO voting thresholds.
    Haskell ref: SPO vote handling in ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_spo_vote_on_hard_fork(self):
        """SPOs should be able to vote on HardForkInitiation."""
        action_id = make_gov_action_id(0)
        proposal = make_proposal(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(10, 0),
        )

        spo1 = make_credential(1)
        spo2 = make_credential(2)
        drep1 = make_credential(10)
        drep2 = make_credential(11)
        drep3 = make_credential(12)

        # Need >= committee_min_size (7) CC members
        committee = {make_credential(50 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={drep1: 500_000_000, drep2: 500_000_000, drep3: 500_000_000},
            registered_pools={spo1, spo2},
            pool_stake={spo1: 500_000, spo2: 500_000},
            committee=committee,
            votes={action_id: {}},
        )

        # SPOs vote YES (1/2 threshold for hard fork)
        state.votes[action_id][Voter(VoterRole.STAKE_POOL, spo1)] = VotingProcedure(vote=Vote.YES)
        state.votes[action_id][Voter(VoterRole.STAKE_POOL, spo2)] = VotingProcedure(vote=Vote.YES)

        # DReps vote YES
        state.votes[action_id][Voter(VoterRole.DREP, drep1)] = VotingProcedure(vote=Vote.YES)
        state.votes[action_id][Voter(VoterRole.DREP, drep2)] = VotingProcedure(vote=Vote.YES)

        # All CC members vote YES
        for cc_cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        assert check_ratification(action_id, state, TEST_PARAMS)

    def test_unregistered_spo_vote_rejected(self):
        """SPO not in registered_pools should fail validation."""
        spo_cred = make_credential(99)
        state = GovernanceState(
            registered_pools={make_credential(1), make_credential(2)},
        )

        voter = Voter(role=VoterRole.STAKE_POOL, credential=spo_cred)
        errors = validate_spo_vote(voter, state)
        assert any("VoterNotAuthorized" in e for e in errors)

    def test_registered_spo_vote_passes(self):
        """Registered SPO should pass vote validation."""
        spo_cred = make_credential(1)
        state = GovernanceState(
            registered_pools={spo_cred},
        )

        voter = Voter(role=VoterRole.STAKE_POOL, credential=spo_cred)
        errors = validate_spo_vote(voter, state)
        assert errors == []

    def test_spo_vote_in_voting_procedures(self):
        """SPO vote validation should be integrated into validate_voting_procedures."""
        spo_cred = make_credential(99)
        state, action_ids = _make_gov_state_with_proposals(1)
        state.registered_pools = {make_credential(1)}  # spo_cred NOT registered

        voter = Voter(role=VoterRole.STAKE_POOL, credential=spo_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert any("VoterNotAuthorized" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 11: Committee quorum (committeeMinSize)
# ---------------------------------------------------------------------------


class TestCommitteeQuorum:
    """Test that ratification checks fail if fewer than committeeMinSize
    CC members exist.

    Spec ref: Conway formal spec, ``committeeMinSize`` parameter.
    Haskell ref: ``ratifyAction`` committee size check in
        ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_insufficient_committee_size_fails(self):
        """Ratification should fail when committee has fewer than committeeMinSize members."""
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        drep1 = make_credential(1)
        drep2 = make_credential(2)
        drep3 = make_credential(3)

        # Only 3 CC members, but committeeMinSize is 7
        cc1 = make_credential(10)
        cc2 = make_credential(11)
        cc3 = make_credential(12)

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={drep1: 500_000_000, drep2: 500_000_000, drep3: 500_000_000},
            committee={cc1: 1000, cc2: 1000, cc3: 1000},
            votes={action_id: {}},
        )

        # All DReps vote YES
        state.votes[action_id] = {
            Voter(VoterRole.DREP, drep1): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep2): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep3): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc1): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc2): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc3): VotingProcedure(vote=Vote.YES),
        }

        # Should fail: only 3 CC members, need 7
        assert not check_ratification(action_id, state, TEST_PARAMS)

    def test_sufficient_committee_size_passes(self):
        """Ratification should pass when committee has enough members."""
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        dreps = {make_credential(i): 500_000_000 for i in range(3)}

        # 7 CC members (matches committeeMinSize)
        committee = {make_credential(100 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps=dreps,
            committee=committee,
            votes={action_id: {}},
        )

        # All DReps vote YES
        for cred in dreps:
            state.votes[action_id][Voter(VoterRole.DREP, cred)] = VotingProcedure(vote=Vote.YES)

        # All CC members vote YES (need 2/3 = 5 of 7)
        for cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        assert check_ratification(action_id, state, TEST_PARAMS)


# ---------------------------------------------------------------------------
# Test 12: Hard fork initiation validation
# ---------------------------------------------------------------------------


class TestHardForkInitiationValidation:
    """Test specific validation for HardForkInitiation: must specify
    a valid target protocol version exactly one major version higher.

    Spec ref: Conway formal spec, HardForkInitiation validation.
    Haskell ref: ``HardForkInitiation`` validation in
        ``Cardano.Ledger.Conway.Rules.Gov``
    """

    def test_valid_hard_fork_version(self):
        """Valid hard fork: current (9,0) -> target (10,0)."""
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(10, 0),
        )
        state = GovernanceState(current_protocol_version=(9, 0))
        errors = validate_hard_fork_initiation(action, state)
        assert errors == []

    def test_same_major_version_fails(self):
        """Target with same major version should fail."""
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(9, 1),
        )
        state = GovernanceState(current_protocol_version=(9, 0))
        errors = validate_hard_fork_initiation(action, state)
        assert any("VersionMismatch" in e for e in errors)

    def test_skip_major_version_fails(self):
        """Skipping a major version should fail."""
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(11, 0),
        )
        state = GovernanceState(current_protocol_version=(9, 0))
        errors = validate_hard_fork_initiation(action, state)
        assert any("VersionMismatch" in e for e in errors)

    def test_missing_version_payload_fails(self):
        """HardForkInitiation without a version payload should fail."""
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=None,
        )
        state = GovernanceState(current_protocol_version=(9, 0))
        errors = validate_hard_fork_initiation(action, state)
        assert any("MissingVersion" in e for e in errors)

    def test_non_hard_fork_action_ignored(self):
        """Non-HardForkInitiation actions should return no errors."""
        action = GovAction(action_type=GovActionType.INFO_ACTION)
        state = GovernanceState()
        errors = validate_hard_fork_initiation(action, state)
        assert errors == []


# ---------------------------------------------------------------------------
# Test 13: Treasury withdrawal validation
# ---------------------------------------------------------------------------


class TestTreasuryWithdrawalValidation:
    """Test that TreasuryWithdrawals validates withdrawal amounts are positive
    and destinations are valid reward addresses.

    Spec ref: Conway formal spec, TreasuryWithdrawals validation.
    Haskell ref: ``TreasuryWithdrawals`` validation in
        ``Cardano.Ledger.Conway.Rules.Gov``
    """

    def test_valid_withdrawal(self):
        """Valid treasury withdrawal with positive amounts and good addresses."""
        addr = make_reward_addr(0)
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={addr: 1_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []

    def test_zero_amount_fails(self):
        """Zero withdrawal amount should fail."""
        addr = make_reward_addr(0)
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={addr: 0},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("NonPositiveAmount" in e for e in errors)

    def test_negative_amount_fails(self):
        """Negative withdrawal amount should fail."""
        addr = make_reward_addr(0)
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={addr: -100},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("NonPositiveAmount" in e for e in errors)

    def test_invalid_address_fails(self):
        """Non-29-byte reward address should fail."""
        bad_addr = b"\x00" * 10
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={bad_addr: 1_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("InvalidAddr" in e for e in errors)

    def test_empty_payload_fails(self):
        """Treasury withdrawal with None payload should fail."""
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload=None,
        )
        errors = validate_treasury_withdrawals(action)
        assert any("TreasuryWithdrawalsEmpty" in e for e in errors)

    def test_multiple_withdrawals(self):
        """Multiple valid withdrawals in one action should pass."""
        addr1 = make_reward_addr(0)
        addr2 = make_reward_addr(1)
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={addr1: 1_000_000, addr2: 2_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []


# ---------------------------------------------------------------------------
# Test 14: No confidence effects
# ---------------------------------------------------------------------------


class TestNoConfidenceEffects:
    """Test that when NoConfidence passes, the constitutional committee
    is dissolved and CC-required actions cannot be ratified.

    Spec ref: Conway formal spec, NoConfidence enactment.
    Haskell ref: ``enactNoConfidence`` in
        ``Cardano.Ledger.Conway.Rules.Enact``
    """

    def test_no_confidence_dissolves_committee(self):
        """After NoConfidence, the committee should be empty."""
        cc1 = make_credential(10)
        cc2 = make_credential(11)
        cc3 = make_credential(12)

        state = GovernanceState(
            committee={cc1: 1000, cc2: 1000, cc3: 1000},
        )

        new_state = apply_no_confidence(state)
        assert len(new_state.committee) == 0

    def test_cc_required_action_fails_after_no_confidence(self):
        """After NoConfidence, actions requiring CC approval should not ratify."""
        # Create a ParameterChange (requires CC threshold)
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        dreps = {make_credential(i): 500_000_000 for i in range(3)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps=dreps,
            committee={},  # No committee (dissolved by NoConfidence)
            votes={action_id: {}},
        )

        # All DReps vote YES
        for cred in dreps:
            state.votes[action_id][Voter(VoterRole.DREP, cred)] = VotingProcedure(vote=Vote.YES)

        # Should fail: ParameterChange needs CC, but committee is empty
        # (committeeMinSize check fails: 0 < 7)
        assert not check_ratification(action_id, state, TEST_PARAMS)

    def test_no_confidence_does_not_affect_dreps(self):
        """NoConfidence should only dissolve the committee, not DReps."""
        drep_cred = make_credential(1)
        cc_cred = make_credential(10)

        state = GovernanceState(
            dreps={drep_cred: 500_000_000},
            committee={cc_cred: 1000},
        )

        new_state = apply_no_confidence(state)
        assert drep_cred in new_state.dreps
        assert len(new_state.committee) == 0


# ---------------------------------------------------------------------------
# Test 15: DRep activity tracking
# ---------------------------------------------------------------------------


class TestDRepActivityTracking:
    """Test that DReps who haven't voted within drep_activity epochs are
    considered inactive and excluded from threshold calculations.

    Spec ref: Conway formal spec, ``drepActivity`` parameter.
    Haskell ref: ``isDRepExpiry`` in ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_active_drep_included(self):
        """DRep who voted recently should be considered active."""
        cred = make_credential(1)
        state = GovernanceState(
            dreps={cred: 500_000_000},
            drep_activity_epoch={cred: 90},  # Last active at epoch 90
        )

        # Current epoch 100, drep_activity=20 => 100-90=10 <= 20 => active
        assert _is_drep_active(cred, state, TEST_PARAMS, current_epoch=100)

    def test_inactive_drep_excluded(self):
        """DRep who hasn't voted in drep_activity epochs should be inactive."""
        cred = make_credential(1)
        state = GovernanceState(
            dreps={cred: 500_000_000},
            drep_activity_epoch={cred: 50},  # Last active at epoch 50
        )

        # Current epoch 100, drep_activity=20 => 100-50=50 > 20 => inactive
        assert not _is_drep_active(cred, state, TEST_PARAMS, current_epoch=100)

    def test_get_active_dreps(self):
        """get_active_dreps should return only active DReps."""
        active_cred = make_credential(1)
        inactive_cred = make_credential(2)

        state = GovernanceState(
            dreps={active_cred: 500_000_000, inactive_cred: 500_000_000},
            drep_activity_epoch={active_cred: 90, inactive_cred: 50},
        )

        active = get_active_dreps(state, TEST_PARAMS, current_epoch=100)
        assert active_cred in active
        assert inactive_cred not in active

    def test_inactive_drep_excluded_from_ratification(self):
        """Inactive DReps should be excluded from threshold denominator.

        Since check_ratification doesn't take current_epoch, the activity
        check without current_epoch defaults to 'active'. We test the
        mechanism through _is_drep_active and get_active_dreps directly,
        and verify here that the activity data at least does not break
        the standard count-based flow.
        """
        action_id = make_gov_action_id(0)
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)

        active_drep = make_credential(1)

        # Use committee with enough members
        committee = {make_credential(100 + i): 1000 for i in range(7)}

        # Only one DRep (the active one), so 1/1 = 100% >= 2/3
        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={active_drep: 500_000_000},
            drep_activity_epoch={active_drep: 95},
            committee=committee,
            votes={action_id: {}},
        )

        # active_drep votes YES
        state.votes[action_id][Voter(VoterRole.DREP, active_drep)] = VotingProcedure(vote=Vote.YES)

        # All CC members vote YES
        for cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        result = check_ratification(action_id, state, TEST_PARAMS)
        assert result

        # Now verify that _is_drep_active properly distinguishes:
        inactive_drep = make_credential(2)
        assert _is_drep_active(active_drep, state, TEST_PARAMS, current_epoch=100)
        # inactive drep with old activity epoch
        state2 = GovernanceState(
            dreps={inactive_drep: 500_000_000},
            drep_activity_epoch={inactive_drep: 50},
        )
        assert not _is_drep_active(inactive_drep, state2, TEST_PARAMS, current_epoch=100)

    def test_no_activity_data_assumes_active(self):
        """DReps without activity tracking data should be assumed active."""
        cred = make_credential(1)
        state = GovernanceState(
            dreps={cred: 500_000_000},
            # No drep_activity_epoch data
        )

        assert _is_drep_active(cred, state, TEST_PARAMS, current_epoch=100)

    def test_drep_at_activity_boundary(self):
        """DRep exactly at the activity boundary should still be active."""
        cred = make_credential(1)
        state = GovernanceState(
            dreps={cred: 500_000_000},
            drep_activity_epoch={cred: 80},
        )

        # 100 - 80 = 20 == drep_activity => still active (<=)
        assert _is_drep_active(cred, state, TEST_PARAMS, current_epoch=100)


# ---------------------------------------------------------------------------
# Helper used by SPO test
# ---------------------------------------------------------------------------


def _make_gov_state_with_proposals(
    num_proposals: int = 1,
) -> tuple[GovernanceState, list[GovActionId]]:
    """Create a governance state with active proposals."""
    state = GovernanceState()
    ids = []
    for i in range(num_proposals):
        action_id = make_gov_action_id(i)
        state.proposals[action_id] = make_proposal(i)
        state.votes[action_id] = {}
        ids.append(action_id)
    return state, ids
