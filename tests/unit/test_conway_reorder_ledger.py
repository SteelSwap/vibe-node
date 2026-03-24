"""Tests for Conway governance action reordering and ledger spec gaps.

Tests cover:
    - Governance action reordering by enactment priority
    - TxRefScriptsSizeTooBig validation
    - Withdrawal delegation checks (Conway-specific)
    - ApplyTx integration for full Conway transaction processing

Spec references:
    - Conway ledger formal spec, Figure 7 (reorderActions / actionPriority)
    - Conway ledger formal spec, UTXO rule (TxRefScriptsSizeTooBig)
    - Conway ledger formal spec, UTXOW rule (withdrawal delegation check)
    - Conway ledger formal spec, GOV transition rule
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Gov.hs``
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Utxo.hs``
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.ledger.conway import (
    ConwayTx,
    ConwayValidationError,
    apply_conway_tx,
    reorder_gov_actions,
    validate_tx_ref_scripts_size,
    validate_withdrawal_delegation,
)
from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayProtocolParams,
    DRep,
    DRepRegistration,
    DRepType,
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


# ---------------------------------------------------------------------------
# Governance action reordering tests
# ---------------------------------------------------------------------------


class TestReorderGovActions:
    """Tests for governance action reordering by enactment priority.

    Spec ref: Conway formal spec, Figure 7, ``reorderActions``.
    Haskell ref: ``reorderActions`` in ``Cardano.Ledger.Conway.Rules.Gov``
    """

    def test_reorder_preserves_length(self):
        """Reordering N proposals must produce exactly N proposals."""
        proposals = [
            make_proposal(seed=i, action_type=at)
            for i, at in enumerate(
                [
                    GovActionType.TREASURY_WITHDRAWALS,
                    GovActionType.HARD_FORK_INITIATION,
                    GovActionType.INFO_ACTION,
                    GovActionType.NO_CONFIDENCE,
                    GovActionType.PARAMETER_CHANGE,
                ]
            )
        ]
        reordered = reorder_gov_actions(proposals)
        assert len(reordered) == len(proposals)

    def test_sorts_by_priority(self):
        """Proposals must be sorted by actionPriority — NoConfidence first,
        InfoAction last, following the spec's enactment ordering.

        Spec ref: Conway formal spec, Figure 7.
        Haskell ref: ``actionPriority`` assigns NoConfidence=0,
            UpdateCommittee=1, NewConstitution=2, HardForkInitiation=3,
            ParameterChange=4, TreasuryWithdrawals=5, InfoAction=6.
        """
        proposals = [
            make_proposal(seed=0, action_type=GovActionType.INFO_ACTION),
            make_proposal(seed=1, action_type=GovActionType.HARD_FORK_INITIATION),
            make_proposal(seed=2, action_type=GovActionType.NO_CONFIDENCE),
            make_proposal(seed=3, action_type=GovActionType.PARAMETER_CHANGE),
            make_proposal(seed=4, action_type=GovActionType.TREASURY_WITHDRAWALS),
            make_proposal(seed=5, action_type=GovActionType.UPDATE_COMMITTEE),
            make_proposal(seed=6, action_type=GovActionType.NEW_CONSTITUTION),
        ]

        reordered = reorder_gov_actions(proposals)
        result_types = [p.gov_action.action_type for p in reordered]

        expected_order = [
            GovActionType.NO_CONFIDENCE,
            GovActionType.UPDATE_COMMITTEE,
            GovActionType.NEW_CONSTITUTION,
            GovActionType.HARD_FORK_INITIATION,
            GovActionType.PARAMETER_CHANGE,
            GovActionType.TREASURY_WITHDRAWALS,
            GovActionType.INFO_ACTION,
        ]
        assert result_types == expected_order

    def test_stable_sort_same_priority(self):
        """Two proposals of the same type must maintain their original
        (deposit/transaction) order — the sort must be stable.

        Spec ref: Conway formal spec, ``reorderActions`` uses stable sort.
        Haskell ref: ``sortBy`` in Haskell is stable.
        """
        # Three ParameterChange proposals — should keep their original order
        p0 = make_proposal(seed=10, action_type=GovActionType.PARAMETER_CHANGE)
        p1 = make_proposal(seed=20, action_type=GovActionType.PARAMETER_CHANGE)
        p2 = make_proposal(seed=30, action_type=GovActionType.PARAMETER_CHANGE)

        reordered = reorder_gov_actions([p0, p1, p2])
        assert reordered == [p0, p1, p2]

    def test_mixed_priorities_interleave(self):
        """Mixed action types should be correctly interleaved by priority,
        with same-priority items preserving their relative order.

        This tests the full reordering semantics with duplicates.
        """
        # Two NoConfidence, one HardFork, two InfoActions
        nc_a = make_proposal(seed=0, action_type=GovActionType.NO_CONFIDENCE)
        info_a = make_proposal(seed=1, action_type=GovActionType.INFO_ACTION)
        hf = make_proposal(seed=2, action_type=GovActionType.HARD_FORK_INITIATION)
        nc_b = make_proposal(seed=3, action_type=GovActionType.NO_CONFIDENCE)
        info_b = make_proposal(seed=4, action_type=GovActionType.INFO_ACTION)

        reordered = reorder_gov_actions([nc_a, info_a, hf, nc_b, info_b])

        # NoConfidence (priority 0) first, then HardFork (3), then InfoAction (6)
        # Within same priority, original order preserved
        expected = [nc_a, nc_b, hf, info_a, info_b]
        assert reordered == expected


# ---------------------------------------------------------------------------
# TxRefScriptsSizeTooBig tests
# ---------------------------------------------------------------------------


class TestTxRefScriptsSizeTooBig:
    """Tests for reference script size limit validation.

    Spec ref: Conway formal spec, ``TxRefScriptsSizeTooBig`` predicate failure.
    Haskell ref: ``ConwayUtxoPredFailure`` ``TxRefScriptsSizeTooBig`` in
        ``Cardano.Ledger.Conway.Rules.Utxo``
    """

    def test_within_limit_passes(self):
        """Reference scripts within the 200KB limit should pass."""
        sizes = [50_000, 50_000, 50_000]  # 150KB total
        errors = validate_tx_ref_scripts_size(sizes)
        assert errors == []

    def test_exceeds_limit_fails(self):
        """Reference scripts exceeding 200KB should produce TxRefScriptsSizeTooBig."""
        sizes = [100_000, 100_000, 50_000]  # 250KB total > 204800
        errors = validate_tx_ref_scripts_size(sizes)
        assert len(errors) == 1
        assert "TxRefScriptsSizeTooBig" in errors[0]
        assert "250000" in errors[0]

    def test_exact_limit_passes(self):
        """Reference scripts exactly at the limit should pass."""
        sizes = [204800]
        errors = validate_tx_ref_scripts_size(sizes)
        assert errors == []

    def test_empty_ref_scripts_passes(self):
        """No reference scripts should pass."""
        errors = validate_tx_ref_scripts_size([])
        assert errors == []

    def test_custom_limit(self):
        """Custom limit should be respected."""
        sizes = [5000]
        errors = validate_tx_ref_scripts_size(sizes, max_ref_script_size=1000)
        assert len(errors) == 1
        assert "TxRefScriptsSizeTooBig" in errors[0]


# ---------------------------------------------------------------------------
# Withdrawal delegation tests (Conway-specific)
# ---------------------------------------------------------------------------


class TestWithdrawalDelegation:
    """Tests for Conway withdrawal delegation requirement.

    Conway requires that reward withdrawals come from stake credentials
    that have delegated voting power to a DRep. This ensures participation
    in governance as a prerequisite for reward withdrawal.

    Spec ref: Conway formal spec, UTXOW rule, withdrawal delegation check.
    Haskell ref: ``notDelegatedAddrs`` check in
        ``Cardano.Ledger.Conway.Rules.Utxow``
    """

    def test_withdrawal_from_delegated_key_succeeds(self):
        """Withdrawal from a credential that has delegated to a DRep
        should produce no errors."""
        cred = make_credential(1)
        drep_cred = make_credential(2)
        drep = DRep(drep_type=DRepType.KEY_HASH, credential=drep_cred)

        state = GovernanceState(
            drep_delegations={cred: drep},
        )

        errors = validate_withdrawal_delegation(cred, state)
        assert errors == []

    def test_withdrawal_from_non_delegated_key_fails(self):
        """Withdrawal from a credential that has NOT delegated to any DRep
        should produce WithdrawalNotDelegated error.

        This is a Conway-specific requirement — pre-Conway, withdrawals
        did not require voting delegation.
        """
        cred = make_credential(1)
        state = GovernanceState()  # No delegations

        errors = validate_withdrawal_delegation(cred, state)
        assert len(errors) == 1
        assert "WithdrawalNotDelegated" in errors[0]

    def test_withdrawal_delegated_to_always_abstain_succeeds(self):
        """Delegation to AlwaysAbstain satisfies the withdrawal requirement."""
        cred = make_credential(1)
        drep = DRep(drep_type=DRepType.ALWAYS_ABSTAIN)

        state = GovernanceState(
            drep_delegations={cred: drep},
        )

        errors = validate_withdrawal_delegation(cred, state)
        assert errors == []


# ---------------------------------------------------------------------------
# ApplyTx integration tests
# ---------------------------------------------------------------------------


class TestApplyConwayTx:
    """Tests for full Conway transaction application through the ledger.

    Spec ref: Conway formal spec, ``GOV`` and ``GOVCERT`` transition rules.
    Haskell ref: ``conwayGovTransition`` in
        ``Cardano.Ledger.Conway.Rules.Gov``
    """

    def test_apply_tx_with_proposals_and_votes(self):
        """A full Conway tx with proposals and votes should update
        governance state correctly: proposals added, votes recorded."""
        drep_cred = make_credential(1)
        tx_id = make_tx_id_bytes(42)

        # Pre-existing state: one DRep registered, one proposal to vote on
        existing_action_id = make_gov_action_id(0)
        existing_proposal = make_proposal(seed=0)

        gov_state = GovernanceState(
            proposals={existing_action_id: existing_proposal},
            votes={existing_action_id: {}},
            dreps={drep_cred: TEST_PARAMS.drep_deposit},
        )

        # Transaction: one new proposal + one vote on existing proposal
        new_proposal = make_proposal(seed=99)
        voter = Voter(role=VoterRole.DREP, credential=drep_cred)

        tx = ConwayTx(
            tx_id=tx_id,
            proposals=[new_proposal],
            voting_procedures={
                voter: {
                    existing_action_id: VotingProcedure(vote=Vote.YES),
                },
            },
        )

        new_state = apply_conway_tx(
            tx,
            gov_state,
            TEST_PARAMS,
            current_epoch=10,
        )

        # Verify: new proposal added
        new_action_id = GovActionId(tx_id=tx_id, gov_action_index=0)
        assert new_action_id in new_state.proposals
        assert new_state.proposals[new_action_id] == new_proposal

        # Verify: vote recorded on existing proposal
        assert voter in new_state.votes[existing_action_id]
        assert new_state.votes[existing_action_id][voter].vote == Vote.YES

        # Verify: existing proposal still present
        assert existing_action_id in new_state.proposals

    def test_apply_tx_with_drep_registration(self):
        """A tx with a DRep registration certificate should register the DRep."""
        drep_cred = make_credential(5)
        tx_id = make_tx_id_bytes(50)

        gov_state = GovernanceState()

        cert = DRepRegistration(
            credential=drep_cred,
            deposit=TEST_PARAMS.drep_deposit,
            anchor=make_anchor(5),
        )

        tx = ConwayTx(
            tx_id=tx_id,
            certificates=[cert],
        )

        new_state = apply_conway_tx(
            tx,
            gov_state,
            TEST_PARAMS,
            current_epoch=10,
        )

        assert drep_cred in new_state.dreps
        assert new_state.dreps[drep_cred] == TEST_PARAMS.drep_deposit

    def test_apply_tx_invalid_proposal_raises(self):
        """A tx with an invalid proposal should raise ConwayValidationError."""
        tx_id = make_tx_id_bytes(60)
        bad_proposal = make_proposal(seed=0, deposit=1)  # Wrong deposit

        tx = ConwayTx(
            tx_id=tx_id,
            proposals=[bad_proposal],
        )

        with pytest.raises(ConwayValidationError, match="ProposalDepositMismatch"):
            apply_conway_tx(
                tx,
                GovernanceState(),
                TEST_PARAMS,
                current_epoch=10,
            )

    def test_apply_tx_invalid_vote_raises(self):
        """A tx voting on a non-existent proposal should raise ConwayValidationError."""
        drep_cred = make_credential(1)
        tx_id = make_tx_id_bytes(70)
        phantom_id = make_gov_action_id(999)

        gov_state = GovernanceState(
            dreps={drep_cred: TEST_PARAMS.drep_deposit},
        )

        voter = Voter(role=VoterRole.DREP, credential=drep_cred)
        tx = ConwayTx(
            tx_id=tx_id,
            voting_procedures={
                voter: {phantom_id: VotingProcedure(vote=Vote.YES)},
            },
        )

        with pytest.raises(ConwayValidationError, match="GovActionIdNotFound"):
            apply_conway_tx(
                tx,
                gov_state,
                TEST_PARAMS,
                current_epoch=10,
            )
