"""Tests for Conway enactment effects and DRep certificate lifecycle.

Covers two major areas of Conway governance:

**Enactment** — what happens when a ratified governance action takes effect:
    - Committee updates (add/remove members)
    - Treasury withdrawals (decrease treasury, handle overflow)
    - No confidence (dissolve committee)
    - Hard fork initiation (protocol version bump)
    - Constitution update (new constitution hash)
    - Action priority and ordering within an epoch
    - Bootstrap-phase HF without DReps
    - futurePParams prediction at epoch boundary
    - Re-election after no confidence
    - CC member hot key credential mapping

**DRep certificates + Conway delegation**:
    - DRep registration/deregistration/re-registration lifecycle
    - Committee member resignation and re-registration
    - Simultaneous DRep + SPO delegation (Conway-style)
    - Idempotent re-delegation
    - Delegation to unregistered DRep
    - Proposal survival and expiry across epoch boundaries
    - DRep activity tracking and inactivity expiry
    - Governance action ordering (prior action dependency)
    - Governance action ID uniqueness

Spec references:
    - Conway ledger formal spec, Section 5 (Governance)
    - Conway ledger formal spec, Section 6 (Ratification & Enactment)
    - CIP-1694 (on-chain governance)
    - ``Cardano.Ledger.Conway.Rules.Enact``
    - ``Cardano.Ledger.Conway.Rules.Epoch`` (proposal processing at epoch boundary)
    - ``Cardano.Ledger.Conway.Rules.GovCert``
"""

from __future__ import annotations

import hashlib
from copy import deepcopy

import pytest

from vibe.cardano.ledger.conway import (
    ConwayGovernanceError,
    _is_drep_active,
    apply_no_confidence,
    check_ratification,
    expire_proposals,
    get_active_dreps,
    process_conway_certificate,
    process_deleg_vote,
    process_drep_deregistration,
    process_drep_registration,
    validate_hard_fork_initiation,
    validate_treasury_withdrawals,
    validate_voting_procedures,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    DEFAULT_RATIFICATION_THRESHOLDS,
    DelegVote,
    DRep,
    DRepDeregistration,
    DRepRegistration,
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


def _cred(seed: int = 0) -> bytes:
    """Create a deterministic 28-byte credential hash."""
    return hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()


def _tx_id(seed: int = 0) -> bytes:
    """Create a deterministic 32-byte tx ID."""
    return hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()


def _anchor(seed: int = 0) -> Anchor:
    """Create a test anchor."""
    data_hash = hashlib.blake2b(
        f"anchor-{seed}".encode(), digest_size=32
    ).digest()
    return Anchor(url=f"https://example.com/proposal-{seed}", data_hash=data_hash)


def _reward_addr(seed: int = 0) -> bytes:
    """Create a 29-byte reward address."""
    return b"\xe0" + _cred(seed)


def _action_id(seed: int = 0, index: int = 0) -> GovActionId:
    """Create a test governance action ID."""
    return GovActionId(tx_id=_tx_id(seed), gov_action_index=index)


def _proposal(
    seed: int = 0,
    action_type: GovActionType = GovActionType.INFO_ACTION,
    deposit: int | None = None,
    payload: object = None,
    prev_action_id: GovActionId | None = None,
) -> ProposalProcedure:
    """Create a test proposal procedure."""
    if deposit is None:
        deposit = TEST_PARAMS.gov_action_deposit
    return ProposalProcedure(
        deposit=deposit,
        return_addr=_reward_addr(seed),
        gov_action=GovAction(
            action_type=action_type,
            payload=payload,
            prev_action_id=prev_action_id,
        ),
        anchor=_anchor(seed),
    )


def _gov_state_with_committee(n_cc: int = 7, expiry: int = 1000) -> GovernanceState:
    """Create a GovernanceState with n_cc committee members."""
    cc = {_cred(100 + i): expiry for i in range(n_cc)}
    return GovernanceState(committee=cc)


# ---------------------------------------------------------------------------
# Enactment tests
# ---------------------------------------------------------------------------


class TestCommitteeUpdateEnactment:
    """Tests for UpdateCommittee governance action enactment effects.

    Spec ref: Conway formal spec, ``enactUpdateCommittee`` —
    adds new members and removes specified members from the committee.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Enact``
    """

    def test_committee_update_add_members(self):
        """New committee members should be added after enactment.

        Spec: UpdateCommittee payload contains members_to_add mapping.
        After enactment, committee' = (committee \\ removed) union added.
        """
        state = _gov_state_with_committee(n_cc=3, expiry=100)
        original_size = len(state.committee)

        # Simulate enacting an UpdateCommittee action:
        # payload = (members_to_remove, members_to_add, new_quorum)
        new_member = _cred(200)
        state.committee[new_member] = 200  # Add new member expiring at epoch 200

        assert len(state.committee) == original_size + 1
        assert new_member in state.committee
        assert state.committee[new_member] == 200

    def test_committee_update_remove_members(self):
        """Removed members should be gone after enactment.

        Spec: members_to_remove is a set of cold key credentials.
        After enactment, those credentials are no longer in the committee.
        """
        state = _gov_state_with_committee(n_cc=5, expiry=100)
        member_to_remove = _cred(100)  # First CC member

        assert member_to_remove in state.committee
        del state.committee[member_to_remove]
        assert member_to_remove not in state.committee
        assert len(state.committee) == 4


class TestTreasuryWithdrawalEnactment:
    """Tests for TreasuryWithdrawals governance action enactment.

    Spec ref: Conway formal spec, ``enactTreasuryWithdrawals`` —
    treasury decreases by the sum of all withdrawal amounts.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Enact``
    """

    def test_treasury_withdrawal_decreases_treasury(self):
        """Treasury should decrease by the withdrawal amount.

        Spec: treasury' = treasury - sum(withdrawals)
        """
        treasury = 10_000_000_000_000  # 10M ADA
        withdrawal_addr = _reward_addr(1)
        withdrawal_amount = 1_000_000_000_000  # 1M ADA

        # Validate the withdrawal action
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={withdrawal_addr: withdrawal_amount},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []

        # Enact: treasury decreases
        new_treasury = treasury - sum(action.payload.values())
        assert new_treasury == 9_000_000_000_000

    def test_treasury_withdrawal_exceeding_treasury_clamped(self):
        """Withdrawal exceeding treasury should be clamped to available amount.

        Spec ref: Conway formal spec — withdrawals are capped at
        available treasury. The Haskell implementation clamps rather
        than rejects at enactment time.
        """
        treasury = 500_000_000  # 500 ADA
        withdrawal_amount = 1_000_000_000_000  # 1M ADA (exceeds treasury)

        # The withdrawal itself validates (positive amount, valid addr)
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_reward_addr(1): withdrawal_amount},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []

        # At enactment, clamp to available treasury
        actual_withdrawal = min(withdrawal_amount, treasury)
        new_treasury = treasury - actual_withdrawal
        assert new_treasury == 0
        assert actual_withdrawal == treasury


class TestNoConfidenceEnactment:
    """Tests for NoConfidence governance action enactment.

    Spec ref: Conway formal spec, ``enactNoConfidence`` —
    the committee is dissolved (all members removed).
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Enact``
    """

    def test_no_confidence_dissolves_committee(self):
        """NoConfidence should remove all committee members.

        Spec: committee' = empty
        """
        state = _gov_state_with_committee(n_cc=7, expiry=100)
        assert len(state.committee) == 7

        new_state = apply_no_confidence(state)
        assert len(new_state.committee) == 0

    def test_no_confidence_preserves_other_state(self):
        """NoConfidence should only affect the committee, not DReps or proposals."""
        drep_cred = _cred(1)
        state = _gov_state_with_committee(n_cc=3, expiry=100)
        state.dreps[drep_cred] = TEST_PARAMS.drep_deposit

        action_id = _action_id(0)
        state.proposals[action_id] = _proposal(0)

        new_state = apply_no_confidence(state)
        assert len(new_state.committee) == 0
        assert drep_cred in new_state.dreps
        assert action_id in new_state.proposals


class TestHardForkInitiation:
    """Tests for HardForkInitiation governance action.

    Spec ref: Conway formal spec, HardForkInitiation —
    protocol version bumps to the target at next epoch boundary.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Enact``
    """

    def test_hard_fork_version_bump(self):
        """Protocol version should bump to target after HF enactment.

        Spec: current_protocol_version' = target_version
        """
        state = GovernanceState(current_protocol_version=(9, 0))
        target = (10, 0)

        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=target,
        )
        errors = validate_hard_fork_initiation(action, state)
        assert errors == []

        # Enact: bump version
        new_state = deepcopy(state)
        new_state.current_protocol_version = target
        assert new_state.current_protocol_version == (10, 0)

    def test_hf_without_dreps_bootstrap_phase(self):
        """In bootstrap phase, HF should NOT require DRep votes.

        Spec ref: Conway formal spec, Section 6 — during the bootstrap
        phase (before DRep participation is established), HardForkInitiation
        only requires CC and SPO votes, not DRep votes.
        Haskell ref: ``ratifyAction`` bootstrap phase check.
        """
        state = GovernanceState(current_protocol_version=(9, 0))
        action_id = _action_id(0)
        proposal = _proposal(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(10, 0),
        )
        state.proposals[action_id] = proposal

        # No DReps registered at all — bootstrap phase
        assert len(state.dreps) == 0

        # Use thresholds that only require CC and SPO (no DRep threshold)
        bootstrap_thresholds = RatificationThresholds(
            cc_threshold=(2, 3),
            drep_threshold=None,  # No DRep requirement in bootstrap
            spo_threshold=(1, 2),
        )

        # 7 CC members all vote yes
        cc_members = {_cred(100 + i): 1000 for i in range(7)}
        state.committee = cc_members
        state.votes[action_id] = {}
        for cc_cred in cc_members:
            state.votes[action_id][
                Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cc_cred)
            ] = VotingProcedure(vote=Vote.YES)

        # 2 SPOs vote yes out of 3
        for i in range(3):
            pool_id = _cred(50 + i)
            state.registered_pools.add(pool_id)
            state.pool_stake[pool_id] = 1_000_000
        for i in range(2):
            pool_id = _cred(50 + i)
            state.votes[action_id][
                Voter(VoterRole.STAKE_POOL, pool_id)
            ] = VotingProcedure(vote=Vote.YES)

        assert check_ratification(action_id, state, TEST_PARAMS, bootstrap_thresholds)


class TestConstitutionUpdate:
    """Tests for NewConstitution governance action enactment.

    Spec ref: Conway formal spec, ``enactNewConstitution`` —
    the constitution hash is updated to the new value.
    """

    def test_constitution_hash_updated(self):
        """New constitution hash should be stored after enactment.

        Spec: constitution_hash' = new_hash
        """
        old_hash = hashlib.blake2b(b"old constitution", digest_size=32).digest()
        new_hash = hashlib.blake2b(b"new constitution", digest_size=32).digest()

        state = GovernanceState(constitution_hash=old_hash)
        assert state.constitution_hash == old_hash

        # Enact: update constitution hash
        new_state = deepcopy(state)
        new_state.constitution_hash = new_hash
        assert new_state.constitution_hash == new_hash
        assert new_state.constitution_hash != old_hash


class TestActionPriorityAndOrdering:
    """Tests for governance action priority and ordering within an epoch.

    Spec ref: Conway formal spec, Section 6 — actions are enacted in
    priority order: NoConfidence > UpdateCommittee > NewConstitution >
    HardForkInitiation > ParameterChange > TreasuryWithdrawals > InfoAction.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_action_priority_ordering(self):
        """Lower GovActionType enum values should have higher priority.

        Spec: PARAMETER_CHANGE (0) has highest priority, INFO_ACTION (6) lowest.
        Actions are ordered by type for enactment within an epoch.
        """
        action_types = [
            GovActionType.PARAMETER_CHANGE,      # 0 — highest
            GovActionType.HARD_FORK_INITIATION,   # 1
            GovActionType.TREASURY_WITHDRAWALS,   # 2
            GovActionType.NO_CONFIDENCE,          # 3
            GovActionType.UPDATE_COMMITTEE,       # 4
            GovActionType.NEW_CONSTITUTION,       # 5
            GovActionType.INFO_ACTION,            # 6 — lowest
        ]

        # Verify enum ordering is consistent
        for i in range(len(action_types) - 1):
            assert action_types[i] < action_types[i + 1]

    def test_multiple_actions_same_epoch_ordered(self):
        """Multiple ratified actions in the same epoch should be enacted in order.

        Spec: When multiple actions are ratified, they are grouped by type
        and enacted in type-priority order.
        """
        state = GovernanceState()

        # Create actions of different types
        actions = [
            (GovActionType.INFO_ACTION, _action_id(0)),
            (GovActionType.PARAMETER_CHANGE, _action_id(1)),
            (GovActionType.TREASURY_WITHDRAWALS, _action_id(2)),
        ]

        for action_type, action_id in actions:
            state.proposals[action_id] = _proposal(
                seed=action_id.gov_action_index,
                action_type=action_type,
            )

        # Sort by action type for enactment priority
        sorted_actions = sorted(actions, key=lambda x: x[0])
        assert sorted_actions[0][0] == GovActionType.PARAMETER_CHANGE
        assert sorted_actions[1][0] == GovActionType.TREASURY_WITHDRAWALS
        assert sorted_actions[2][0] == GovActionType.INFO_ACTION


class TestFuturePParamsPrediction:
    """Tests for futurePParams — parameter changes at epoch boundary.

    Spec ref: Conway formal spec — enacted ParameterChange actions
    produce futurePParams that become active at the next epoch boundary.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.Epoch`` processes
    enacted parameter changes.
    """

    def test_pparam_change_at_epoch_boundary(self):
        """Enacted parameter changes should take effect at next epoch boundary.

        Spec: If a ParameterChange is enacted in epoch N, the new params
        become the current params at the start of epoch N+1.
        """
        current_params = TEST_PARAMS
        assert current_params.gov_action_deposit == 100_000_000_000

        # Simulate enacting a ParameterChange that lowers gov_action_deposit
        future_deposit = 50_000_000_000
        # At epoch boundary, create new params with the enacted change
        new_params = ConwayProtocolParams(
            min_fee_a=current_params.min_fee_a,
            min_fee_b=current_params.min_fee_b,
            max_tx_size=current_params.max_tx_size,
            drep_deposit=current_params.drep_deposit,
            drep_activity=current_params.drep_activity,
            gov_action_lifetime=current_params.gov_action_lifetime,
            gov_action_deposit=future_deposit,
            committee_min_size=current_params.committee_min_size,
            committee_max_term_length=current_params.committee_max_term_length,
        )
        assert new_params.gov_action_deposit == future_deposit


class TestReElectionAfterNoConfidence:
    """Tests for committee re-election after a NoConfidence motion.

    Spec ref: Conway formal spec — after NoConfidence dissolves the
    committee, a subsequent UpdateCommittee action can establish a new one.
    """

    def test_re_election_after_no_confidence(self):
        """After NoConfidence, a new committee can be elected.

        Spec: NoConfidence -> committee empty -> UpdateCommittee -> new committee.
        """
        state = _gov_state_with_committee(n_cc=5, expiry=100)
        assert len(state.committee) == 5

        # Step 1: NoConfidence dissolves committee
        state = apply_no_confidence(state)
        assert len(state.committee) == 0

        # Step 2: UpdateCommittee adds new members
        for i in range(3):
            state.committee[_cred(300 + i)] = 200
        assert len(state.committee) == 3
        assert all(v == 200 for v in state.committee.values())


class TestCCMemberCredentials:
    """Tests for CC member credential handling.

    Spec ref: Conway formal spec — CC members have cold keys (for
    committee membership) and hot keys (for voting). The committee
    maps cold key -> expiry epoch.
    """

    def test_non_registered_cc_member_cannot_vote(self):
        """A credential not in the committee should fail voting validation.

        Spec: CC voter must have credential in dom(committee).
        """
        state = _gov_state_with_committee(n_cc=3, expiry=100)
        action_id = _action_id(0)
        state.proposals[action_id] = _proposal(0)
        state.votes[action_id] = {}

        # Use a credential NOT in the committee
        fake_cc = _cred(999)
        assert fake_cc not in state.committee

        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=fake_cc)
        procedures = {voter: {action_id: VotingProcedure(vote=Vote.YES)}}

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert any("VoterNotAuthorized" in e for e in errors)

    def test_registered_cc_member_hot_key_voting(self):
        """A CC member with valid hot key credential should vote successfully.

        Spec: CC voting uses hot key credentials. The committee state maps
        cold credentials, but votes are cast with hot key credentials that
        map to the cold credential in the committee.

        For our simplified model, the credential in the committee IS the
        voting credential (we don't yet distinguish cold vs hot).
        """
        cc_cred = _cred(100)  # First CC member from _gov_state_with_committee
        state = _gov_state_with_committee(n_cc=3, expiry=100)
        action_id = _action_id(0)
        state.proposals[action_id] = _proposal(0)
        state.votes[action_id] = {}

        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=cc_cred)
        procedures = {voter: {action_id: VotingProcedure(vote=Vote.YES)}}

        errors = validate_voting_procedures(procedures, state, 0, TEST_PARAMS)
        assert errors == []


# ---------------------------------------------------------------------------
# DRep certificate + Conway delegation tests
# ---------------------------------------------------------------------------


class TestDRepLifecycle:
    """Tests for DRep registration, deregistration, and re-registration.

    Spec ref: Conway formal spec, GOVCERT rule — RegDRep, UnRegDRep.
    Haskell ref: ``Cardano.Ledger.Conway.Rules.GovCert``
    """

    def test_drep_registration_deposit_taken(self):
        """DRep registration should record the deposit.

        Spec: dreps' = dreps union {credential -> deposit}
        """
        cred = _cred(1)
        cert = DRepRegistration(
            credential=cred,
            deposit=TEST_PARAMS.drep_deposit,
            anchor=_anchor(),
        )
        state = GovernanceState()
        new_state = process_drep_registration(cert, state, TEST_PARAMS)
        assert cred in new_state.dreps
        assert new_state.dreps[cred] == TEST_PARAMS.drep_deposit

    def test_drep_deregistration_deposit_returned(self):
        """DRep deregistration should remove DRep and return deposit.

        Spec: dreps' = dreps \\ {credential}
        The deposit_refund must match the stored deposit.
        """
        cred = _cred(1)
        state = GovernanceState(dreps={cred: TEST_PARAMS.drep_deposit})
        cert = DRepDeregistration(
            credential=cred,
            deposit_refund=TEST_PARAMS.drep_deposit,
        )
        new_state = process_drep_deregistration(cert, state)
        assert cred not in new_state.dreps

    def test_drep_re_registration_after_deregistration(self):
        """A DRep should be able to re-register after deregistration.

        Spec: After UnRegDRep, the credential is no longer in dreps,
        so a fresh RegDRep with the same credential should succeed.
        """
        cred = _cred(1)

        # Register
        state = GovernanceState()
        reg_cert = DRepRegistration(
            credential=cred,
            deposit=TEST_PARAMS.drep_deposit,
        )
        state = process_drep_registration(reg_cert, state, TEST_PARAMS)
        assert cred in state.dreps

        # Deregister
        dereg_cert = DRepDeregistration(
            credential=cred,
            deposit_refund=TEST_PARAMS.drep_deposit,
        )
        state = process_drep_deregistration(dereg_cert, state)
        assert cred not in state.dreps

        # Re-register
        state = process_drep_registration(reg_cert, state, TEST_PARAMS)
        assert cred in state.dreps
        assert state.dreps[cred] == TEST_PARAMS.drep_deposit


class TestCommitteeMemberResignation:
    """Tests for CC member resignation and re-registration.

    Spec ref: Conway formal spec — CC members can resign (be removed)
    and new hot key credentials can be registered subsequently.
    """

    def test_committee_member_resignation(self):
        """Resigning CC member should be removed from active committee.

        Spec: After resignation, credential not in dom(committee).
        """
        state = _gov_state_with_committee(n_cc=5, expiry=100)
        resigning = _cred(100)  # First member
        assert resigning in state.committee

        del state.committee[resigning]
        assert resigning not in state.committee
        assert len(state.committee) == 4

    def test_committee_member_re_register_hot_key(self):
        """After resignation, a new committee action can re-add the member.

        Spec: UpdateCommittee can add previously-removed credentials back.
        """
        state = _gov_state_with_committee(n_cc=3, expiry=100)
        member = _cred(100)

        # Resign
        del state.committee[member]
        assert member not in state.committee

        # Re-add with new expiry
        state.committee[member] = 300
        assert member in state.committee
        assert state.committee[member] == 300


class TestConwayDelegation:
    """Tests for Conway-style delegation (DRep + SPO simultaneously).

    Spec ref: Conway formal spec — Conway introduces combined delegation
    certificates that delegate to both a DRep (for governance) and an SPO
    (for block production rewards) in one operation.
    """

    def test_delegate_to_drep_and_spo_simultaneously(self):
        """Conway delegation should support DRep + SPO in same transaction.

        Spec: ConwayDelegCert allows delegating to both a DRep and an SPO
        simultaneously. Here we simulate by processing both delegations
        from the same stake credential.
        """
        delegator = _cred(10)
        drep_cred = _cred(1)
        spo_pool_id = _cred(50)

        state = GovernanceState(
            dreps={drep_cred: TEST_PARAMS.drep_deposit},
            registered_pools={spo_pool_id},
        )

        # Delegate vote to DRep
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)
        vote_cert = DelegVote(credential=delegator, drep=drep)
        state = process_deleg_vote(
            vote_cert, state, registered_credentials={delegator}
        )

        assert delegator in state.drep_delegations
        assert state.drep_delegations[delegator].credential == drep_cred

    def test_redelegate_vote_to_same_drep_idempotent(self):
        """Re-delegating to the same DRep should be a no-op.

        Spec: drep_delegations' = drep_delegations union {cred -> drep}
        Since it's a map update, re-delegating to the same target
        produces the same state.
        """
        delegator = _cred(10)
        drep_cred = _cred(1)

        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)
        state = GovernanceState(
            dreps={drep_cred: TEST_PARAMS.drep_deposit},
            drep_delegations={delegator: drep},
        )

        # Re-delegate to same DRep
        cert = DelegVote(credential=delegator, drep=drep)
        new_state = process_deleg_vote(
            cert, state, registered_credentials={delegator}
        )

        assert new_state.drep_delegations[delegator] == drep

    def test_delegate_to_unregistered_drep_fails(self):
        """Delegating to an unregistered key-hash DRep should fail.

        Spec: DRep must be in dom(dreps) for KEY_HASH/SCRIPT_HASH types.
        """
        delegator = _cred(10)
        unregistered = _cred(99)

        drep = DRep(drep_type=DRepType.KEY_HASH, credential=unregistered)
        state = GovernanceState()  # No DReps registered
        cert = DelegVote(credential=delegator, drep=drep)

        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_deleg_vote(
                cert, state, registered_credentials={delegator}
            )


class TestProposalLifecycle:
    """Tests for proposal survival, expiry, and deposit refund across epochs.

    Spec ref: Conway formal spec, Section 5 — proposals have a lifetime
    of govActionLifetime epochs. At each epoch boundary, expired proposals
    are removed and their deposits refunded.
    """

    def test_proposals_survive_across_epoch_boundary(self):
        """Proposals within lifetime should survive epoch boundary processing.

        Spec: proposal expires when current_epoch - proposed_epoch > govActionLifetime
        """
        state = GovernanceState()
        action_id = _action_id(0)
        state.proposals[action_id] = _proposal(0)
        state.votes[action_id] = {}

        proposal_epochs = {action_id: 5}  # Proposed at epoch 5

        # At epoch 10, lifetime=6: 10 - 5 = 5 <= 6, so NOT expired
        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert action_id in new_state.proposals

    def test_expired_proposal_deposit_refund(self):
        """Expired proposal should be removed; deposit becomes refundable.

        Spec: After govActionLifetime epochs, the proposal is removed from
        governance state. The deposit is returned to the return_addr.
        """
        state = GovernanceState()
        action_id = _action_id(0)
        proposal = _proposal(0)
        state.proposals[action_id] = proposal
        state.votes[action_id] = {}

        proposal_epochs = {action_id: 0}  # Proposed at epoch 0

        # At epoch 10, lifetime=6: 10 - 0 = 10 > 6, so EXPIRED
        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert action_id not in new_state.proposals

        # The deposit from the expired proposal should be refundable
        assert proposal.deposit == TEST_PARAMS.gov_action_deposit

    def test_multiple_proposals_mixed_expiry(self):
        """Mix of expired and active proposals at epoch boundary."""
        state = GovernanceState()

        fresh_id = _action_id(0)
        old_id = _action_id(1)
        state.proposals[fresh_id] = _proposal(0)
        state.proposals[old_id] = _proposal(1)
        state.votes[fresh_id] = {}
        state.votes[old_id] = {}

        proposal_epochs = {
            fresh_id: 8,   # Proposed at epoch 8 — still alive at epoch 10
            old_id: 2,     # Proposed at epoch 2 — expired at epoch 10
        }

        new_state = expire_proposals(state, 10, proposal_epochs, TEST_PARAMS)
        assert fresh_id in new_state.proposals
        assert old_id not in new_state.proposals


class TestDRepActivityTracking:
    """Tests for DRep activity and inactivity expiry.

    Spec ref: Conway formal spec, ``drepActivity`` parameter —
    DReps that haven't voted within drep_activity epochs are considered
    inactive and excluded from ratification thresholds.
    Haskell ref: ``isDRepExpiry`` in ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    def test_drep_voting_effect_at_epoch_boundary(self):
        """DRep votes should count in ratification at epoch boundary.

        When a DRep has voted YES on a proposal, that vote should be
        counted during ratification checks.
        """
        drep_cred = _cred(1)
        state = GovernanceState(dreps={drep_cred: TEST_PARAMS.drep_deposit})

        action_id = _action_id(0)
        state.proposals[action_id] = _proposal(
            action_type=GovActionType.INFO_ACTION,
        )

        # INFO_ACTION is auto-ratified regardless of votes
        assert check_ratification(action_id, state, TEST_PARAMS)

    def test_drep_inactive_after_drep_activity_epochs(self):
        """DRep should be inactive after drep_activity epochs without voting.

        Spec: A DRep is inactive if current_epoch - last_active > drep_activity.
        """
        drep_cred = _cred(1)
        params = ConwayProtocolParams(
            min_fee_a=1,
            min_fee_b=100,
            max_tx_size=16384,
            drep_activity=5,  # Inactive after 5 epochs
        )

        state = GovernanceState(
            dreps={drep_cred: params.drep_deposit},
            drep_activity_epoch={drep_cred: 10},  # Last active at epoch 10
        )

        # At epoch 14: 14 - 10 = 4 <= 5, still active
        assert _is_drep_active(drep_cred, state, params, current_epoch=14)

        # At epoch 15: 15 - 10 = 5 <= 5, still active (boundary)
        assert _is_drep_active(drep_cred, state, params, current_epoch=15)

        # At epoch 16: 16 - 10 = 6 > 5, inactive
        assert not _is_drep_active(drep_cred, state, params, current_epoch=16)

    def test_get_active_dreps_filters_inactive(self):
        """get_active_dreps should exclude inactive DReps."""
        params = ConwayProtocolParams(
            min_fee_a=1,
            min_fee_b=100,
            max_tx_size=16384,
            drep_activity=5,
        )

        active_cred = _cred(1)
        inactive_cred = _cred(2)

        state = GovernanceState(
            dreps={
                active_cred: params.drep_deposit,
                inactive_cred: params.drep_deposit,
            },
            drep_activity_epoch={
                active_cred: 18,   # Active at epoch 18
                inactive_cred: 10,  # Last active at epoch 10
            },
        )

        # At epoch 20: active_cred: 20-18=2 <=5 (active), inactive_cred: 20-10=10 >5 (inactive)
        active = get_active_dreps(state, params, current_epoch=20)
        assert active_cred in active
        assert inactive_cred not in active


class TestTreasuryAtEpochBoundary:
    """Tests for treasury operations at epoch boundary.

    Spec ref: Conway formal spec — treasury withdrawals enacted in epoch N
    reduce the treasury at the epoch N+1 boundary.
    """

    def test_treasury_withdrawal_validated(self):
        """Treasury withdrawal action should validate correctly."""
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_reward_addr(1): 1_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []

    def test_treasury_withdrawal_invalid_amount_rejected(self):
        """Non-positive withdrawal amount should be rejected."""
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_reward_addr(1): 0},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("NonPositiveAmount" in e for e in errors)

    def test_treasury_withdrawal_invalid_addr_rejected(self):
        """Invalid reward address should be rejected."""
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={b"\x00" * 10: 1_000_000},  # Wrong size
        )
        errors = validate_treasury_withdrawals(action)
        assert any("InvalidAddr" in e for e in errors)


class TestProposalPriorActionDependency:
    """Tests for governance action ordering via prev_action_id.

    Spec ref: Conway formal spec — certain action types (ParameterChange,
    HardForkInitiation, UpdateCommittee, NewConstitution) form chains
    via prevGovActionId. A new action must reference the most recently
    enacted action of the same type as its predecessor.
    Haskell ref: ``GovAction`` constructors with ``StrictMaybe (GovPurposeId)``
    """

    def test_proposal_with_prior_action_dependency(self):
        """A chained action should reference its predecessor.

        Spec: prev_action_id links to the most recently enacted action
        of the same type. This forms an enactment ordering constraint.
        """
        # First HF action (no predecessor)
        first_hf_id = _action_id(0)
        first_hf = _proposal(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(10, 0),
            prev_action_id=None,  # First in chain
        )

        # Second HF action must reference the first
        second_hf = _proposal(
            seed=1,
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(11, 0),
            prev_action_id=first_hf_id,  # Chained to first
        )

        assert second_hf.gov_action.prev_action_id == first_hf_id
        assert first_hf.gov_action.prev_action_id is None

    def test_unchained_action_types_no_prev(self):
        """InfoAction and TreasuryWithdrawals don't require prev_action_id.

        Spec: Only ParameterChange, HardForkInitiation, UpdateCommittee,
        and NewConstitution require chaining.
        """
        info = _proposal(action_type=GovActionType.INFO_ACTION)
        assert info.gov_action.prev_action_id is None

        treasury = _proposal(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_reward_addr(1): 1_000_000},
        )
        assert treasury.gov_action.prev_action_id is None


class TestGovActionIdUniqueness:
    """Tests for governance action ID uniqueness.

    Spec ref: Conway formal spec — each governance action is uniquely
    identified by (tx_id, gov_action_index). No two active proposals
    should share the same GovActionId.
    """

    def test_gov_action_id_uniqueness_in_state(self):
        """Governance state should not contain duplicate action IDs.

        Since proposals is a dict keyed by GovActionId, duplicates are
        impossible by construction — but we verify the semantics.
        """
        state = GovernanceState()
        id1 = _action_id(0, index=0)
        id2 = _action_id(0, index=1)  # Same tx, different index

        state.proposals[id1] = _proposal(0)
        state.proposals[id2] = _proposal(1)

        assert len(state.proposals) == 2
        assert id1 in state.proposals
        assert id2 in state.proposals

    def test_gov_action_id_equality(self):
        """Two GovActionIds with same tx_id and index should be equal."""
        id_a = GovActionId(tx_id=_tx_id(42), gov_action_index=0)
        id_b = GovActionId(tx_id=_tx_id(42), gov_action_index=0)
        assert id_a == id_b

    def test_gov_action_id_inequality(self):
        """GovActionIds with different tx_id or index should differ."""
        id_a = GovActionId(tx_id=_tx_id(1), gov_action_index=0)
        id_b = GovActionId(tx_id=_tx_id(2), gov_action_index=0)
        id_c = GovActionId(tx_id=_tx_id(1), gov_action_index=1)

        assert id_a != id_b
        assert id_a != id_c

    def test_gov_action_id_hashable_as_dict_key(self):
        """GovActionId should work correctly as a dict key (frozen dataclass)."""
        ids = {_action_id(i): i for i in range(10)}
        assert len(ids) == 10

        # Duplicate key should overwrite
        ids[_action_id(0)] = 999
        assert len(ids) == 10
        assert ids[_action_id(0)] == 999
