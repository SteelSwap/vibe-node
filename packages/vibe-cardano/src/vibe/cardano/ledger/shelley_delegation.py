"""Shelley-era delegation and staking certificate processing (DELEG, POOL, DELEGS).

Implements the certificate transition rules from the Shelley ledger formal spec:

1. **DELEG transition** -- stake credential registration/deregistration/delegation:
   - RegKey: Register a staking credential, pay key_deposit
   - DeRegKey: Deregister a staking credential, refund key_deposit
   - Delegate: Delegate stake to a registered pool

2. **POOL transition** -- stake pool management:
   - RegPool: Register a stake pool with its parameters, pay pool_deposit
   - RetirePool: Schedule a pool for retirement at a future epoch

3. **DELEGS transition** -- sequentially process all certificates in a transaction,
   threading the delegation state through each one.

Spec references:
    * Shelley ledger formal spec, Section 8 (Delegation)
    * Shelley ledger formal spec, Figure 33 (DELEG transition)
    * Shelley ledger formal spec, Figure 35 (POOL transition)
    * Shelley ledger formal spec, Figure 36 (DELEGS transition)
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Deleg.hs``
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Pool.hs``
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Delegs.hs``

Haskell references:
    * ``shelleyDelegTransition`` in ``Cardano.Ledger.Shelley.Rules.Deleg``
    * ``shelleyPoolTransition`` in ``Cardano.Ledger.Shelley.Rules.Pool``
    * ``ShelleyDelegPredFailure``: StakeKeyAlreadyRegisteredDELEG,
      StakeKeyNotRegisteredDELEG, StakeDelegationImpossibleDELEG, etc.
    * ``ShelleyPoolPredFailure``: StakePoolNotRegisteredOnKeyPOOL, etc.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Union

from pycardano.certificate import (
    PoolParams,
    PoolRegistration,
    PoolRetirement,
    StakeCredential,
    StakeDelegation,
    StakeDeregistration,
    StakeRegistration,
)
from pycardano.hash import PoolKeyHash

from vibe.cardano.ledger.shelley import ShelleyProtocolParams

# ---------------------------------------------------------------------------
# Certificate type alias
# ---------------------------------------------------------------------------

# The certificate types we handle in Shelley DELEG/POOL rules.
ShelleyCertificate = Union[
    StakeRegistration,
    StakeDeregistration,
    StakeDelegation,
    PoolRegistration,
    PoolRetirement,
]


# ---------------------------------------------------------------------------
# Delegation state
# ---------------------------------------------------------------------------


@dataclass
class DelegationState:
    """Tracks the delegation and staking state across the ledger.

    This corresponds to the DState and PState components from the Shelley
    formal spec (Figures 30-31), combined into a single dataclass for
    ergonomic use.

    Spec ref: Shelley ledger formal spec, Section 8, Figures 30-31.
    Haskell ref: ``DState`` and ``PState`` in
        ``Cardano.Ledger.Shelley.LedgerState``

    Attributes:
        rewards: Map from stake credential hash -> accumulated rewards (lovelace).
            A credential being present in this map means it is registered.
            Spec: rewards ∈ StakeCredential ↦ Coin
        delegations: Map from stake credential hash -> pool key hash.
            Spec: delegations ∈ StakeCredential ↦ KeyHash
        pools: Map from pool key hash -> PoolParams.
            Spec: stpools ∈ KeyHash ↦ PoolParams
        retiring: Map from pool key hash -> epoch number when pool retires.
            Spec: retiring ∈ KeyHash ↦ Epoch
    """

    rewards: dict[bytes, int] = field(default_factory=dict)
    """stake_credential_hash -> reward balance (lovelace)"""

    delegations: dict[bytes, bytes] = field(default_factory=dict)
    """stake_credential_hash -> pool_key_hash"""

    pools: dict[bytes, PoolParams] = field(default_factory=dict)
    """pool_key_hash -> PoolParams"""

    retiring: dict[bytes, int] = field(default_factory=dict)
    """pool_key_hash -> retirement epoch"""


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class DelegationError(Exception):
    """Raised when a certificate fails the DELEG/POOL transition rules.

    Attributes:
        message: Human-readable error description.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _credential_hash(cred: StakeCredential) -> bytes:
    """Extract the raw 28-byte hash from a StakeCredential.

    Works for both VerificationKeyHash and ScriptHash credentials.
    """
    return bytes(cred.credential)


def _pool_key_hash(pkh: PoolKeyHash) -> bytes:
    """Extract raw bytes from a PoolKeyHash."""
    return bytes(pkh)


# ---------------------------------------------------------------------------
# DELEG transition: RegKey, DeRegKey, Delegate
# ---------------------------------------------------------------------------


def _process_reg_key(
    cert: StakeRegistration,
    state: DelegationState,
    params: ShelleyProtocolParams,
) -> DelegationState:
    """Process a stake key registration certificate (RegKey).

    Spec (DELEG rule, RegKey case):
        - Precondition: hk ∉ dom rewards  (credential must NOT already be registered)
        - Effect: rewards' = rewards ∪ {hk ↦ 0}
        - The key_deposit is collected from the transaction's deposit accounting
          (handled in the UTXO value preservation rule, not here)

    Haskell ref: ``shelleyDelegTransition`` RegKey case in
        ``Cardano.Ledger.Shelley.Rules.Deleg``

    Raises:
        DelegationError: StakeKeyAlreadyRegisteredDELEG
    """
    cred_hash = _credential_hash(cert.stake_credential)

    if cred_hash in state.rewards:
        raise DelegationError(
            f"StakeKeyAlreadyRegisteredDELEG: credential {cred_hash.hex()[:16]}... "
            f"is already registered"
        )

    new_state = deepcopy(state)
    new_state.rewards[cred_hash] = 0
    return new_state


def _process_dereg_key(
    cert: StakeDeregistration,
    state: DelegationState,
    params: ShelleyProtocolParams,
) -> DelegationState:
    """Process a stake key deregistration certificate (DeRegKey).

    Spec (DELEG rule, DeRegKey case):
        - Precondition: hk ∈ dom rewards  (credential must be registered)
        - Precondition: rewards hk = 0  (rewards must be withdrawn first)
        - Effect: rewards' = {hk} ⊳ rewards  (remove from rewards map)
        - Effect: delegations' = {hk} ⊳ delegations  (remove any delegation)
        - The key_deposit is refunded via the UTXO value preservation rule

    Haskell ref: ``shelleyDelegTransition`` DeRegKey case in
        ``Cardano.Ledger.Shelley.Rules.Deleg``

    Raises:
        DelegationError: StakeKeyNotRegisteredDELEG, StakeKeyNonZeroAccountBalanceDELEG
    """
    cred_hash = _credential_hash(cert.stake_credential)

    if cred_hash not in state.rewards:
        raise DelegationError(
            f"StakeKeyNotRegisteredDELEG: credential {cred_hash.hex()[:16]}... "
            f"is not registered"
        )

    if state.rewards[cred_hash] != 0:
        raise DelegationError(
            f"StakeKeyNonZeroAccountBalanceDELEG: credential {cred_hash.hex()[:16]}... "
            f"has non-zero reward balance of {state.rewards[cred_hash]} lovelace"
        )

    new_state = deepcopy(state)
    del new_state.rewards[cred_hash]
    new_state.delegations.pop(cred_hash, None)
    return new_state


def _process_delegate(
    cert: StakeDelegation,
    state: DelegationState,
) -> DelegationState:
    """Process a delegation certificate (Delegate).

    Spec (DELEG rule, Delegate case):
        - Precondition: hk ∈ dom rewards  (delegator credential must be registered)
        - Precondition: dpool ∈ dom stpools  (target pool must be registered)
        - Effect: delegations' = delegations ∪ {hk ↦ dpool}

    Haskell ref: ``shelleyDelegTransition`` Delegate case in
        ``Cardano.Ledger.Shelley.Rules.Deleg``

    Raises:
        DelegationError: StakeKeyNotRegisteredDELEG, StakeDelegationImpossibleDELEG
    """
    cred_hash = _credential_hash(cert.stake_credential)
    pool_hash = _pool_key_hash(cert.pool_keyhash)

    if cred_hash not in state.rewards:
        raise DelegationError(
            f"StakeKeyNotRegisteredDELEG: credential {cred_hash.hex()[:16]}... "
            f"is not registered — cannot delegate"
        )

    if pool_hash not in state.pools:
        raise DelegationError(
            f"StakeDelegationImpossibleDELEG: pool {pool_hash.hex()[:16]}... "
            f"is not registered"
        )

    new_state = deepcopy(state)
    new_state.delegations[cred_hash] = pool_hash
    return new_state


# ---------------------------------------------------------------------------
# POOL transition: RegPool, RetirePool
# ---------------------------------------------------------------------------


def _process_reg_pool(
    cert: PoolRegistration,
    state: DelegationState,
    params: ShelleyProtocolParams,
) -> DelegationState:
    """Process a pool registration certificate (RegPool).

    Spec (POOL rule, RegPool case):
        - If pool not in stpools: register new pool, pool_deposit collected
        - If pool already in stpools: update pool parameters (re-registration)
        - Effect: stpools' = stpools ∪ {hk ↦ poolParams}
        - Effect: retiring' = {hk} ⊳ retiring  (cancel any pending retirement)

    Haskell ref: ``shelleyPoolTransition`` RegPool case in
        ``Cardano.Ledger.Shelley.Rules.Pool``

    Note: Re-registration (updating pool params) does NOT charge another
    pool_deposit. The deposit is only collected on first registration.
    """
    pool_hash = _pool_key_hash(cert.pool_params.operator)

    # Check minPoolCost constraint
    # Spec (POOL rule): cost pp ≥ minPoolCost pp
    # Haskell: StakePoolCostTooLowPOOL
    if cert.pool_params.cost < params.min_pool_cost:
        raise DelegationError(
            f"StakePoolCostTooLowPOOL: pool cost {cert.pool_params.cost} "
            f"is below minimum {params.min_pool_cost}"
        )

    new_state = deepcopy(state)
    new_state.pools[pool_hash] = cert.pool_params
    # Cancel any pending retirement if re-registering
    new_state.retiring.pop(pool_hash, None)
    return new_state


def _process_retire_pool(
    cert: PoolRetirement,
    state: DelegationState,
    current_epoch: int,
) -> DelegationState:
    """Process a pool retirement certificate (RetirePool).

    Spec (POOL rule, RetirePool case):
        - Precondition: hk ∈ dom stpools  (pool must be registered)
        - Precondition: current_epoch < retirement_epoch
          (cannot retire in the past or current epoch)
        - Effect: retiring' = retiring ∪ {hk ↦ e}

    Haskell ref: ``shelleyPoolTransition`` RetirePool case in
        ``Cardano.Ledger.Shelley.Rules.Pool``

    Note: The actual pool removal and deposit refund happens at the epoch
    boundary via the POOLREAP rule, not here. We just schedule it.

    Raises:
        DelegationError: StakePoolNotRegisteredOnKeyPOOL,
            StakePoolRetirementWrongEpochPOOL
    """
    pool_hash = _pool_key_hash(cert.pool_keyhash)

    if pool_hash not in state.pools:
        raise DelegationError(
            f"StakePoolNotRegisteredOnKeyPOOL: pool {pool_hash.hex()[:16]}... "
            f"is not registered — cannot retire"
        )

    if cert.epoch <= current_epoch:
        raise DelegationError(
            f"StakePoolRetirementWrongEpochPOOL: retirement epoch {cert.epoch} "
            f"must be after current epoch {current_epoch}"
        )

    new_state = deepcopy(state)
    new_state.retiring[pool_hash] = cert.epoch
    return new_state


# ---------------------------------------------------------------------------
# Certificate processing: single and batch
# ---------------------------------------------------------------------------


def process_certificate(
    cert: ShelleyCertificate,
    state: DelegationState,
    params: ShelleyProtocolParams,
    current_epoch: int,
) -> DelegationState:
    """Process a single Shelley delegation/pool certificate.

    Routes to the appropriate DELEG or POOL transition rule based on
    certificate type.

    Spec ref: Shelley ledger formal spec, Section 8 (DELEGS rule).
    Haskell ref: ``shelleyDelegsTransition`` in
        ``Cardano.Ledger.Shelley.Rules.Delegs``

    Args:
        cert: The certificate to process.
        state: Current delegation state.
        params: Protocol parameters (for deposit amounts).
        current_epoch: Current epoch number.

    Returns:
        New DelegationState with the certificate applied.

    Raises:
        DelegationError: If the certificate violates any transition rule.
        TypeError: If the certificate type is not recognized.
    """
    if isinstance(cert, StakeRegistration):
        return _process_reg_key(cert, state, params)
    elif isinstance(cert, StakeDeregistration):
        return _process_dereg_key(cert, state, params)
    elif isinstance(cert, StakeDelegation):
        return _process_delegate(cert, state)
    elif isinstance(cert, PoolRegistration):
        return _process_reg_pool(cert, state, params)
    elif isinstance(cert, PoolRetirement):
        return _process_retire_pool(cert, state, current_epoch)
    else:
        raise TypeError(f"Unrecognized certificate type: {type(cert).__name__}")


def process_certificates(
    certs: list[ShelleyCertificate],
    state: DelegationState,
    params: ShelleyProtocolParams,
    current_epoch: int,
) -> DelegationState:
    """Process all certificates in a transaction sequentially.

    This implements the DELEGS transition rule, which folds over the
    certificate list, threading the delegation state through each one.

    Spec ref: Shelley ledger formal spec, Figure 36 (DELEGS rule).
    Haskell ref: ``shelleyDelegsTransition`` folds ``shelleyDelegTransition``
        and ``shelleyPoolTransition`` over the certificate sequence.

    Args:
        certs: List of certificates from a transaction body.
        state: Current delegation state.
        params: Protocol parameters.
        current_epoch: Current epoch number.

    Returns:
        New DelegationState after applying all certificates.

    Raises:
        DelegationError: If any certificate violates a transition rule.
    """
    current_state = state
    for cert in certs:
        current_state = process_certificate(cert, current_state, params, current_epoch)
    return current_state


# ---------------------------------------------------------------------------
# Deposit accounting helpers
# ---------------------------------------------------------------------------


def compute_certificate_deposits(
    certs: list[ShelleyCertificate],
    params: ShelleyProtocolParams,
) -> int:
    """Compute the net deposit change from a list of certificates.

    Positive means deposits collected (consumed from the transaction),
    negative means deposits refunded (produced to the transaction).

    This is used by the UTXO value preservation rule to account for
    deposits in the consumed/produced equation:
        consumed = inputs + withdrawals + refunds
        produced = outputs + fee + deposits

    Spec ref: Shelley ledger formal spec, Section 9, consumed/produced.
    Haskell ref: ``totalCertsDeposits`` and ``totalCertsRefunds`` in
        ``Cardano.Ledger.Shelley.Rules.Utxo``

    Args:
        certs: List of certificates from a transaction body.
        params: Protocol parameters (key_deposit, pool_deposit).

    Returns:
        Net deposit amount in lovelace. Positive = deposits collected,
        negative = deposits refunded.
    """
    deposits = 0
    refunds = 0

    for cert in certs:
        if isinstance(cert, StakeRegistration):
            deposits += params.key_deposit
        elif isinstance(cert, StakeDeregistration):
            refunds += params.key_deposit
        elif isinstance(cert, PoolRegistration):
            # Note: re-registration does NOT charge another deposit.
            # The caller is responsible for checking if the pool is
            # already registered if they want to distinguish.
            # For the UTXO rule, the deposit is always counted.
            deposits += params.pool_deposit

    return deposits - refunds
