"""Tests for Shelley-era delegation and staking certificate processing.

Tests cover the DELEG, POOL, and DELEGS transition rules from the Shelley
formal spec:
    - Stake key registration (RegKey) and deposit accounting
    - Stake key deregistration (DeRegKey) with deposit refund
    - Register/deregister roundtrip
    - Delegation to a registered pool
    - Pool registration with full PoolParams
    - Pool retirement scheduling
    - Deposit accounting (key_deposit, pool_deposit)
    - Error: delegate to unregistered pool
    - Error: deregister with non-zero rewards
    - Error: double registration
    - Error: deregister unregistered credential
    - Error: retire unregistered pool
    - Error: retire in past epoch

Spec references:
    - Shelley ledger formal spec, Section 8 (Delegation)
    - Shelley ledger formal spec, Figures 33, 35, 36
    - ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Deleg.hs``
    - ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Pool.hs``
"""

from __future__ import annotations

import os
from fractions import Fraction

import pytest
from pycardano.certificate import (
    PoolParams,
    PoolRegistration,
    PoolRetirement,
    StakeCredential,
    StakeDelegation,
    StakeDeregistration,
    StakeRegistration,
)
from pycardano.hash import PoolKeyHash, ScriptHash, VerificationKeyHash

from vibe.cardano.ledger.shelley import ShelleyProtocolParams
from vibe.cardano.ledger.shelley_delegation import (
    DelegationError,
    DelegationState,
    compute_certificate_deposits,
    process_certificate,
    process_certificates,
)

# ---------------------------------------------------------------------------
# Fixtures: deterministic test data
# ---------------------------------------------------------------------------


def _fake_hash(prefix: int, size: int = 28) -> bytes:
    """Create a deterministic fake hash for testing."""
    return bytes([prefix] * size)


def _stake_credential(prefix: int = 0xAA) -> StakeCredential:
    """Create a test StakeCredential with a fake verification key hash."""
    return StakeCredential(VerificationKeyHash(_fake_hash(prefix)))


def _pool_key_hash(prefix: int = 0xBB) -> PoolKeyHash:
    """Create a test PoolKeyHash."""
    return PoolKeyHash(_fake_hash(prefix))


def _pool_params(operator_prefix: int = 0xBB) -> PoolParams:
    """Create test PoolParams with minimal valid fields."""
    return PoolParams(
        operator=PoolKeyHash(_fake_hash(operator_prefix)),
        vrf_keyhash=_fake_hash(0xCC, size=32),
        pledge=100_000_000,  # 100 ADA
        cost=340_000_000,  # 340 ADA min cost
        margin=Fraction(1, 100),  # 1% margin
        reward_account=_fake_hash(0xDD, size=29),  # reward address bytes
        pool_owners=[VerificationKeyHash(_fake_hash(operator_prefix))],
        relays=None,
        pool_metadata=None,
    )


@pytest.fixture
def params() -> ShelleyProtocolParams:
    """Default Shelley protocol parameters."""
    return ShelleyProtocolParams()


@pytest.fixture
def empty_state() -> DelegationState:
    """Empty delegation state (no registrations)."""
    return DelegationState()


@pytest.fixture
def state_with_registered_key(empty_state: DelegationState) -> DelegationState:
    """State with one registered stake credential (0xAA)."""
    cred_hash = _fake_hash(0xAA)
    return DelegationState(
        rewards={cred_hash: 0},
        delegations={},
        pools={},
        retiring={},
    )


@pytest.fixture
def state_with_pool(state_with_registered_key: DelegationState) -> DelegationState:
    """State with a registered stake key AND a registered pool."""
    pool_hash = _fake_hash(0xBB)
    pool = _pool_params(0xBB)
    return DelegationState(
        rewards=dict(state_with_registered_key.rewards),
        delegations={},
        pools={pool_hash: pool},
        retiring={},
    )


# ===========================================================================
# Stake registration (RegKey)
# ===========================================================================


class TestStakeRegistration:
    """Tests for the RegKey (stake registration) certificate."""

    def test_register_new_credential(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Registering a new credential adds it to the rewards map with balance 0."""
        cert = StakeRegistration(_stake_credential(0xAA))
        new_state = process_certificate(cert, empty_state, params, current_epoch=200)

        cred_hash = _fake_hash(0xAA)
        assert cred_hash in new_state.rewards
        assert new_state.rewards[cred_hash] == 0

    def test_register_duplicate_raises(
        self,
        state_with_registered_key: DelegationState,
        params: ShelleyProtocolParams,
    ):
        """Registering an already-registered credential fails."""
        cert = StakeRegistration(_stake_credential(0xAA))
        with pytest.raises(DelegationError, match="StakeKeyAlreadyRegisteredDELEG"):
            process_certificate(cert, state_with_registered_key, params, current_epoch=200)

    def test_register_does_not_mutate_original(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Processing a certificate must not mutate the original state."""
        cert = StakeRegistration(_stake_credential(0xAA))
        _ = process_certificate(cert, empty_state, params, current_epoch=200)
        assert len(empty_state.rewards) == 0


# ===========================================================================
# Stake deregistration (DeRegKey)
# ===========================================================================


class TestStakeDeregistration:
    """Tests for the DeRegKey (stake deregistration) certificate."""

    def test_deregister_credential(
        self,
        state_with_registered_key: DelegationState,
        params: ShelleyProtocolParams,
    ):
        """Deregistering a registered credential with zero rewards succeeds."""
        cert = StakeDeregistration(_stake_credential(0xAA))
        new_state = process_certificate(
            cert, state_with_registered_key, params, current_epoch=200
        )

        cred_hash = _fake_hash(0xAA)
        assert cred_hash not in new_state.rewards

    def test_deregister_unregistered_raises(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Deregistering a credential that was never registered fails."""
        cert = StakeDeregistration(_stake_credential(0xFF))
        with pytest.raises(DelegationError, match="StakeKeyNotRegisteredDELEG"):
            process_certificate(cert, empty_state, params, current_epoch=200)

    def test_deregister_nonzero_rewards_raises(
        self, params: ShelleyProtocolParams
    ):
        """Deregistering a credential with non-zero rewards fails.

        Spec: rewards must be withdrawn before deregistration.
        Haskell: StakeKeyNonZeroAccountBalanceDELEG
        """
        cred_hash = _fake_hash(0xAA)
        state = DelegationState(rewards={cred_hash: 5_000_000})

        cert = StakeDeregistration(_stake_credential(0xAA))
        with pytest.raises(
            DelegationError, match="StakeKeyNonZeroAccountBalanceDELEG"
        ):
            process_certificate(cert, state, params, current_epoch=200)

    def test_deregister_removes_delegation(self, params: ShelleyProtocolParams):
        """Deregistering also removes any existing delegation for that credential."""
        cred_hash = _fake_hash(0xAA)
        pool_hash = _fake_hash(0xBB)
        state = DelegationState(
            rewards={cred_hash: 0},
            delegations={cred_hash: pool_hash},
            pools={pool_hash: _pool_params(0xBB)},
        )

        cert = StakeDeregistration(_stake_credential(0xAA))
        new_state = process_certificate(cert, state, params, current_epoch=200)

        assert cred_hash not in new_state.delegations
        assert cred_hash not in new_state.rewards


# ===========================================================================
# Register/deregister roundtrip
# ===========================================================================


class TestRegisterDeregisterRoundtrip:
    """Register then deregister should return to the original state."""

    def test_roundtrip_empty_state(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Register then deregister returns to empty state."""
        reg = StakeRegistration(_stake_credential(0xAA))
        dereg = StakeDeregistration(_stake_credential(0xAA))

        after_reg = process_certificate(reg, empty_state, params, current_epoch=200)
        assert _fake_hash(0xAA) in after_reg.rewards

        after_dereg = process_certificate(dereg, after_reg, params, current_epoch=200)
        assert _fake_hash(0xAA) not in after_dereg.rewards
        assert len(after_dereg.rewards) == 0
        assert len(after_dereg.delegations) == 0


# ===========================================================================
# Delegation (Delegate)
# ===========================================================================


class TestDelegation:
    """Tests for the Delegate certificate."""

    def test_delegate_to_registered_pool(
        self,
        state_with_pool: DelegationState,
        params: ShelleyProtocolParams,
    ):
        """Delegating a registered credential to a registered pool succeeds."""
        cert = StakeDelegation(
            _stake_credential(0xAA),
            _pool_key_hash(0xBB),
        )
        new_state = process_certificate(cert, state_with_pool, params, current_epoch=200)

        cred_hash = _fake_hash(0xAA)
        pool_hash = _fake_hash(0xBB)
        assert new_state.delegations[cred_hash] == pool_hash

    def test_delegate_to_unregistered_pool_raises(
        self,
        state_with_registered_key: DelegationState,
        params: ShelleyProtocolParams,
    ):
        """Delegating to a pool that is not registered fails.

        Spec: dpool ∈ dom stpools
        Haskell: StakeDelegationImpossibleDELEG
        """
        cert = StakeDelegation(
            _stake_credential(0xAA),
            _pool_key_hash(0xFF),  # unregistered pool
        )
        with pytest.raises(
            DelegationError, match="StakeDelegationImpossibleDELEG"
        ):
            process_certificate(
                cert, state_with_registered_key, params, current_epoch=200
            )

    def test_delegate_unregistered_credential_raises(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Delegating with an unregistered credential fails."""
        cert = StakeDelegation(
            _stake_credential(0xAA),
            _pool_key_hash(0xBB),
        )
        with pytest.raises(DelegationError, match="StakeKeyNotRegisteredDELEG"):
            process_certificate(cert, empty_state, params, current_epoch=200)

    def test_redelegate_to_different_pool(
        self, params: ShelleyProtocolParams
    ):
        """Re-delegating to a different pool updates the delegation map."""
        cred_hash = _fake_hash(0xAA)
        pool1_hash = _fake_hash(0xB1)
        pool2_hash = _fake_hash(0xB2)

        state = DelegationState(
            rewards={cred_hash: 0},
            delegations={cred_hash: pool1_hash},
            pools={
                pool1_hash: _pool_params(0xB1),
                pool2_hash: _pool_params(0xB2),
            },
        )

        cert = StakeDelegation(
            _stake_credential(0xAA),
            _pool_key_hash(0xB2),
        )
        new_state = process_certificate(cert, state, params, current_epoch=200)
        assert new_state.delegations[cred_hash] == pool2_hash


# ===========================================================================
# Pool registration (RegPool)
# ===========================================================================


class TestPoolRegistration:
    """Tests for the RegPool (pool registration) certificate."""

    def test_register_new_pool(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Registering a new pool adds it to the pools map."""
        pp = _pool_params(0xBB)
        cert = PoolRegistration(pp)
        new_state = process_certificate(cert, empty_state, params, current_epoch=200)

        pool_hash = _fake_hash(0xBB)
        assert pool_hash in new_state.pools
        assert new_state.pools[pool_hash].pledge == 100_000_000
        assert new_state.pools[pool_hash].cost == 340_000_000
        assert new_state.pools[pool_hash].margin == Fraction(1, 100)

    def test_reregister_updates_params(
        self, params: ShelleyProtocolParams
    ):
        """Re-registering an existing pool updates its parameters."""
        pool_hash = _fake_hash(0xBB)
        old_pp = _pool_params(0xBB)
        state = DelegationState(pools={pool_hash: old_pp})

        new_pp = PoolParams(
            operator=PoolKeyHash(_fake_hash(0xBB)),
            vrf_keyhash=_fake_hash(0xCC, size=32),
            pledge=200_000_000,  # changed pledge
            cost=400_000_000,  # changed cost
            margin=Fraction(5, 100),  # changed margin
            reward_account=_fake_hash(0xDD, size=29),
            pool_owners=[VerificationKeyHash(_fake_hash(0xBB))],
        )
        cert = PoolRegistration(new_pp)
        new_state = process_certificate(cert, state, params, current_epoch=200)

        assert new_state.pools[pool_hash].pledge == 200_000_000
        assert new_state.pools[pool_hash].cost == 400_000_000

    def test_reregister_cancels_retirement(
        self, params: ShelleyProtocolParams
    ):
        """Re-registering a pool that is scheduled to retire cancels the retirement.

        Spec: retiring' = {hk} ⊳ retiring
        """
        pool_hash = _fake_hash(0xBB)
        state = DelegationState(
            pools={pool_hash: _pool_params(0xBB)},
            retiring={pool_hash: 300},  # scheduled to retire at epoch 300
        )

        cert = PoolRegistration(_pool_params(0xBB))
        new_state = process_certificate(cert, state, params, current_epoch=200)

        assert pool_hash not in new_state.retiring
        assert pool_hash in new_state.pools


# ===========================================================================
# Pool retirement (RetirePool)
# ===========================================================================


class TestPoolRetirement:
    """Tests for the RetirePool (pool retirement) certificate."""

    def test_retire_pool_schedules_retirement(
        self, params: ShelleyProtocolParams
    ):
        """Retiring a registered pool schedules it for a future epoch."""
        pool_hash = _fake_hash(0xBB)
        state = DelegationState(pools={pool_hash: _pool_params(0xBB)})

        cert = PoolRetirement(_pool_key_hash(0xBB), epoch=300)
        new_state = process_certificate(cert, state, params, current_epoch=200)

        assert new_state.retiring[pool_hash] == 300
        # Pool is still in pools map until POOLREAP at epoch boundary
        assert pool_hash in new_state.pools

    def test_retire_unregistered_pool_raises(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Retiring a pool that is not registered fails."""
        cert = PoolRetirement(_pool_key_hash(0xFF), epoch=300)
        with pytest.raises(
            DelegationError, match="StakePoolNotRegisteredOnKeyPOOL"
        ):
            process_certificate(cert, empty_state, params, current_epoch=200)

    def test_retire_in_past_epoch_raises(self, params: ShelleyProtocolParams):
        """Retirement epoch must be strictly after the current epoch."""
        pool_hash = _fake_hash(0xBB)
        state = DelegationState(pools={pool_hash: _pool_params(0xBB)})

        cert = PoolRetirement(_pool_key_hash(0xBB), epoch=200)  # same as current
        with pytest.raises(
            DelegationError, match="StakePoolRetirementWrongEpochPOOL"
        ):
            process_certificate(cert, state, params, current_epoch=200)

    def test_retire_in_earlier_epoch_raises(self, params: ShelleyProtocolParams):
        """Retirement epoch in the past is also invalid."""
        pool_hash = _fake_hash(0xBB)
        state = DelegationState(pools={pool_hash: _pool_params(0xBB)})

        cert = PoolRetirement(_pool_key_hash(0xBB), epoch=100)
        with pytest.raises(
            DelegationError, match="StakePoolRetirementWrongEpochPOOL"
        ):
            process_certificate(cert, state, params, current_epoch=200)


# ===========================================================================
# Deposit accounting
# ===========================================================================


class TestDepositAccounting:
    """Tests for compute_certificate_deposits."""

    def test_key_registration_deposit(self, params: ShelleyProtocolParams):
        """A single key registration charges key_deposit."""
        certs = [StakeRegistration(_stake_credential(0xAA))]
        assert compute_certificate_deposits(certs, params) == params.key_deposit

    def test_key_deregistration_refund(self, params: ShelleyProtocolParams):
        """A single key deregistration refunds key_deposit (negative)."""
        certs = [StakeDeregistration(_stake_credential(0xAA))]
        assert compute_certificate_deposits(certs, params) == -params.key_deposit

    def test_pool_registration_deposit(self, params: ShelleyProtocolParams):
        """A pool registration charges pool_deposit."""
        certs = [PoolRegistration(_pool_params(0xBB))]
        assert compute_certificate_deposits(certs, params) == params.pool_deposit

    def test_delegation_no_deposit(self, params: ShelleyProtocolParams):
        """Delegation certificates do not affect deposits."""
        certs = [StakeDelegation(_stake_credential(0xAA), _pool_key_hash(0xBB))]
        assert compute_certificate_deposits(certs, params) == 0

    def test_pool_retirement_no_deposit(self, params: ShelleyProtocolParams):
        """Pool retirement does not affect deposits (refund is at epoch boundary)."""
        certs = [PoolRetirement(_pool_key_hash(0xBB), epoch=300)]
        assert compute_certificate_deposits(certs, params) == 0

    def test_mixed_certificates_net_deposit(self, params: ShelleyProtocolParams):
        """Mixed certificates: register key + register pool - deregister key."""
        certs = [
            StakeRegistration(_stake_credential(0xAA)),
            PoolRegistration(_pool_params(0xBB)),
            StakeDeregistration(_stake_credential(0xCC)),
        ]
        expected = params.key_deposit + params.pool_deposit - params.key_deposit
        assert compute_certificate_deposits(certs, params) == expected

    def test_register_deregister_roundtrip_net_zero(
        self, params: ShelleyProtocolParams
    ):
        """Register then deregister the same key nets to zero deposit."""
        certs = [
            StakeRegistration(_stake_credential(0xAA)),
            StakeDeregistration(_stake_credential(0xAA)),
        ]
        assert compute_certificate_deposits(certs, params) == 0


# ===========================================================================
# Batch processing (process_certificates / DELEGS)
# ===========================================================================


class TestProcessCertificates:
    """Tests for process_certificates (the DELEGS rule)."""

    def test_register_then_delegate(self, params: ShelleyProtocolParams):
        """Register a key, register a pool, then delegate — all in one tx."""
        certs = [
            PoolRegistration(_pool_params(0xBB)),
            StakeRegistration(_stake_credential(0xAA)),
            StakeDelegation(_stake_credential(0xAA), _pool_key_hash(0xBB)),
        ]
        state = DelegationState()
        new_state = process_certificates(certs, state, params, current_epoch=200)

        cred_hash = _fake_hash(0xAA)
        pool_hash = _fake_hash(0xBB)
        assert cred_hash in new_state.rewards
        assert pool_hash in new_state.pools
        assert new_state.delegations[cred_hash] == pool_hash

    def test_empty_cert_list(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """Processing an empty certificate list returns the same state."""
        new_state = process_certificates([], empty_state, params, current_epoch=200)
        assert new_state is empty_state  # no copy needed for empty list

    def test_error_halts_processing(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """An error in any certificate stops processing (fail-fast)."""
        certs = [
            StakeRegistration(_stake_credential(0xAA)),
            # This delegation fails because pool 0xFF is not registered
            StakeDelegation(_stake_credential(0xAA), _pool_key_hash(0xFF)),
        ]
        with pytest.raises(
            DelegationError, match="StakeDelegationImpossibleDELEG"
        ):
            process_certificates(certs, empty_state, params, current_epoch=200)

    def test_unrecognized_cert_type_raises(
        self, empty_state: DelegationState, params: ShelleyProtocolParams
    ):
        """An unrecognized certificate type raises TypeError."""
        with pytest.raises(TypeError, match="Unrecognized certificate type"):
            process_certificate(
                "not_a_cert",  # type: ignore[arg-type]
                empty_state,
                params,
                current_epoch=200,
            )
