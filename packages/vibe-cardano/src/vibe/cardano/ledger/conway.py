"""Conway-era ledger validation rules: governance actions, voting, DRep delegation.

Conway extends Babbage with on-chain governance (CIP-1694), adding:

Governance rules:
    - **ProposalDepositMismatch**: Proposal deposit must match govActionDeposit param
    - **ProposalReturnAddrNotReward**: Return address must be a valid reward address
    - **ProposalExpired**: Proposals expire after govActionLifetime epochs
    - **DuplicateGovActionId**: No duplicate governance action IDs in a tx

DRep rules:
    - **DRepAlreadyRegistered**: Cannot register an already-registered DRep
    - **DRepNotRegistered**: Cannot deregister/update an unregistered DRep
    - **DRepDepositMismatch**: DRep deposit must match drepDeposit param
    - **DelegVoteNotRegistered**: Delegator credential must be registered

Voting rules:
    - **VoterNotAuthorized**: Voter must be authorized for their role
    - **VotingOnExpiredProposal**: Cannot vote on an expired proposal
    - **GovActionIdNotFound**: Voted-on proposal must exist

Ratification (simplified):
    - Check approval thresholds per action type
    - Enactment at epoch boundary when thresholds are met

Spec references:
    * Conway ledger formal spec, Section 5 (Governance)
    * Conway ledger formal spec, Section 6 (Ratification)
    * CIP-1694 (on-chain governance)
    * ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/Gov.hs``
    * ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Rules/GovCert.hs``

Haskell references:
    * ``conwayGovTransition`` in ``Cardano.Ledger.Conway.Rules.Gov``
    * ``ConwayGovPredFailure``: ProposalDepositIncorrect, etc.
    * ``conwayGovCertTransition`` in ``Cardano.Ledger.Conway.Rules.GovCert``
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from vibe.cardano.ledger.conway_types import (
    Anchor,
    ConwayCertificate,
    ConwayProtocolParams,
    DEFAULT_RATIFICATION_THRESHOLDS,
    DelegVote,
    DRep,
    DRepDeregistration,
    DRepRegistration,
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
    VotingProcedures,
)


# ---------------------------------------------------------------------------
# Proposal validation
# ---------------------------------------------------------------------------


def validate_proposal(
    proposal: ProposalProcedure,
    params: ConwayProtocolParams,
    gov_state: GovernanceState,
) -> list[str]:
    """Validate a governance proposal procedure.

    Spec ref: Conway formal spec, ``GOV`` transition rule for proposals.
    Haskell ref: ``conwayGovTransition`` proposal validation in
        ``Cardano.Ledger.Conway.Rules.Gov``

    Args:
        proposal: The proposal to validate.
        params: Conway protocol parameters.
        gov_state: Current governance state.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    # --- Deposit must match govActionDeposit ---
    # Spec: deposit == govActionDeposit pp
    # Haskell: ProposalDepositIncorrect
    if proposal.deposit != params.gov_action_deposit:
        errors.append(
            f"ProposalDepositMismatch: deposit={proposal.deposit}, "
            f"required={params.gov_action_deposit}"
        )

    # --- Return address must be a valid reward address (29 bytes) ---
    # Spec: returnAddr must be a valid reward address
    # Haskell: ProposalProcedureNetworkIdMismatch (simplified)
    if len(proposal.return_addr) != 29:
        errors.append(
            f"ProposalReturnAddrInvalid: return address is "
            f"{len(proposal.return_addr)} bytes, expected 29"
        )

    # --- Anchor URL must not be empty ---
    if not proposal.anchor.url:
        errors.append("ProposalAnchorEmpty: proposal anchor URL is empty")

    # --- Anchor data hash must be 32 bytes ---
    if len(proposal.anchor.data_hash) != 32:
        errors.append(
            f"ProposalAnchorHashInvalid: anchor hash is "
            f"{len(proposal.anchor.data_hash)} bytes, expected 32"
        )

    return errors


def validate_proposals(
    proposals: list[ProposalProcedure],
    params: ConwayProtocolParams,
    gov_state: GovernanceState,
) -> list[str]:
    """Validate all proposals in a transaction.

    Args:
        proposals: List of proposals.
        params: Conway protocol parameters.
        gov_state: Current governance state.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []
    for i, prop in enumerate(proposals):
        prop_errors = validate_proposal(prop, params, gov_state)
        for err in prop_errors:
            errors.append(f"Proposal[{i}]: {err}")
    return errors


# ---------------------------------------------------------------------------
# DRep certificate processing
# ---------------------------------------------------------------------------


def process_drep_registration(
    cert: DRepRegistration,
    gov_state: GovernanceState,
    params: ConwayProtocolParams,
) -> GovernanceState:
    """Process a DRep registration certificate.

    Spec (GOVCERT rule, RegDRep case):
        - Precondition: credential not in dom dreps (not already registered)
        - Precondition: deposit == drepDeposit pp
        - Effect: dreps' = dreps union {credential -> deposit}

    Haskell ref: ``conwayGovCertTransition`` RegDRep case in
        ``Cardano.Ledger.Conway.Rules.GovCert``

    Raises:
        ConwayGovernanceError: DRepAlreadyRegistered, DRepDepositMismatch
    """
    if cert.credential in gov_state.dreps:
        raise ConwayGovernanceError(
            f"DRepAlreadyRegistered: credential {cert.credential.hex()[:16]}... "
            f"is already registered"
        )

    if cert.deposit != params.drep_deposit:
        raise ConwayGovernanceError(
            f"DRepDepositMismatch: deposit={cert.deposit}, "
            f"required={params.drep_deposit}"
        )

    new_state = deepcopy(gov_state)
    new_state.dreps[cert.credential] = cert.deposit
    return new_state


def process_drep_deregistration(
    cert: DRepDeregistration,
    gov_state: GovernanceState,
) -> GovernanceState:
    """Process a DRep deregistration certificate.

    Spec (GOVCERT rule, UnRegDRep case):
        - Precondition: credential in dom dreps (must be registered)
        - Precondition: deposit_refund == dreps[credential]
        - Effect: dreps' = dreps \\ {credential}

    Haskell ref: ``conwayGovCertTransition`` UnRegDRep case in
        ``Cardano.Ledger.Conway.Rules.GovCert``

    Raises:
        ConwayGovernanceError: DRepNotRegistered, DRepDepositRefundMismatch
    """
    if cert.credential not in gov_state.dreps:
        raise ConwayGovernanceError(
            f"DRepNotRegistered: credential {cert.credential.hex()[:16]}... "
            f"is not registered"
        )

    if cert.deposit_refund != gov_state.dreps[cert.credential]:
        raise ConwayGovernanceError(
            f"DRepDepositRefundMismatch: refund={cert.deposit_refund}, "
            f"expected={gov_state.dreps[cert.credential]}"
        )

    new_state = deepcopy(gov_state)
    del new_state.dreps[cert.credential]
    # Remove delegations pointing to this DRep
    new_state.drep_delegations = {
        k: v for k, v in new_state.drep_delegations.items()
        if not (v.credential == cert.credential)
    }
    return new_state


def process_drep_update(
    cert: DRepUpdate,
    gov_state: GovernanceState,
) -> GovernanceState:
    """Process a DRep update certificate (metadata update).

    Spec (GOVCERT rule, UpdateDRep case):
        - Precondition: credential in dom dreps (must be registered)
        - Effect: no state change (metadata is off-chain via anchor)

    Haskell ref: ``conwayGovCertTransition`` UpdateDRep case in
        ``Cardano.Ledger.Conway.Rules.GovCert``

    Raises:
        ConwayGovernanceError: DRepNotRegistered
    """
    if cert.credential not in gov_state.dreps:
        raise ConwayGovernanceError(
            f"DRepNotRegistered: credential {cert.credential.hex()[:16]}... "
            f"is not registered — cannot update"
        )

    # DRep update is a no-op on-chain (metadata is off-chain)
    return gov_state


def process_deleg_vote(
    cert: DelegVote,
    gov_state: GovernanceState,
    registered_credentials: set[bytes],
) -> GovernanceState:
    """Process a vote delegation certificate.

    Spec (GOVCERT rule, DelegVote case):
        - Precondition: credential in dom rewards (stake cred must be registered)
        - Precondition: if DRep is key/script, it must be registered
        - Effect: drep_delegations' = drep_delegations union {credential -> drep}

    Haskell ref: ``conwayGovCertTransition`` DelegVote case in
        ``Cardano.Ledger.Conway.Rules.GovCert``

    Args:
        cert: The delegation certificate.
        gov_state: Current governance state.
        registered_credentials: Set of registered stake credential hashes.

    Raises:
        ConwayGovernanceError: DelegVoteNotRegistered, DRepNotRegistered
    """
    if cert.credential not in registered_credentials:
        raise ConwayGovernanceError(
            f"DelegVoteNotRegistered: stake credential "
            f"{cert.credential.hex()[:16]}... is not registered"
        )

    # For key/script DReps, the DRep must be registered
    from vibe.cardano.ledger.conway_types import DRepType
    if cert.drep.drep_type in (DRepType.KEY_HASH, DRepType.SCRIPT_HASH):
        if cert.drep.credential not in gov_state.dreps:
            raise ConwayGovernanceError(
                f"DRepNotRegistered: DRep {cert.drep.credential.hex()[:16]}... "  # type: ignore[union-attr]
                f"is not registered — cannot delegate to it"
            )

    new_state = deepcopy(gov_state)
    new_state.drep_delegations[cert.credential] = cert.drep
    return new_state


# ---------------------------------------------------------------------------
# Certificate dispatch
# ---------------------------------------------------------------------------


def process_conway_certificate(
    cert: ConwayCertificate,
    gov_state: GovernanceState,
    params: ConwayProtocolParams,
    registered_credentials: set[bytes] | None = None,
) -> GovernanceState:
    """Process a single Conway governance certificate.

    Routes to the appropriate handler based on certificate type.

    Args:
        cert: The certificate to process.
        gov_state: Current governance state.
        params: Conway protocol parameters.
        registered_credentials: Set of registered stake credential hashes
            (needed for DelegVote validation).

    Returns:
        New GovernanceState with the certificate applied.

    Raises:
        ConwayGovernanceError: If the certificate violates any rule.
        TypeError: If the certificate type is not recognized.
    """
    if registered_credentials is None:
        registered_credentials = set()

    if isinstance(cert, DRepRegistration):
        return process_drep_registration(cert, gov_state, params)
    elif isinstance(cert, DRepDeregistration):
        return process_drep_deregistration(cert, gov_state)
    elif isinstance(cert, DRepUpdate):
        return process_drep_update(cert, gov_state)
    elif isinstance(cert, DelegVote):
        return process_deleg_vote(cert, gov_state, registered_credentials)
    else:
        raise TypeError(f"Unrecognized Conway certificate type: {type(cert).__name__}")


# ---------------------------------------------------------------------------
# Voting validation
# ---------------------------------------------------------------------------


def validate_voting_procedures(
    voting_procedures: VotingProcedures,
    gov_state: GovernanceState,
    current_epoch: int,
    params: ConwayProtocolParams,
) -> list[str]:
    """Validate all voting procedures in a transaction.

    Spec ref: Conway formal spec, ``GOV`` transition rule for votes.
    Haskell ref: ``conwayGovTransition`` voting validation in
        ``Cardano.Ledger.Conway.Rules.Gov``

    Args:
        voting_procedures: All votes in the transaction.
        gov_state: Current governance state.
        current_epoch: Current epoch number.
        params: Conway protocol parameters.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    for voter, votes in voting_procedures.items():
        # --- Voter authorization ---
        if voter.role == VoterRole.CONSTITUTIONAL_COMMITTEE:
            # CC member must be in the committee
            if voter.credential not in gov_state.committee:
                errors.append(
                    f"VoterNotAuthorized: CC member "
                    f"{voter.credential.hex()[:16]}... not in committee"
                )
            elif gov_state.committee[voter.credential] < current_epoch:
                errors.append(
                    f"VoterExpired: CC member "
                    f"{voter.credential.hex()[:16]}... term expired at epoch "
                    f"{gov_state.committee[voter.credential]}"
                )

        elif voter.role == VoterRole.DREP:
            # DRep must be registered
            if voter.credential not in gov_state.dreps:
                errors.append(
                    f"VoterNotAuthorized: DRep "
                    f"{voter.credential.hex()[:16]}... not registered"
                )

        # SPOs: we'd check pool registration, but that's in delegation state
        # which we don't have here. Simplified: always allow SPOs.

        # --- Each voted-on proposal must exist ---
        for action_id in votes:
            if action_id not in gov_state.proposals:
                errors.append(
                    f"GovActionIdNotFound: action "
                    f"tx_id={action_id.tx_id.hex()[:16]}..., "
                    f"index={action_id.gov_action_index} "
                    f"not found in active proposals"
                )

    return errors


# ---------------------------------------------------------------------------
# Ratification
# ---------------------------------------------------------------------------


def _threshold_met(
    yes_count: int,
    total_count: int,
    threshold: tuple[int, int],
) -> bool:
    """Check if a voting threshold is met.

    Uses integer arithmetic to avoid floating point:
        yes_count * denominator >= threshold_numerator * total_count

    Args:
        yes_count: Number of yes votes.
        total_count: Total eligible voters (excluding abstentions in some cases).
        threshold: (numerator, denominator) tuple.

    Returns:
        True if the threshold is met.
    """
    if total_count == 0:
        return False
    num, denom = threshold
    return yes_count * denom >= num * total_count


def check_ratification(
    action_id: GovActionId,
    gov_state: GovernanceState,
    params: ConwayProtocolParams,
    thresholds: RatificationThresholds | None = None,
) -> bool:
    """Check if a governance action has been ratified.

    Ratification requires meeting all applicable thresholds for the
    action type. InfoActions are automatically ratified.

    Spec ref: Conway formal spec, Section 6 (Ratification).
    Haskell ref: ``ratifyAction`` in
        ``Cardano.Ledger.Conway.Rules.Ratify``

    Args:
        action_id: The governance action to check.
        gov_state: Current governance state with votes.
        params: Conway protocol parameters.
        thresholds: Override thresholds (default: from action type).

    Returns:
        True if the action is ratified.
    """
    if action_id not in gov_state.proposals:
        return False

    proposal = gov_state.proposals[action_id]
    action_type = proposal.gov_action.action_type

    # InfoAction is automatically ratified
    if action_type == GovActionType.INFO_ACTION:
        return True

    if thresholds is None:
        thresholds = DEFAULT_RATIFICATION_THRESHOLDS.get(
            action_type,
            RatificationThresholds(),
        )

    # Collect votes for this action
    action_votes = gov_state.votes.get(action_id, {})

    # --- CC threshold ---
    if thresholds.cc_threshold is not None:
        cc_yes = 0
        cc_total = len(gov_state.committee)
        for voter, procedure in action_votes.items():
            if voter.role == VoterRole.CONSTITUTIONAL_COMMITTEE:
                if procedure.vote == Vote.YES:
                    cc_yes += 1
        if not _threshold_met(cc_yes, cc_total, thresholds.cc_threshold):
            return False

    # --- DRep threshold ---
    if thresholds.drep_threshold is not None:
        drep_yes = 0
        drep_total = len(gov_state.dreps)
        for voter, procedure in action_votes.items():
            if voter.role == VoterRole.DREP:
                if procedure.vote == Vote.YES:
                    drep_yes += 1
        if not _threshold_met(drep_yes, drep_total, thresholds.drep_threshold):
            return False

    # --- SPO threshold ---
    if thresholds.spo_threshold is not None:
        spo_yes = 0
        spo_total = 0  # We'd need pool count — simplified: count voters
        for voter, procedure in action_votes.items():
            if voter.role == VoterRole.STAKE_POOL:
                spo_total += 1
                if procedure.vote == Vote.YES:
                    spo_yes += 1
        if spo_total > 0 and not _threshold_met(
            spo_yes, spo_total, thresholds.spo_threshold
        ):
            return False

    return True


# ---------------------------------------------------------------------------
# Proposal expiry
# ---------------------------------------------------------------------------


def expire_proposals(
    gov_state: GovernanceState,
    current_epoch: int,
    proposal_epochs: dict[GovActionId, int],
    params: ConwayProtocolParams,
) -> GovernanceState:
    """Remove expired proposals from governance state.

    Proposals expire after ``govActionLifetime`` epochs from the epoch
    they were submitted.

    Spec ref: Conway formal spec, proposal expiry at epoch boundary.
    Haskell ref: ``processProposals`` in
        ``Cardano.Ledger.Conway.Rules.Epoch``

    Args:
        gov_state: Current governance state.
        current_epoch: Current epoch number.
        proposal_epochs: Map from action_id -> epoch when proposed.
        params: Conway protocol parameters.

    Returns:
        New GovernanceState with expired proposals removed.
    """
    new_state = deepcopy(gov_state)

    expired_ids = []
    for action_id, proposed_epoch in proposal_epochs.items():
        if current_epoch - proposed_epoch > params.gov_action_lifetime:
            expired_ids.append(action_id)

    for action_id in expired_ids:
        new_state.proposals.pop(action_id, None)
        new_state.votes.pop(action_id, None)

    return new_state


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class ConwayGovernanceError(Exception):
    """Raised when a Conway governance operation fails validation.

    Attributes:
        message: Human-readable error description.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ConwayValidationError(Exception):
    """Raised when a Conway transaction or block fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Conway validation failed: {'; '.join(errors)}")
