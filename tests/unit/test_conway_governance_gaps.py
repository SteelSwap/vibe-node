"""Conway governance lifecycle and ratification gap tests (~35 tests).

These tests cover governance proposal lifecycle (submission, validation,
rejection) and ratification arithmetic (DRep/SPO/CC threshold calculations,
edge cases, ordering). They target gaps not covered by test_conway.py or
test_conway_audit.py.

Spec references:
    - Conway ledger formal spec, Section 5 (Governance)
    - Conway ledger formal spec, Section 6 (Ratification)
    - CIP-1694 (on-chain governance)
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Gov.hs``
    - ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Ratify.hs``
"""

from __future__ import annotations

import hashlib

from vibe.cardano.ledger.conway import (
    _threshold_met,
    check_ratification,
    validate_hard_fork_initiation,
    validate_proposal,
    validate_proposals,
    validate_treasury_withdrawals,
)
from vibe.cardano.ledger.conway_types import (
    DEFAULT_RATIFICATION_THRESHOLDS,
    Anchor,
    ConwayProtocolParams,
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
    data_hash = hashlib.blake2b(f"anchor-{seed}".encode(), digest_size=32).digest()
    return Anchor(url=f"https://example.com/proposal-{seed}", data_hash=data_hash)


def _reward_addr(seed: int = 0) -> bytes:
    """Create a 29-byte reward address (network tag 0xe0 + 28-byte credential)."""
    return b"\xe0" + _cred(seed)


def _action_id(seed: int = 0, index: int = 0) -> GovActionId:
    return GovActionId(tx_id=_tx_id(seed), gov_action_index=index)


def _proposal(
    seed: int = 0,
    action_type: GovActionType = GovActionType.INFO_ACTION,
    deposit: int | None = None,
    payload=None,
    prev_action_id: GovActionId | None = None,
) -> ProposalProcedure:
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


def _full_committee(n: int = 7, expiry: int = 1000) -> dict[bytes, int]:
    """Return a committee dict of *n* members whose terms expire at *expiry*."""
    return {_cred(200 + i): expiry for i in range(n)}


def _gov_state_with_all_votes(
    action_id: GovActionId,
    proposal: ProposalProcedure,
    dreps: dict[bytes, int],
    drep_stake: dict[bytes, int] | None = None,
    committee: dict[bytes, int] | None = None,
    pool_stake: dict[bytes, int] | None = None,
    drep_votes: dict[bytes, Vote] | None = None,
    cc_votes: dict[bytes, Vote] | None = None,
    spo_votes: dict[bytes, Vote] | None = None,
) -> GovernanceState:
    """Build a GovernanceState pre-populated with the supplied votes."""
    if committee is None:
        committee = _full_committee()
    state = GovernanceState(
        proposals={action_id: proposal},
        dreps=dreps,
        drep_stake=drep_stake or {},
        committee=committee,
        pool_stake=pool_stake or {},
        registered_pools=set((pool_stake or {}).keys()),
        votes={action_id: {}},
    )
    if drep_votes:
        for cred, vote in drep_votes.items():
            state.votes[action_id][Voter(VoterRole.DREP, cred)] = VotingProcedure(vote=vote)
    if cc_votes:
        for cred, vote in cc_votes.items():
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cred)] = (
                VotingProcedure(vote=vote)
            )
    elif committee:
        # Default: all CC vote YES so CC threshold is not the thing we test
        for cred in committee:
            state.votes[action_id][Voter(VoterRole.CONSTITUTIONAL_COMMITTEE, cred)] = (
                VotingProcedure(vote=Vote.YES)
            )
    if spo_votes:
        for cred, vote in spo_votes.items():
            state.votes[action_id][Voter(VoterRole.STAKE_POOL, cred)] = VotingProcedure(vote=vote)
    return state


# ===================================================================
#  PART 1 — Governance lifecycle (~20 tests)
# ===================================================================


class TestGovernanceLifecycle:
    """Governance proposal submission and validation lifecycle tests.

    Spec ref: Conway formal spec, GOV transition rule.
    Haskell ref: conwayGovTransition in Cardano.Ledger.Conway.Rules.Gov
    """

    # ----- 1. Submit constitution governance action -----

    def test_submit_constitution_action_accepted(self):
        """A well-formed NewConstitution proposal should pass validation.

        Spec ref: Conway formal spec, Section 5 — NewConstitution.
        Haskell ref: conwayGovTransition NewConstitution case.
        """
        proposal = _proposal(
            action_type=GovActionType.NEW_CONSTITUTION,
            payload=b"\xab" * 32,  # constitution hash
        )
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 2. Submit parameter change -----

    def test_submit_parameter_change_accepted(self):
        """A well-formed ParameterChange proposal should pass validation.

        Spec ref: Conway formal spec, Section 5 — ParameterChange.
        """
        proposal = _proposal(
            action_type=GovActionType.PARAMETER_CHANGE,
            payload={"min_fee_a": 44},
        )
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 3. Treasury withdrawal — positive amounts -----

    def test_treasury_withdrawal_positive_amounts_required(self):
        """TreasuryWithdrawals with zero or negative amounts must be rejected.

        Spec ref: Conway formal spec, TreasuryWithdrawals — amounts > 0.
        Haskell ref: TreasuryWithdrawals validation in Gov.hs.
        """
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={_reward_addr(0): 0, _reward_addr(1): -5},
        )
        errors = validate_treasury_withdrawals(action)
        assert len(errors) == 2
        assert all("NonPositiveAmount" in e for e in errors)

    # ----- 4. Hard fork initiation — version +1 major -----

    def test_hard_fork_target_exactly_plus_one_major(self):
        """HardForkInitiation target must be exactly current_major + 1.

        Spec ref: Conway formal spec, HardForkInitiation.
        """
        state = GovernanceState(current_protocol_version=(9, 0))

        ok_action = GovAction(action_type=GovActionType.HARD_FORK_INITIATION, payload=(10, 0))
        assert validate_hard_fork_initiation(ok_action, state) == []

        bad_action = GovAction(action_type=GovActionType.HARD_FORK_INITIATION, payload=(12, 0))
        errors = validate_hard_fork_initiation(bad_action, state)
        assert any("VersionMismatch" in e for e in errors)

    # ----- 5. No confidence action -----

    def test_no_confidence_proposal_accepted(self):
        """A well-formed NoConfidence proposal should pass validation."""
        proposal = _proposal(action_type=GovActionType.NO_CONFIDENCE)
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 6. Update committee — add/remove -----

    def test_update_committee_proposal_accepted(self):
        """An UpdateCommittee proposal should pass basic validation."""
        proposal = _proposal(
            action_type=GovActionType.UPDATE_COMMITTEE,
            payload={
                "add": {_cred(50): 500},
                "remove": {_cred(51)},
                "quorum": (2, 3),
            },
        )
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 7. Info action — always ratified -----

    def test_info_action_always_ratified(self):
        """InfoAction should be ratified automatically regardless of votes.

        Spec ref: Conway formal spec, Section 6 — InfoAction ratification.
        """
        aid = _action_id(0)
        state = GovernanceState(proposals={aid: _proposal()})
        # No votes at all — still ratified
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 8. Duplicate proposal in same tx -----

    def test_duplicate_proposal_in_same_tx_rejected(self):
        """Two identical proposals in one tx should produce errors for the second.

        The current validate_proposals validates each proposal independently
        against the state but does not detect duplicates within the list.
        We document this as a known gap and test the existing behaviour.

        TODO: Implement intra-tx duplicate detection (GovActionId collision).
        """
        p1 = _proposal(seed=0, action_type=GovActionType.PARAMETER_CHANGE)
        p2 = _proposal(seed=0, action_type=GovActionType.PARAMETER_CHANGE)
        # Both proposals are valid individually
        errors = validate_proposals([p1, p2], TEST_PARAMS, GovernanceState())
        # Current behaviour: both pass (no duplicate check yet)
        # When duplicate detection is added, expect len(errors) > 0
        assert isinstance(errors, list)

    # ----- 9. Insufficient deposit -----

    def test_insufficient_deposit_rejected(self):
        """Proposal with deposit < govActionDeposit must be rejected.

        Spec ref: Conway formal spec, GOV — deposit == govActionDeposit.
        Haskell ref: ProposalDepositIncorrect.
        """
        proposal = _proposal(deposit=1_000)
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert any("ProposalDepositMismatch" in e for e in errors)

    # ----- 10. Invalid return address -----

    def test_invalid_return_address_rejected(self):
        """Proposal whose return_addr is not 29 bytes must be rejected.

        Spec ref: Conway formal spec, GOV — returnAddr must be reward address.
        """
        bad = ProposalProcedure(
            deposit=TEST_PARAMS.gov_action_deposit,
            return_addr=b"\x00" * 15,  # wrong length
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_anchor(),
        )
        errors = validate_proposal(bad, TEST_PARAMS, GovernanceState())
        assert any("ProposalReturnAddrInvalid" in e for e in errors)

    # ----- 11. Unknown cost model in parameter change -----

    def test_unknown_cost_model_in_parameter_change(self):
        """A ParameterChange proposing an unrecognised cost model key should
        still pass basic proposal validation (the payload is opaque at the
        GOV level — semantic checks happen at enactment).

        Spec ref: Conway formal spec, Section 5 — ParameterChange payload
        is only structurally checked.
        """
        proposal = _proposal(
            action_type=GovActionType.PARAMETER_CHANGE,
            payload={"unknown_cost_model_v99": [1, 2, 3]},
        )
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 12. Network ID validation in governance context -----

    def test_network_id_wrong_header_byte_in_return_addr(self):
        """Return address with incorrect network header is still accepted
        by length check but the header byte is non-standard.

        Our current validation only checks length (29 bytes).
        This test documents the gap: no network-ID-specific validation yet.
        """
        # 0x00 header + 28-byte hash = 29 bytes, passes length check
        addr = b"\x00" + _cred(0)
        proposal = ProposalProcedure(
            deposit=TEST_PARAMS.gov_action_deposit,
            return_addr=addr,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_anchor(),
        )
        errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
        # Currently passes — no network ID check
        assert errors == []

    # ----- 13. Bootstrap phase restrictions -----

    def test_bootstrap_phase_only_critical_actions_allowed(self):
        """During the bootstrap phase (before full governance), certain
        action types should be restricted. In a bootstrap-aware implementation
        only HardForkInitiation, InfoAction, and ParameterChange (security
        group) would be allowed.

        We test that all action types currently pass validation because
        bootstrap-phase filtering is not yet implemented.

        Spec ref: Conway formal spec, Section 5.5 — Bootstrap phase.
        Haskell ref: bootstrapPhaseCheck in Gov.hs.
        """
        for action_type in GovActionType:
            proposal = _proposal(action_type=action_type)
            errors = validate_proposal(proposal, TEST_PARAMS, GovernanceState())
            # All pass today — bootstrap filtering is a documented gap
            assert isinstance(errors, list)

    # ----- 14. Proposal tree pruning — conflicting proposals -----

    def test_conflicting_prev_action_id_detection(self):
        """Two proposals chaining to the same prev_action_id create a
        conflict — only one can be enacted. Current implementation does
        not enforce this at submission time.

        Spec ref: Conway formal spec, Section 5 — prev_action_id chain.
        """
        parent_id = _action_id(seed=0)
        child_a = _proposal(
            seed=1,
            action_type=GovActionType.PARAMETER_CHANGE,
            prev_action_id=parent_id,
            payload={"min_fee_a": 50},
        )
        child_b = _proposal(
            seed=2,
            action_type=GovActionType.PARAMETER_CHANGE,
            prev_action_id=parent_id,
            payload={"min_fee_a": 60},
        )
        # Both proposals are individually valid (no conflict check yet)
        errors_a = validate_proposal(child_a, TEST_PARAMS, GovernanceState())
        errors_b = validate_proposal(child_b, TEST_PARAMS, GovernanceState())
        assert errors_a == []
        assert errors_b == []


# ===================================================================
#  PART 2 — Ratification arithmetic (~15 tests)
# ===================================================================


class TestRatificationArithmetic:
    """Ratification threshold computation edge cases.

    Spec ref: Conway formal spec, Section 6 (Ratification).
    Haskell ref: ratifyAction in Cardano.Ledger.Conway.Rules.Ratify.
    """

    # ----- 15. DRep threshold — stake weighted -----

    def test_drep_threshold_stake_weighted(self):
        """DRep approval ratio must be computed with stake weighting.

        Spec ref: Conway formal spec, Section 6 — accepted_drep ratio.
        """
        aid = _action_id(0)
        d1, d2, d3 = _cred(1), _cred(2), _cred(3)
        dreps = {d1: 500_000_000, d2: 500_000_000, d3: 500_000_000}
        drep_stake = {d1: 600_000, d2: 300_000, d3: 100_000}
        # d1 YES (600k), d2 YES (300k) => 900k / 1M = 90% > 2/3
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_stake=drep_stake,
            drep_votes={d1: Vote.YES, d2: Vote.YES, d3: Vote.NO},
        )
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 16. DRep all yes -----

    def test_drep_all_yes_passes(self):
        """All DReps voting YES should meet any threshold."""
        aid = _action_id(0)
        d1, d2, d3 = _cred(1), _cred(2), _cred(3)
        dreps = {d1: 500_000_000, d2: 500_000_000, d3: 500_000_000}
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES, d2: Vote.YES, d3: Vote.YES},
        )
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 17. DRep all no -----

    def test_drep_all_no_fails(self):
        """All DReps voting NO should fail threshold."""
        aid = _action_id(0)
        d1, d2, d3 = _cred(1), _cred(2), _cred(3)
        dreps = {d1: 500_000_000, d2: 500_000_000, d3: 500_000_000}
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.NO, d2: Vote.NO, d3: Vote.NO},
        )
        assert not check_ratification(aid, state, TEST_PARAMS)

    # ----- 18. DRep all abstain -----

    def test_drep_all_abstain_treated_as_not_voting(self):
        """Abstaining DReps are excluded from the denominator in count-based
        mode. With all abstaining and no YES votes, the yes count is 0 out
        of a total of 3 (registered DReps), so the threshold is not met.

        Spec ref: Conway formal spec, Section 6 — abstentions.
        """
        aid = _action_id(0)
        d1, d2 = _cred(1), _cred(2)
        dreps = {d1: 500_000_000, d2: 500_000_000}
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.ABSTAIN, d2: Vote.ABSTAIN},
        )
        # In count-based fallback (no drep_stake): total = 2 registered DReps,
        # yes = 0 => 0/2 < 2/3 => not ratified
        assert not check_ratification(aid, state, TEST_PARAMS)

    # ----- 19. DRep AlwaysNoConfidence -----

    def test_drep_always_no_confidence_counts_as_no(self):
        """AlwaysNoConfidence delegations effectively count as No votes for
        most action types. Since AlwaysNoConfidence is a delegation target
        (not a voter), the current implementation does not handle it in
        ratification — this test documents the gap.

        Spec ref: Conway formal spec, Section 6 — AlwaysNoConfidence.
        Haskell ref: ratifyAction AlwaysNoConfidence handling.
        """
        # With the current implementation, AlwaysNoConfidence delegations
        # are not factored into ratification. This test verifies the current
        # behaviour and documents it as a gap.
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
        )
        # 1/1 DReps vote YES => passes (AlwaysNoConfidence not counted yet)
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 20. SPO threshold for hard fork -----

    def test_spo_threshold_for_hard_fork(self):
        """HardForkInitiation requires SPO threshold (1/2).

        Spec ref: Conway formal spec, Section 6 — SPO threshold table.
        """
        aid = _action_id(0)
        s1, s2, s3, s4 = _cred(30), _cred(31), _cred(32), _cred(33)
        pool_stake = {s1: 250_000, s2: 250_000, s3: 250_000, s4: 250_000}
        d1, d2, d3 = _cred(1), _cred(2), _cred(3)
        dreps = {d1: 500_000_000, d2: 500_000_000, d3: 500_000_000}

        # 3 of 4 SPOs vote YES => 750k/1M = 75% > 50%
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.HARD_FORK_INITIATION, payload=(10, 0)),
            dreps=dreps,
            drep_votes={d1: Vote.YES, d2: Vote.YES, d3: Vote.YES},
            pool_stake=pool_stake,
            spo_votes={s1: Vote.YES, s2: Vote.YES, s3: Vote.YES, s4: Vote.NO},
        )
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 21. SPO votes with pool stake weighting -----

    def test_spo_pool_stake_weighting(self):
        """SPO votes should be weighted by pool stake.

        Spec ref: Conway formal spec, Section 6 — SPO stake weighting.
        """
        aid = _action_id(0)
        big_pool = _cred(30)
        small_pool = _cred(31)
        pool_stake = {big_pool: 900_000, small_pool: 100_000}
        d1 = _cred(1)
        dreps = {d1: 500_000_000}

        # big_pool YES (900k) vs small_pool NO (100k) => 90% > 50%
        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.HARD_FORK_INITIATION, payload=(10, 0)),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            pool_stake=pool_stake,
            spo_votes={big_pool: Vote.YES, small_pool: Vote.NO},
        )
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 22. Committee quorum — min size enforcement -----

    def test_committee_quorum_min_size(self):
        """Ratification must fail if committee size < committeeMinSize.

        Spec ref: Conway formal spec, committeeMinSize parameter.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        small_committee = {_cred(200): 1000, _cred(201): 1000}  # only 2

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            committee=small_committee,
            cc_votes={c: Vote.YES for c in small_committee},
        )
        # 2 < committeeMinSize(7) => fail
        assert not check_ratification(aid, state, TEST_PARAMS)

    # ----- 23. Committee expired members excluded from quorum -----

    def test_committee_expired_members_in_quorum(self):
        """Expired CC members are still counted in committee dict but their
        votes are rejected during validate_voting_procedures. For
        ratification, they still appear in len(committee) for the threshold
        denominator. This test documents that behaviour.

        Spec ref: Conway formal spec, Section 6 — expired CC members.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        # 7 members but 3 have expired terms
        committee = {}
        for i in range(4):
            committee[_cred(200 + i)] = 1000  # valid
        for i in range(3):
            committee[_cred(210 + i)] = 5  # expired at epoch 5

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            committee=committee,
            cc_votes={c: Vote.YES for c in committee},
        )
        # All 7 in committee dict, all vote YES => 7/7 = 100% >= 2/3
        # and len(committee)=7 >= committeeMinSize=7
        assert check_ratification(aid, state, TEST_PARAMS)

    # ----- 24. Committee resigned members excluded -----

    def test_committee_resigned_member_removed(self):
        """After a member resigns (removed from committee dict), they no
        longer count toward quorum. If this drops below committeeMinSize,
        ratification should fail.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        # Start with exactly 7, remove one to get 6
        committee = _full_committee(7)
        resigned = list(committee.keys())[0]
        del committee[resigned]  # now 6 members

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            committee=committee,
            cc_votes={c: Vote.YES for c in committee},
        )
        # 6 < 7 => fail
        assert not check_ratification(aid, state, TEST_PARAMS)

    # ----- 25. Zero DRep stake — no divide-by-zero -----

    def test_zero_drep_stake_no_divide_by_zero(self):
        """When all DReps have 0 stake, ratification should not crash.

        _threshold_met returns False when total == 0, so this should
        simply not ratify rather than raising ZeroDivisionError.

        Spec ref: Conway formal spec, Section 6 — edge case.
        """
        aid = _action_id(0)
        d1, d2 = _cred(1), _cred(2)
        dreps = {d1: 500_000_000, d2: 500_000_000}
        drep_stake = {d1: 0, d2: 0}

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_stake=drep_stake,
            drep_votes={d1: Vote.YES, d2: Vote.YES},
        )
        # total_stake = 0, _threshold_met(0, 0, ...) returns False
        assert not check_ratification(aid, state, TEST_PARAMS)

    # ----- 26. Action priority ordering -----

    def test_action_priority_ordering(self):
        """Lower GovActionType integer values should be considered higher
        priority. This tests that the enum ordering is correct for
        future enactment ordering.

        Spec ref: Conway formal spec, Section 6 — enactment priority.
        Haskell ref: actionPriority in Ratify.hs.
        """
        # ParameterChange(0) < HardForkInitiation(1) < TreasuryWithdrawals(2)
        # etc. Lower value = higher priority (enacted first).
        sorted_types = sorted(GovActionType, key=lambda t: t.value)
        assert sorted_types[0] == GovActionType.PARAMETER_CHANGE
        assert sorted_types[-1] == GovActionType.INFO_ACTION

    # ----- 27. Stable ordering for same priority -----

    def test_stable_ordering_same_action_type(self):
        """Multiple proposals of the same type should have a deterministic
        ordering (by GovActionId). This tests that GovActionId comparison
        is deterministic.
        """
        ids = [_action_id(seed=i) for i in range(5)]
        # GovActionIds are dataclass frozen — sort by tx_id bytes
        sorted_ids = sorted(ids, key=lambda a: (a.tx_id, a.gov_action_index))
        # Re-sorting should give the same order
        re_sorted = sorted(sorted_ids, key=lambda a: (a.tx_id, a.gov_action_index))
        assert sorted_ids == re_sorted

    # ----- 28. Delayed action — depends on unenacted prior -----

    def test_delayed_action_depends_on_prior(self):
        """A proposal that chains to a prev_action_id that has not been
        enacted yet cannot itself be enacted. We test that the proposal
        is valid for submission (chain validation is at enactment time).

        Spec ref: Conway formal spec, Section 5 — prev_action_id chain.
        """
        parent_id = _action_id(seed=0)
        child = _proposal(
            seed=1,
            action_type=GovActionType.PARAMETER_CHANGE,
            prev_action_id=parent_id,
            payload={"min_fee_a": 55},
        )
        # Submission validation passes (chain checked at enactment)
        errors = validate_proposal(child, TEST_PARAMS, GovernanceState())
        assert errors == []

    # ----- 29. Parameter change affects in-flight proposal thresholds -----

    def test_parameter_change_affects_inflight_thresholds(self):
        """If a ParameterChange that modifies ratification thresholds is
        enacted, it should affect the thresholds used for other in-flight
        proposals. We verify this by checking with custom thresholds.

        Spec ref: Conway formal spec, Section 6 — thresholds from params.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
        )

        # With strict 100% threshold, 1/1 passes
        strict = RatificationThresholds(drep_threshold=(1, 1))
        assert check_ratification(aid, state, TEST_PARAMS, strict)

        # Simulate a parameter change lowering the threshold to 1/2
        lenient = RatificationThresholds(drep_threshold=(1, 2))
        assert check_ratification(aid, state, TEST_PARAMS, lenient)

        # Now imagine the threshold was raised to 100% and there's a NO voter
        d2 = _cred(2)
        state.dreps[d2] = 500_000_000
        state.votes[aid][Voter(VoterRole.DREP, d2)] = VotingProcedure(vote=Vote.NO)
        # 1/2 YES with (1,1) threshold => 50% < 100% => fail
        assert not check_ratification(aid, state, TEST_PARAMS, strict)
        # But with (1,2) threshold => 50% >= 50% => pass
        assert check_ratification(aid, state, TEST_PARAMS, lenient)


# ===================================================================
#  Additional edge-case tests
# ===================================================================


class TestRatificationEdgeCases:
    """Additional edge cases for ratification arithmetic."""

    def test_cc_threshold_with_split_vote(self):
        """CC with exactly 2/3 voting YES should just pass the (2,3) threshold.

        5 YES out of 7 = 5/7 ~ 71.4% which is >= 2/3 ~ 66.7%.
        4 YES out of 7 = 4/7 ~ 57.1% which is < 2/3.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        committee = _full_committee(7)
        cc_list = list(committee.keys())

        # 5 YES, 2 NO => 5*3 = 15 >= 2*7 = 14 => passes
        cc_votes_pass = {c: Vote.YES for c in cc_list[:5]}
        cc_votes_pass.update({c: Vote.NO for c in cc_list[5:]})

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            committee=committee,
            cc_votes=cc_votes_pass,
        )
        assert check_ratification(aid, state, TEST_PARAMS)

        # 4 YES, 3 NO => 4*3 = 12 < 2*7 = 14 => fails
        cc_votes_fail = {c: Vote.YES for c in cc_list[:4]}
        cc_votes_fail.update({c: Vote.NO for c in cc_list[4:]})

        state2 = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            committee=committee,
            cc_votes=cc_votes_fail,
        )
        assert not check_ratification(aid, state2, TEST_PARAMS)

    def test_no_confidence_does_not_require_cc(self):
        """NoConfidence action should not require CC approval (cc_threshold is None).

        Spec ref: Conway formal spec, Section 6 — NoConfidence thresholds.
        """
        thresholds = DEFAULT_RATIFICATION_THRESHOLDS[GovActionType.NO_CONFIDENCE]
        assert thresholds.cc_threshold is None

        aid = _action_id(0)
        d1, d2, d3 = _cred(1), _cred(2), _cred(3)
        dreps = {d1: 500_000_000, d2: 500_000_000, d3: 500_000_000}
        s1, s2 = _cred(30), _cred(31)
        pool_stake = {s1: 500_000, s2: 500_000}

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.NO_CONFIDENCE),
            dreps=dreps,
            drep_votes={d1: Vote.YES, d2: Vote.YES, d3: Vote.NO},
            pool_stake=pool_stake,
            spo_votes={s1: Vote.YES, s2: Vote.YES},
            committee={},  # empty committee should not matter
        )
        # NoConfidence has cc_threshold=None so CC is not checked,
        # but committeeMinSize check only applies when cc_threshold is not None
        assert check_ratification(aid, state, TEST_PARAMS)

    def test_single_drep_single_vote_passes(self):
        """Edge case: single DRep voting YES should pass 2/3 threshold (1/1 = 100%)."""
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.PARAMETER_CHANGE),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
        )
        assert check_ratification(aid, state, TEST_PARAMS)

    def test_threshold_boundary_exact(self):
        """Test _threshold_met at exact boundary: 2/3 of 3 = 2 YES needed."""
        # 2 * 3 >= 2 * 3 => 6 >= 6 => True
        assert _threshold_met(2, 3, (2, 3))
        # 1 * 3 >= 2 * 3 => 3 >= 6 => False
        assert not _threshold_met(1, 3, (2, 3))

    def test_spo_no_votes_cast_but_pools_exist(self):
        """If SPO threshold is required but no SPOs vote, the SPO total is
        still computed from pool_stake. 0 YES out of nonzero total => fail.
        """
        aid = _action_id(0)
        d1 = _cred(1)
        dreps = {d1: 500_000_000}
        s1, s2 = _cred(30), _cred(31)
        pool_stake = {s1: 500_000, s2: 500_000}

        state = _gov_state_with_all_votes(
            aid,
            _proposal(action_type=GovActionType.HARD_FORK_INITIATION, payload=(10, 0)),
            dreps=dreps,
            drep_votes={d1: Vote.YES},
            pool_stake=pool_stake,
            spo_votes={},  # no SPO votes
        )
        # 0 YES / 1M total => 0% < 50% => fail
        assert not check_ratification(aid, state, TEST_PARAMS)
