"""Conway-era types: governance actions, voting, DRep delegation.

Conway introduces on-chain governance to Cardano (CIP-1694), adding:
    - Governance actions: proposals for protocol changes, treasury withdrawals, etc.
    - Voting: DReps, stake pools, and constitutional committee vote on proposals
    - DRep delegation: stake holders delegate voting power to DReps
    - Constitutional committee: a body that approves governance actions
    - Guardrails: ratification thresholds per action type

Spec references:
    * Conway ledger formal spec, Section 5 (Governance)
    * Conway ledger formal spec, Section 6 (Ratification)
    * CIP-1694 (on-chain governance)
    * ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/Governance/``
    * ``cardano-ledger/eras/conway/impl/src/Cardano/Ledger/Conway/PParams.hs``

Haskell references:
    * ``GovAction`` in ``Cardano.Ledger.Conway.Governance.Actions``
    * ``VotingProcedures`` in ``Cardano.Ledger.Conway.Governance.Procedures``
    * ``DRep`` in ``Cardano.Ledger.Conway.TxCert``
    * ``ConwayEraPParams`` in ``Cardano.Ledger.Conway.PParams``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from vibe.cardano.ledger.babbage_types import BabbageProtocolParams

# ---------------------------------------------------------------------------
# Governance action types
# ---------------------------------------------------------------------------


class GovActionType(IntEnum):
    """Types of Conway governance actions.

    Spec ref: Conway formal spec, ``GovAction`` type.
    Haskell ref: ``GovAction`` in ``Cardano.Ledger.Conway.Governance.Actions``

    Each action type has different ratification thresholds and effects.
    """

    PARAMETER_CHANGE = 0
    """Propose a change to protocol parameters.

    Requires: CC + DRep approval.
    """

    HARD_FORK_INITIATION = 1
    """Initiate a hard fork to a new protocol version.

    Requires: CC + SPO + DRep approval.
    """

    TREASURY_WITHDRAWALS = 2
    """Withdraw funds from the treasury.

    Requires: CC + DRep approval.
    """

    NO_CONFIDENCE = 3
    """Express no confidence in the current constitutional committee.

    Requires: SPO + DRep approval.
    """

    UPDATE_COMMITTEE = 4
    """Add or remove members from the constitutional committee.

    Requires: SPO + DRep approval (or CC if normal state).
    """

    NEW_CONSTITUTION = 5
    """Propose a new constitution (on-chain hash).

    Requires: CC + DRep approval.
    """

    INFO_ACTION = 6
    """Informational action — no on-chain effect, just records intent.

    Ratified automatically (no thresholds).
    """


# ---------------------------------------------------------------------------
# Anchor — metadata reference
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Anchor:
    """An anchor linking to off-chain metadata.

    Used in governance proposals, DRep registrations, etc. to point to
    a URL containing detailed information about the action.

    Spec ref: Conway formal spec, ``Anchor = (URL, Hash)``
    Haskell ref: ``Anchor`` in ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    url: str
    """URL pointing to the metadata document."""

    data_hash: bytes
    """Blake2b-256 hash of the metadata document content (32 bytes)."""


# ---------------------------------------------------------------------------
# Governance action ID
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovActionId:
    """Unique identifier for a governance action (proposal).

    A governance action is identified by the transaction that proposed it
    and the index within that transaction's proposal list.

    Spec ref: Conway formal spec, ``GovActionId = (TxId, GovActionIx)``
    Haskell ref: ``GovActionId`` in ``Cardano.Ledger.Conway.Governance.Actions``
    """

    tx_id: bytes
    """Transaction ID where this governance action was proposed (32 bytes)."""

    gov_action_index: int
    """Index within the transaction's proposal procedures list."""


# ---------------------------------------------------------------------------
# Governance action
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovAction:
    """A governance action proposed on-chain.

    Spec ref: Conway formal spec, ``GovAction``.
    Haskell ref: ``GovAction`` in ``Cardano.Ledger.Conway.Governance.Actions``
    """

    action_type: GovActionType
    """What kind of governance action this is."""

    prev_action_id: GovActionId | None = None
    """Previous action ID in the chain (for ordered actions).
    Some action types (ParameterChange, HardFork, UpdateCommittee,
    NewConstitution) require chaining to the previous enacted action
    of the same type. None for the first action or for unchained types.

    Spec ref: Conway formal spec, ``prevGovActionId``
    Haskell ref: ``GovAction`` constructors with ``StrictMaybe (GovPurposeId)``
    """

    # Action-specific payload — varies by type
    # ParameterChange: proposed parameter updates
    # HardForkInitiation: target protocol version
    # TreasuryWithdrawals: map of reward_addr -> amount
    # UpdateCommittee: members to add/remove, quorum threshold
    # NewConstitution: constitution hash + optional guardrails script
    # InfoAction: no payload
    payload: Any = None
    """Action-type-specific data. Type depends on action_type."""


# ---------------------------------------------------------------------------
# Proposal procedure
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposalProcedure:
    """A complete governance proposal.

    Spec ref: Conway formal spec, ``ProposalProcedure``.
    Haskell ref: ``ProposalProcedure`` in
        ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    deposit: int
    """Deposit in lovelace required to submit a proposal.
    Must equal the ``govActionDeposit`` protocol parameter.
    """

    return_addr: bytes
    """Reward address where the deposit is returned after the
    proposal is enacted or expired (29-byte reward address).
    """

    gov_action: GovAction
    """The governance action being proposed."""

    anchor: Anchor
    """Metadata anchor with detailed proposal information."""


# ---------------------------------------------------------------------------
# Vote
# ---------------------------------------------------------------------------


class Vote(IntEnum):
    """Vote on a governance action.

    Spec ref: Conway formal spec, ``Vote = Yes | No | Abstain``
    Haskell ref: ``Vote`` in ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    NO = 0
    YES = 1
    ABSTAIN = 2


# ---------------------------------------------------------------------------
# Voter types
# ---------------------------------------------------------------------------


class VoterRole(IntEnum):
    """Role of a voter in Conway governance.

    Spec ref: Conway formal spec, ``Voter`` type.
    Haskell ref: ``Voter`` in ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    CONSTITUTIONAL_COMMITTEE = 0
    """Constitutional committee member (hot key credential)."""

    DREP = 1
    """Delegated representative (DRep credential)."""

    STAKE_POOL = 2
    """Stake pool operator (pool key hash)."""


@dataclass(frozen=True, slots=True)
class Voter:
    """A voter in the Conway governance system.

    Spec ref: Conway formal spec, ``Voter = CC hot_cred | DRep cred | SPO pool_id``
    Haskell ref: ``Voter`` in ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    role: VoterRole
    """What role this voter has."""

    credential: bytes
    """28-byte credential hash:
    - CC: hot key hash
    - DRep: credential hash (key or script)
    - SPO: pool key hash
    """


# ---------------------------------------------------------------------------
# Voting procedures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VotingProcedure:
    """A single voting procedure: vote + optional anchor.

    Spec ref: Conway formal spec, ``VotingProcedure = (Vote, Maybe Anchor)``
    Haskell ref: ``VotingProcedure`` in
        ``Cardano.Ledger.Conway.Governance.Procedures``
    """

    vote: Vote
    """The vote cast."""

    anchor: Anchor | None = None
    """Optional anchor with rationale for the vote."""


# Map from Voter -> (GovActionId -> VotingProcedure)
VotingProcedures = dict[Voter, dict[GovActionId, VotingProcedure]]
"""All voting procedures in a transaction.

Spec ref: Conway formal spec, ``VotingProcedures``
Haskell ref: ``VotingProcedures`` in
    ``Cardano.Ledger.Conway.Governance.Procedures``
"""


# ---------------------------------------------------------------------------
# DRep types
# ---------------------------------------------------------------------------


class DRepType(IntEnum):
    """Types of DRep delegation targets.

    Spec ref: Conway formal spec, ``DRep`` type.
    Haskell ref: ``DRep`` in ``Cardano.Ledger.Conway.TxCert``
    """

    KEY_HASH = 0
    """Delegate to a DRep identified by a verification key hash."""

    SCRIPT_HASH = 1
    """Delegate to a DRep identified by a script hash."""

    ALWAYS_ABSTAIN = 2
    """Always abstain — equivalent to not voting."""

    ALWAYS_NO_CONFIDENCE = 3
    """Always vote no confidence — automatically votes NoConfidence on everything."""


@dataclass(frozen=True, slots=True)
class DRep:
    """A DRep delegation target.

    Spec ref: Conway formal spec, ``DRep``.
    Haskell ref: ``DRep`` in ``Cardano.Ledger.Conway.TxCert``
    """

    drep_type: DRepType
    """What kind of DRep this is."""

    credential: bytes | None = None
    """28-byte credential hash for KEY_HASH or SCRIPT_HASH.
    None for ALWAYS_ABSTAIN and ALWAYS_NO_CONFIDENCE.
    """

    def __post_init__(self) -> None:
        if self.drep_type in (DRepType.KEY_HASH, DRepType.SCRIPT_HASH):
            if self.credential is None or len(self.credential) != 28:
                raise ValueError(
                    f"DRep with type {self.drep_type.name} requires a "
                    f"28-byte credential, got {self.credential!r}"
                )
        elif self.credential is not None:
            raise ValueError(
                f"DRep with type {self.drep_type.name} should not have "
                f"a credential, got {self.credential!r}"
            )


# ---------------------------------------------------------------------------
# DRep certificates
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DRepRegistration:
    """DRep registration certificate.

    Spec ref: Conway formal spec, ``RegDRep``.
    Haskell ref: ``ConwayRegDRep`` in ``Cardano.Ledger.Conway.TxCert``
    """

    credential: bytes
    """28-byte DRep credential hash."""

    deposit: int
    """Deposit in lovelace (must equal drepDeposit param)."""

    anchor: Anchor | None = None
    """Optional metadata anchor."""


@dataclass(frozen=True, slots=True)
class DRepDeregistration:
    """DRep deregistration certificate.

    Spec ref: Conway formal spec, ``UnRegDRep``.
    Haskell ref: ``ConwayUnRegDRep`` in ``Cardano.Ledger.Conway.TxCert``
    """

    credential: bytes
    """28-byte DRep credential hash."""

    deposit_refund: int
    """Deposit to refund in lovelace."""


@dataclass(frozen=True, slots=True)
class DRepUpdate:
    """DRep update certificate (update metadata).

    Spec ref: Conway formal spec, ``UpdateDRep``.
    Haskell ref: ``ConwayUpdateDRep`` in ``Cardano.Ledger.Conway.TxCert``
    """

    credential: bytes
    """28-byte DRep credential hash."""

    anchor: Anchor | None = None
    """New metadata anchor."""


@dataclass(frozen=True, slots=True)
class DelegVote:
    """Delegate voting power to a DRep.

    Spec ref: Conway formal spec, ``DelegVote``.
    Haskell ref: ``ConwayDelegVote`` in ``Cardano.Ledger.Conway.TxCert``
    """

    credential: bytes
    """28-byte stake credential hash of the delegator."""

    drep: DRep
    """DRep to delegate to."""


# Union of all Conway-specific certificates
ConwayCertificate = DRepRegistration | DRepDeregistration | DRepUpdate | DelegVote


# ---------------------------------------------------------------------------
# Governance state
# ---------------------------------------------------------------------------


@dataclass
class GovernanceState:
    """Conway governance state tracking proposals, votes, and DReps.

    Spec ref: Conway formal spec, ``GovState``.
    Haskell ref: ``ConwayGovState`` in
        ``Cardano.Ledger.Conway.Governance``

    Attributes:
        proposals: Active proposals keyed by GovActionId.
        votes: Votes cast on proposals.
        dreps: Registered DReps with their deposits.
        drep_delegations: Stake credential -> DRep delegation.
        constitution_hash: Hash of the current constitution.
        committee: Current constitutional committee members.
    """

    proposals: dict[GovActionId, ProposalProcedure] = field(default_factory=dict)
    """Active governance proposals."""

    votes: dict[GovActionId, dict[Voter, VotingProcedure]] = field(default_factory=dict)
    """Votes cast on proposals: action_id -> voter -> procedure."""

    dreps: dict[bytes, int] = field(default_factory=dict)
    """Registered DReps: credential_hash -> deposit."""

    drep_delegations: dict[bytes, DRep] = field(default_factory=dict)
    """Voting delegations: stake_credential_hash -> DRep."""

    constitution_hash: bytes | None = None
    """Blake2b-256 hash of the current constitution document."""

    committee: dict[bytes, int] = field(default_factory=dict)
    """Constitutional committee members: cold_key_hash -> expiry_epoch."""

    committee_threshold: tuple[int, int] = (0, 1)
    """Committee approval threshold as (numerator, denominator).
    E.g., (2, 3) means 2/3 of committee must approve.
    """

    drep_stake: dict[bytes, int] = field(default_factory=dict)
    """Delegated stake per DRep credential: credential_hash -> lovelace.
    Used for stake-weighted DRep voting in ratification.

    Spec ref: Conway formal spec, Section 6 (stake-weighted DRep votes).
    Haskell ref: ``ratifyAction`` DRep stake calculation in
        ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    drep_activity_epoch: dict[bytes, int] = field(default_factory=dict)
    """Last epoch each DRep was active (voted or registered): credential_hash -> epoch.
    DReps inactive for more than drep_activity epochs are excluded from thresholds.

    Spec ref: Conway formal spec, ``drepActivity`` parameter.
    Haskell ref: ``isDRepExpiry`` in ``Cardano.Ledger.Conway.Rules.Ratify``
    """

    registered_pools: set[bytes] = field(default_factory=set)
    """Set of registered pool key hashes (for SPO vote validation).

    Haskell ref: pool registration in ``Cardano.Ledger.Shelley.LedgerState``
    """

    pool_stake: dict[bytes, int] = field(default_factory=dict)
    """Stake per pool: pool_key_hash -> lovelace.
    Used for stake-weighted SPO voting in ratification.

    Spec ref: Conway formal spec, Section 6 (stake-weighted SPO votes).
    """

    current_protocol_version: tuple[int, int] = (9, 0)
    """Current protocol version as (major, minor).
    Used for HardForkInitiation validation.
    """

    reward_account_delegations: dict[bytes, DRep] = field(default_factory=dict)
    """Pool reward account credential -> DRep delegation.

    Maps each pool's reward account credential to its DRep delegation target.
    Used for computing default SPO votes when a pool hasn't voted explicitly.

    Spec ref: Conway formal spec, Section 6 (default SPO vote via reward addr delegation).
    Haskell ref: ``spoAcceptedRatio`` in ``Cardano.Ledger.Conway.Rules.Ratify``
    """


# ---------------------------------------------------------------------------
# Ratification thresholds
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RatificationThresholds:
    """Thresholds required for ratifying a governance action.

    Each governance action type may require approval from up to three
    bodies: Constitutional Committee (CC), DReps, and Stake Pool Operators (SPOs).
    A threshold of None means that body doesn't vote on this action type.

    Spec ref: Conway formal spec, Section 6 (Ratification thresholds).
    Haskell ref: ``DRepVotingThresholds``, ``PoolVotingThresholds`` in
        ``Cardano.Ledger.Conway.PParams``
    """

    cc_threshold: tuple[int, int] | None = None
    """CC approval threshold (numerator, denominator). None = CC doesn't vote."""

    drep_threshold: tuple[int, int] | None = None
    """DRep approval threshold (numerator, denominator). None = DReps don't vote."""

    spo_threshold: tuple[int, int] | None = None
    """SPO approval threshold (numerator, denominator). None = SPOs don't vote."""


# Default ratification thresholds per action type.
# These are simplified versions — the real values come from protocol parameters.
# Spec ref: Conway formal spec, Figure 3 (Ratification requirements).
DEFAULT_RATIFICATION_THRESHOLDS: dict[GovActionType, RatificationThresholds] = {
    GovActionType.PARAMETER_CHANGE: RatificationThresholds(
        cc_threshold=(2, 3),
        drep_threshold=(2, 3),
        spo_threshold=None,
    ),
    GovActionType.HARD_FORK_INITIATION: RatificationThresholds(
        cc_threshold=(2, 3),
        drep_threshold=(2, 3),
        spo_threshold=(1, 2),
    ),
    GovActionType.TREASURY_WITHDRAWALS: RatificationThresholds(
        cc_threshold=(2, 3),
        drep_threshold=(2, 3),
        spo_threshold=None,
    ),
    GovActionType.NO_CONFIDENCE: RatificationThresholds(
        cc_threshold=None,
        drep_threshold=(2, 3),
        spo_threshold=(1, 2),
    ),
    GovActionType.UPDATE_COMMITTEE: RatificationThresholds(
        cc_threshold=None,
        drep_threshold=(2, 3),
        spo_threshold=(1, 2),
    ),
    GovActionType.NEW_CONSTITUTION: RatificationThresholds(
        cc_threshold=(2, 3),
        drep_threshold=(2, 3),
        spo_threshold=None,
    ),
    GovActionType.INFO_ACTION: RatificationThresholds(
        cc_threshold=None,
        drep_threshold=None,
        spo_threshold=None,
    ),
}


# ---------------------------------------------------------------------------
# Conway protocol parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConwayProtocolParams(BabbageProtocolParams):
    """Conway-era protocol parameters extending Babbage.

    Spec ref: Conway ledger formal spec, protocol parameters.
    Haskell ref: ``ConwayEraPParams`` in ``Cardano.Ledger.Conway.PParams``

    Adds governance-related parameters.
    """

    drep_deposit: int = 500_000_000
    """Deposit required to register as a DRep (lovelace).
    Conway mainnet: 500 ADA.

    Spec ref: ``drepDeposit`` in Conway formal spec.
    Haskell ref: ``cppDRepDeposit`` in ``ConwayEraPParams``
    """

    drep_activity: int = 20
    """Number of epochs a DRep can be inactive before being considered
    dormant. Conway mainnet: 20 epochs.

    Spec ref: ``drepActivity`` in Conway formal spec.
    Haskell ref: ``cppDRepActivity`` in ``ConwayEraPParams``
    """

    gov_action_lifetime: int = 6
    """Number of epochs a governance action proposal lives before
    expiring if not enacted. Conway mainnet: 6 epochs.

    Spec ref: ``govActionLifetime`` in Conway formal spec.
    Haskell ref: ``cppGovActionLifetime`` in ``ConwayEraPParams``
    """

    gov_action_deposit: int = 100_000_000_000
    """Deposit required to submit a governance action (lovelace).
    Conway mainnet: 100,000 ADA.

    Spec ref: ``govActionDeposit`` in Conway formal spec.
    Haskell ref: ``cppGovActionDeposit`` in ``ConwayEraPParams``
    """

    committee_min_size: int = 7
    """Minimum number of constitutional committee members.
    Conway mainnet: 7.

    Spec ref: ``committeeMinSize`` in Conway formal spec.
    Haskell ref: ``cppCommitteeMinSize`` in ``ConwayEraPParams``
    """

    committee_max_term_length: int = 146
    """Maximum term length for CC members in epochs.
    Conway mainnet: 146 epochs (~2 years).

    Spec ref: ``committeeMaxTermLength`` in Conway formal spec.
    Haskell ref: ``cppCommitteeMaxTermLength`` in ``ConwayEraPParams``
    """


# Conway mainnet defaults (for testing)
CONWAY_MAINNET_PARAMS = ConwayProtocolParams()
