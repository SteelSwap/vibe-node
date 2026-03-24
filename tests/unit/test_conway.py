"""Tests for Conway-era governance rules (proposals, voting, DRep delegation).

Tests cover the Conway governance transition rules:
    - Governance action types and proposal validation
    - DRep registration, deregistration, update
    - Vote delegation (DelegVote)
    - Voting procedure validation
    - Ratification threshold checks
    - Proposal expiry
    - Hypothesis property tests

Spec references:
    - Conway ledger formal spec, Section 5 (Governance)
    - Conway ledger formal spec, Section 6 (Ratification)
    - CIP-1694 (on-chain governance)
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Gov.hs``
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/GovCert.hs``
"""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.ledger.conway import (
    ConwayGovernanceError,
    ConwayValidationError,
    _threshold_met,
    check_ratification,
    expire_proposals,
    process_conway_certificate,
    process_deleg_vote,
    process_drep_deregistration,
    process_drep_registration,
    process_drep_update,
    validate_proposal,
    validate_proposals,
    validate_voting_procedures,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    DelegVote,
    DRep,
    DRepDeregistration,
    DRepRegistration,
    DRepType,
    DRepUpdate,
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
    return GovActionId(
        tx_id=make_tx_id_bytes(seed),
        gov_action_index=0,
    )


def make_proposal(
    seed: int = 0,
    action_type: GovActionType = GovActionType.INFO_ACTION,
    deposit: int | None = None,
) -> ProposalProcedure:
    """Create a test proposal procedure."""
    if deposit is None:
        deposit = TEST_PARAMS.gov_action_deposit
    return ProposalProcedure(
        deposit=deposit,
        return_addr=make_reward_addr(seed),
        gov_action=GovAction(action_type=action_type),
        anchor=make_anchor(seed),
    )


def make_gov_state_with_proposals(
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


# ---------------------------------------------------------------------------
# Governance action type tests
# ---------------------------------------------------------------------------


class TestGovActionTypes:
    """Tests for governance action type enumeration."""

    def test_all_action_types_defined(self):
        """All seven Conway governance action types should be defined."""
        assert len(GovActionType) == 7

    def test_info_action_value(self):
        """InfoAction should have value 6."""
        assert GovActionType.INFO_ACTION == 6

    def test_parameter_change_value(self):
        """ParameterChange should have value 0."""
        assert GovActionType.PARAMETER_CHANGE == 0


# ---------------------------------------------------------------------------
# Proposal validation tests
# ---------------------------------------------------------------------------


class TestProposalValidation:
    """Tests for governance proposal validation."""

    def test_valid_proposal(self):
        """Well-formed proposal should pass."""
        proposal = make_proposal()
        state = GovernanceState()
        errors = validate_proposal(proposal, TEST_PARAMS, state)
        assert errors == []

    def test_wrong_deposit(self):
        """Proposal with wrong deposit should fail."""
        proposal = make_proposal(deposit=1_000)
        state = GovernanceState()
        errors = validate_proposal(proposal, TEST_PARAMS, state)
        assert any("ProposalDepositMismatch" in e for e in errors)

    def test_invalid_return_addr(self):
        """Proposal with wrong-size return address should fail."""
        proposal = ProposalProcedure(
            deposit=TEST_PARAMS.gov_action_deposit,
            return_addr=b"\x00" * 10,  # Wrong size
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=make_anchor(),
        )
        state = GovernanceState()
        errors = validate_proposal(proposal, TEST_PARAMS, state)
        assert any("ProposalReturnAddrInvalid" in e for e in errors)

    def test_empty_anchor_url(self):
        """Proposal with empty anchor URL should fail."""
        proposal = ProposalProcedure(
            deposit=TEST_PARAMS.gov_action_deposit,
            return_addr=make_reward_addr(),
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=Anchor(url="", data_hash=b"\x00" * 32),
        )
        state = GovernanceState()
        errors = validate_proposal(proposal, TEST_PARAMS, state)
        assert any("ProposalAnchorEmpty" in e for e in errors)

    def test_invalid_anchor_hash(self):
        """Proposal with wrong-size anchor hash should fail."""
        proposal = ProposalProcedure(
            deposit=TEST_PARAMS.gov_action_deposit,
            return_addr=make_reward_addr(),
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=Anchor(url="https://example.com", data_hash=b"\x00" * 16),
        )
        state = GovernanceState()
        errors = validate_proposal(proposal, TEST_PARAMS, state)
        assert any("ProposalAnchorHashInvalid" in e for e in errors)

    def test_validate_multiple_proposals(self):
        """Multiple proposals should be validated independently."""
        good = make_proposal(seed=0)
        bad = make_proposal(seed=1, deposit=0)
        state = GovernanceState()
        errors = validate_proposals([good, bad], TEST_PARAMS, state)
        assert len(errors) >= 1
        assert any("Proposal[1]" in e for e in errors)


# ---------------------------------------------------------------------------
# DRep registration tests
# ---------------------------------------------------------------------------


class TestDRepRegistration:
    """Tests for DRep registration certificate processing."""

    def test_register_new_drep(self):
        """Registering a new DRep should succeed."""
        cred = make_credential(1)
        cert = DRepRegistration(
            credential=cred,
            deposit=TEST_PARAMS.drep_deposit,
            anchor=make_anchor(),
        )
        state = GovernanceState()
        new_state = process_drep_registration(cert, state, TEST_PARAMS)
        assert cred in new_state.dreps
        assert new_state.dreps[cred] == TEST_PARAMS.drep_deposit

    def test_register_already_registered_fails(self):
        """Registering an already-registered DRep should fail."""
        cred = make_credential(1)
        state = GovernanceState(dreps={cred: TEST_PARAMS.drep_deposit})
        cert = DRepRegistration(
            credential=cred,
            deposit=TEST_PARAMS.drep_deposit,
        )
        with pytest.raises(ConwayGovernanceError, match="DRepAlreadyRegistered"):
            process_drep_registration(cert, state, TEST_PARAMS)

    def test_wrong_deposit_fails(self):
        """Registration with wrong deposit amount should fail."""
        cred = make_credential(1)
        cert = DRepRegistration(
            credential=cred,
            deposit=1_000,  # Wrong
        )
        state = GovernanceState()
        with pytest.raises(ConwayGovernanceError, match="DRepDepositMismatch"):
            process_drep_registration(cert, state, TEST_PARAMS)


# ---------------------------------------------------------------------------
# DRep deregistration tests
# ---------------------------------------------------------------------------


class TestDRepDeregistration:
    """Tests for DRep deregistration certificate processing."""

    def test_deregister_registered_drep(self):
        """Deregistering a registered DRep should succeed."""
        cred = make_credential(1)
        state = GovernanceState(dreps={cred: TEST_PARAMS.drep_deposit})
        cert = DRepDeregistration(
            credential=cred,
            deposit_refund=TEST_PARAMS.drep_deposit,
        )
        new_state = process_drep_deregistration(cert, state)
        assert cred not in new_state.dreps

    def test_deregister_unregistered_fails(self):
        """Deregistering an unregistered DRep should fail."""
        cred = make_credential(1)
        cert = DRepDeregistration(
            credential=cred,
            deposit_refund=TEST_PARAMS.drep_deposit,
        )
        state = GovernanceState()
        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_drep_deregistration(cert, state)

    def test_wrong_refund_amount_fails(self):
        """Deregistration with wrong refund amount should fail."""
        cred = make_credential(1)
        state = GovernanceState(dreps={cred: TEST_PARAMS.drep_deposit})
        cert = DRepDeregistration(
            credential=cred,
            deposit_refund=1_000,
        )
        with pytest.raises(ConwayGovernanceError, match="DRepDepositRefundMismatch"):
            process_drep_deregistration(cert, state)

    def test_deregister_removes_delegations(self):
        """Deregistering a DRep should clean up delegations to that DRep."""
        drep_cred = make_credential(1)
        delegator_cred = make_credential(2)
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)

        state = GovernanceState(
            dreps={drep_cred: TEST_PARAMS.drep_deposit},
            drep_delegations={delegator_cred: drep},
        )
        cert = DRepDeregistration(
            credential=drep_cred,
            deposit_refund=TEST_PARAMS.drep_deposit,
        )
        new_state = process_drep_deregistration(cert, state)
        assert delegator_cred not in new_state.drep_delegations


# ---------------------------------------------------------------------------
# DRep update tests
# ---------------------------------------------------------------------------


class TestDRepUpdate:
    """Tests for DRep update certificate processing."""

    def test_update_registered_drep(self):
        """Updating a registered DRep should succeed (no state change)."""
        cred = make_credential(1)
        state = GovernanceState(dreps={cred: TEST_PARAMS.drep_deposit})
        cert = DRepUpdate(credential=cred, anchor=make_anchor())
        new_state = process_drep_update(cert, state)
        assert cred in new_state.dreps

    def test_update_unregistered_fails(self):
        """Updating an unregistered DRep should fail."""
        cred = make_credential(1)
        cert = DRepUpdate(credential=cred)
        state = GovernanceState()
        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_drep_update(cert, state)


# ---------------------------------------------------------------------------
# Vote delegation tests
# ---------------------------------------------------------------------------


class TestDelegVote:
    """Tests for DelegVote certificate processing."""

    def test_delegate_to_registered_drep(self):
        """Delegating to a registered DRep should succeed."""
        drep_cred = make_credential(1)
        delegator_cred = make_credential(2)

        state = GovernanceState(dreps={drep_cred: TEST_PARAMS.drep_deposit})
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)
        cert = DelegVote(credential=delegator_cred, drep=drep)

        new_state = process_deleg_vote(cert, state, registered_credentials={delegator_cred})
        assert delegator_cred in new_state.drep_delegations
        assert new_state.drep_delegations[delegator_cred] == drep

    def test_delegate_unregistered_credential_fails(self):
        """Delegating with unregistered stake credential should fail."""
        drep_cred = make_credential(1)
        delegator_cred = make_credential(2)

        state = GovernanceState(dreps={drep_cred: TEST_PARAMS.drep_deposit})
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)
        cert = DelegVote(credential=delegator_cred, drep=drep)

        with pytest.raises(ConwayGovernanceError, match="DelegVoteNotRegistered"):
            process_deleg_vote(cert, state, registered_credentials=set())

    def test_delegate_to_unregistered_drep_fails(self):
        """Delegating to an unregistered DRep (key/script) should fail."""
        drep_cred = make_credential(1)
        delegator_cred = make_credential(2)

        state = GovernanceState()  # No DReps registered
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)
        cert = DelegVote(credential=delegator_cred, drep=drep)

        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_deleg_vote(cert, state, registered_credentials={delegator_cred})

    def test_delegate_to_always_abstain(self):
        """Delegating to AlwaysAbstain should succeed without DRep registration."""
        delegator_cred = make_credential(2)
        state = GovernanceState()
        drep = DRep(drep_type=DRepType.ALWAYS_ABSTAIN)
        cert = DelegVote(credential=delegator_cred, drep=drep)

        new_state = process_deleg_vote(cert, state, registered_credentials={delegator_cred})
        assert new_state.drep_delegations[delegator_cred].drep_type == DRepType.ALWAYS_ABSTAIN

    def test_delegate_to_always_no_confidence(self):
        """Delegating to AlwaysNoConfidence should succeed."""
        delegator_cred = make_credential(2)
        state = GovernanceState()
        drep = DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE)
        cert = DelegVote(credential=delegator_cred, drep=drep)

        new_state = process_deleg_vote(cert, state, registered_credentials={delegator_cred})
        assert (
            new_state.drep_delegations[delegator_cred].drep_type == DRepType.ALWAYS_NO_CONFIDENCE
        )


# ---------------------------------------------------------------------------
# Certificate dispatch tests
# ---------------------------------------------------------------------------


class TestCertificateDispatch:
    """Tests for process_conway_certificate dispatch."""

    def test_dispatch_drep_registration(self):
        """Should route DRepRegistration correctly."""
        cred = make_credential(1)
        cert = DRepRegistration(credential=cred, deposit=TEST_PARAMS.drep_deposit)
        state = GovernanceState()
        new_state = process_conway_certificate(cert, state, TEST_PARAMS)
        assert cred in new_state.dreps

    def test_dispatch_unknown_type_raises(self):
        """Unrecognized certificate type should raise TypeError."""
        with pytest.raises(TypeError, match="Unrecognized"):
            process_conway_certificate("not_a_cert", GovernanceState(), TEST_PARAMS)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Voting validation tests
# ---------------------------------------------------------------------------


class TestVotingValidation:
    """Tests for voting procedure validation."""

    def test_valid_drep_vote(self):
        """DRep voting on an existing proposal should pass."""
        drep_cred = make_credential(1)
        state, action_ids = make_gov_state_with_proposals(1)
        state.dreps[drep_cred] = TEST_PARAMS.drep_deposit

        voter = Voter(role=VoterRole.DREP, credential=drep_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert errors == []

    def test_unregistered_drep_vote_fails(self):
        """Unregistered DRep voting should fail."""
        drep_cred = make_credential(1)
        state, action_ids = make_gov_state_with_proposals(1)
        # drep_cred is NOT in state.dreps

        voter = Voter(role=VoterRole.DREP, credential=drep_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert any("VoterNotAuthorized" in e for e in errors)

    def test_cc_member_vote(self):
        """CC member voting should pass when in committee."""
        cc_cred = make_credential(10)
        state, action_ids = make_gov_state_with_proposals(1)
        state.committee[cc_cred] = 100  # expires at epoch 100

        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=cc_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert errors == []

    def test_expired_cc_member_vote_fails(self):
        """Expired CC member should fail."""
        cc_cred = make_credential(10)
        state, action_ids = make_gov_state_with_proposals(1)
        state.committee[cc_cred] = 5  # expired at epoch 5

        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=cc_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(
            procedures,
            state,
            10,
            TEST_PARAMS,  # current epoch 10 > expiry 5
        )
        assert any("VoterExpired" in e for e in errors)

    def test_cc_not_in_committee_fails(self):
        """CC member not in committee should fail."""
        cc_cred = make_credential(10)
        state, action_ids = make_gov_state_with_proposals(1)
        # cc_cred NOT in state.committee

        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=cc_cred)
        procedures = {
            voter: {action_ids[0]: VotingProcedure(vote=Vote.NO)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert any("VoterNotAuthorized" in e for e in errors)

    def test_vote_on_nonexistent_proposal_fails(self):
        """Voting on a proposal that doesn't exist should fail."""
        drep_cred = make_credential(1)
        state = GovernanceState(dreps={drep_cred: TEST_PARAMS.drep_deposit})

        bad_action_id = make_gov_action_id(999)
        voter = Voter(role=VoterRole.DREP, credential=drep_cred)
        procedures = {
            voter: {bad_action_id: VotingProcedure(vote=Vote.YES)},
        }

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert any("GovActionIdNotFound" in e for e in errors)


# ---------------------------------------------------------------------------
# Ratification tests
# ---------------------------------------------------------------------------


class TestRatification:
    """Tests for governance action ratification."""

    def test_info_action_auto_ratified(self):
        """InfoAction should be automatically ratified."""
        state, action_ids = make_gov_state_with_proposals(1)
        # Proposal is already an INFO_ACTION by default
        assert check_ratification(action_ids[0], state, TEST_PARAMS)

    def test_nonexistent_proposal(self):
        """Non-existent proposal should not be ratified."""
        state = GovernanceState()
        bad_id = make_gov_action_id(999)
        assert not check_ratification(bad_id, state, TEST_PARAMS)

    def test_threshold_met(self):
        """When threshold is met, ratification should return True."""
        assert _threshold_met(2, 3, (2, 3))  # 2/3 >= 2/3
        assert _threshold_met(3, 3, (2, 3))  # 3/3 >= 2/3

    def test_threshold_not_met(self):
        """When threshold is not met, should return False."""
        assert not _threshold_met(1, 3, (2, 3))  # 1/3 < 2/3

    def test_threshold_zero_total(self):
        """Zero total voters should not meet threshold."""
        assert not _threshold_met(0, 0, (2, 3))

    def test_drep_threshold_check(self):
        """Ratification with DRep threshold should check votes."""
        # Create a parameter change proposal
        proposal = make_proposal(
            action_type=GovActionType.PARAMETER_CHANGE,
        )
        action_id = make_gov_action_id(0)

        # 3 DReps registered, 2 vote yes
        drep1 = make_credential(1)
        drep2 = make_credential(2)
        drep3 = make_credential(3)

        # Need at least committee_min_size (7) CC members for ratification
        cc_members = {make_credential(10 + i): 1000 for i in range(7)}

        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={drep1: 500_000_000, drep2: 500_000_000, drep3: 500_000_000},
            committee=cc_members,
        )

        # 2 of 3 DReps vote yes, all CC members vote yes
        state.votes[action_id] = {
            Voter(VoterRole.DREP, drep1): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep2): VotingProcedure(vote=Vote.YES),
            Voter(VoterRole.DREP, drep3): VotingProcedure(vote=Vote.NO),
        }
        for cc_cred in cc_members:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)] = (
                VotingProcedure(vote=Vote.YES)
            )

        assert check_ratification(action_id, state, TEST_PARAMS)

    def test_custom_thresholds(self):
        """Custom thresholds should override defaults."""
        proposal = make_proposal(action_type=GovActionType.PARAMETER_CHANGE)
        action_id = make_gov_action_id(0)

        drep1 = make_credential(1)
        state = GovernanceState(
            proposals={action_id: proposal},
            dreps={drep1: 500_000_000},
        )
        state.votes[action_id] = {
            Voter(VoterRole.DREP, drep1): VotingProcedure(vote=Vote.YES),
        }

        # 100% threshold — 1/1 should pass
        thresholds = RatificationThresholds(
            drep_threshold=(1, 1),
        )
        assert check_ratification(action_id, state, TEST_PARAMS, thresholds)


# ---------------------------------------------------------------------------
# Proposal expiry tests
# ---------------------------------------------------------------------------


class TestProposalExpiry:
    """Tests for governance proposal expiry."""

    def test_expired_proposal_removed(self):
        """Proposals past govActionLifetime should be removed."""
        state, action_ids = make_gov_state_with_proposals(1)
        proposal_epochs = {action_ids[0]: 0}  # Proposed at epoch 0

        # Current epoch = 10, lifetime = 6 => epoch 0 + 6 < 10 => expired
        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert action_ids[0] not in new_state.proposals

    def test_active_proposal_kept(self):
        """Proposals within govActionLifetime should be kept."""
        state, action_ids = make_gov_state_with_proposals(1)
        proposal_epochs = {action_ids[0]: 5}  # Proposed at epoch 5

        # Current epoch = 10, lifetime = 6 => epoch 5 + 6 = 11 > 10 => active
        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert action_ids[0] in new_state.proposals

    def test_expired_votes_also_removed(self):
        """Votes on expired proposals should also be removed."""
        state, action_ids = make_gov_state_with_proposals(1)

        # Add a vote
        drep_cred = make_credential(1)
        voter = Voter(VoterRole.DREP, drep_cred)
        state.votes[action_ids[0]] = {
            voter: VotingProcedure(vote=Vote.YES),
        }

        proposal_epochs = {action_ids[0]: 0}
        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert action_ids[0] not in new_state.votes


# ---------------------------------------------------------------------------
# DRep type validation tests
# ---------------------------------------------------------------------------


class TestDRepType:
    """Tests for DRep type validation."""

    def test_key_hash_drep(self):
        """KEY_HASH DRep should require 28-byte credential."""
        cred = make_credential(1)
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=cred)
        assert drep.credential == cred

    def test_script_hash_drep(self):
        """SCRIPT_HASH DRep should require 28-byte credential."""
        cred = make_credential(2)
        drep = DRep(drep_type=DRepType.SCRIPT_HASH, credential=cred)
        assert drep.credential == cred

    def test_always_abstain_no_credential(self):
        """ALWAYS_ABSTAIN should not have a credential."""
        drep = DRep(drep_type=DRepType.ALWAYS_ABSTAIN)
        assert drep.credential is None

    def test_always_no_confidence_no_credential(self):
        """ALWAYS_NO_CONFIDENCE should not have a credential."""
        drep = DRep(drep_type=DRepType.ALWAYS_NO_CONFIDENCE)
        assert drep.credential is None

    def test_key_hash_without_credential_fails(self):
        """KEY_HASH without credential should fail."""
        with pytest.raises(ValueError, match="requires a 28-byte credential"):
            DRep(drep_type=DRepType.KEY_HASH, credential=None)

    def test_always_abstain_with_credential_fails(self):
        """ALWAYS_ABSTAIN with credential should fail."""
        with pytest.raises(ValueError, match="should not have a credential"):
            DRep(drep_type=DRepType.ALWAYS_ABSTAIN, credential=make_credential(1))


# ---------------------------------------------------------------------------
# Error type tests
# ---------------------------------------------------------------------------


class TestErrorTypes:
    """Tests for Conway error types."""

    def test_governance_error(self):
        """ConwayGovernanceError should carry message."""
        err = ConwayGovernanceError("test error")
        assert err.message == "test error"
        assert "test error" in str(err)

    def test_validation_error(self):
        """ConwayValidationError should carry error list."""
        err = ConwayValidationError(["err1", "err2"])
        assert err.errors == ["err1", "err2"]
        assert "err1" in str(err)
        assert "err2" in str(err)


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestConwayProperties:
    """Property-based tests for Conway governance invariants."""

    @given(
        yes=st.integers(min_value=0, max_value=1000),
        total=st.integers(min_value=1, max_value=1000),
        num=st.integers(min_value=1, max_value=100),
        denom=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=200)
    def test_threshold_monotonic_in_yes_votes(self, yes: int, total: int, num: int, denom: int):
        """More yes votes should never reduce threshold satisfaction."""
        if yes >= total:
            return  # Skip invalid cases
        met_at_yes = _threshold_met(yes, total, (num, denom))
        met_at_yes_plus = _threshold_met(yes + 1, total, (num, denom))
        # If met at yes, should also be met at yes+1
        if met_at_yes:
            assert met_at_yes_plus

    @given(
        action_types=st.lists(
            st.sampled_from(list(GovActionType)),
            min_size=1,
            max_size=7,
        ),
    )
    @settings(max_examples=50)
    def test_governance_action_validity_independent_of_ordering(
        self, action_types: list[GovActionType]
    ):
        """Validating proposals should not depend on their order.

        Each proposal is validated independently — reordering the list
        should produce the same set of errors.
        """
        proposals = [make_proposal(seed=i, action_type=at) for i, at in enumerate(action_types)]
        state = GovernanceState()

        errors_forward = validate_proposals(proposals, TEST_PARAMS, state)
        errors_reverse = validate_proposals(list(reversed(proposals)), TEST_PARAMS, state)

        # Same number of errors regardless of order
        assert len(errors_forward) == len(errors_reverse)
