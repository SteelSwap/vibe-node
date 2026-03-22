"""Ledger test parity — Haskell-equivalent validation scenarios.

Tests are organized to mirror the Haskell ledger test suite structure:

1. Shelley UTxO rules: input existence, value conservation, fee, TTL, min UTxO
2. Fee validation: min_fee calculation, fee-too-small rejection
3. Certificate processing: stake reg/dereg, delegation, pool reg/retirement (strict mode)
4. Allegra/Mary multi-asset: validity intervals, mint/burn, policy ID
5. Timelock evaluation: RequireTimeAfter, RequireTimeBefore, AllOf, AnyOf, MOfN
6. Conway governance: proposal validation, voting procedures, DRep lifecycle

Each test class maps to a specific Haskell predicate failure or transition rule,
cited by spec reference and Haskell module.

Spec references:
    * Shelley ledger formal spec, Sections 8-10
    * Allegra ledger formal spec (validity intervals)
    * Mary ledger formal spec, Section 3 (multi-asset)
    * Conway ledger formal spec, Sections 5-6 (governance)

Haskell references:
    * ``Cardano.Ledger.Shelley.Rules.Utxo`` — ShelleyUtxoPredFailure
    * ``Cardano.Ledger.Shelley.Rules.Deleg`` — ShelleyDelegPredFailure
    * ``Cardano.Ledger.Allegra.Scripts`` — Timelock evaluation
    * ``Cardano.Ledger.Conway.Rules.Gov`` — ConwayGovPredFailure
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction

import pytest

from pycardano import (
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
    MultiAsset,
    Asset,
)
from pycardano.transaction import AssetName
from pycardano.address import Address
from pycardano.certificate import (
    PoolParams,
    PoolRegistration,
    PoolRetirement,
    StakeCredential,
    StakeDelegation,
    StakeDeregistration,
    StakeRegistration,
)
from pycardano.hash import (
    PoolKeyHash,
    ScriptHash,
    TransactionId,
    VerificationKeyHash,
    VrfKeyHash,
)
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet

from vibe.cardano.ledger.shelley import (
    ShelleyProtocolParams,
    ShelleyUTxO,
    ShelleyValidationError,
    _output_lovelace,
    shelley_min_fee,
    validate_shelley_utxo,
)
from vibe.cardano.ledger.allegra_mary import (
    MaryProtocolParams,
    Timelock,
    TimelockType,
    ValidityInterval,
    _value_eq,
    evaluate_timelock,
    mary_min_utxo_value,
    validate_allegra_utxo,
    validate_mary_tx,
    validate_validity_interval,
)
from vibe.cardano.ledger.shelley_delegation import (
    DelegationError,
    DelegationState,
    _credential_hash,
    _pool_key_hash,
    process_certificate,
    process_certificates,
    compute_certificate_deposits,
)
from vibe.cardano.ledger.conway import (
    ConwayGovernanceError,
    ConwayValidationError,
    apply_conway_tx,
    check_ratification,
    expire_proposals,
    process_conway_certificate,
    process_drep_deregistration,
    process_drep_registration,
    validate_proposal,
    validate_voting_procedures,
    validate_hard_fork_initiation,
    validate_treasury_withdrawals,
    validate_withdrawal_delegation,
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
    Vote,
    Voter,
    VoterRole,
    VotingProcedure,
)


# ===========================================================================
# Test fixtures
# ===========================================================================

TX_ID_A = TransactionId(b"\xaa" * 32)
TX_ID_B = TransactionId(b"\xbb" * 32)
TX_ID_C = TransactionId(b"\xcc" * 32)

MAINNET_ADDR = Address(
    payment_part=VerificationKeyHash(b"\xaa" * 28),
    staking_part=VerificationKeyHash(b"\xbb" * 28),
    network=Network.MAINNET,
)

# 28-byte test credential/pool hashes
CRED_A = b"\xaa" * 28
CRED_B = b"\xbb" * 28
CRED_C = b"\xcc" * 28
POOL_1 = b"\x01" * 28
POOL_2 = b"\x02" * 28
VRF_KEY_1 = b"\x11" * 32
VRF_KEY_2 = b"\x22" * 32
REWARD_ACCOUNT_1 = b"\xe1" + POOL_1  # mainnet VKey staking
ANCHOR_HASH = b"\xdd" * 32


def _make_txin(tx_id: TransactionId = TX_ID_A, index: int = 0) -> TransactionInput:
    return TransactionInput(tx_id, index)


def _make_txout(
    amount: int = 2_000_000,
    address: Address | None = None,
) -> TransactionOutput:
    if address is None:
        address = MAINNET_ADDR
    return TransactionOutput(address, amount)


def _make_utxo(
    inputs_and_amounts: list[tuple[TransactionInput, int]] | None = None,
) -> ShelleyUTxO:
    """Build a UTxO set from (input, lovelace_amount) pairs."""
    if inputs_and_amounts is None:
        inputs_and_amounts = [(_make_txin(), 10_000_000)]
    return {txin: _make_txout(amount=amt) for txin, amt in inputs_and_amounts}


def _default_params() -> ShelleyProtocolParams:
    return ShelleyProtocolParams()


def _make_stake_cred(raw: bytes) -> StakeCredential:
    return StakeCredential(VerificationKeyHash(raw))


def _make_pkh(raw: bytes) -> PoolKeyHash:
    return PoolKeyHash(raw)


def _make_pool_params(
    operator: bytes,
    vrf_key: bytes = VRF_KEY_1,
    pledge: int = 100_000_000,
    cost: int = 340_000_000,
    margin: Fraction = Fraction(1, 100),
    reward_account: bytes = REWARD_ACCOUNT_1,
) -> PoolParams:
    return PoolParams(
        operator=_make_pkh(operator),
        vrf_keyhash=VrfKeyHash(vrf_key),
        pledge=pledge,
        cost=cost,
        margin=margin,
        reward_account=reward_account,
        pool_owners=[VerificationKeyHash(operator)],
    )


def _make_anchor(
    url: str = "https://example.com/metadata.json",
    data_hash: bytes = ANCHOR_HASH,
) -> Anchor:
    return Anchor(url=url, data_hash=data_hash)


def _make_conway_params() -> ConwayProtocolParams:
    return ConwayProtocolParams()


def _make_gov_state() -> GovernanceState:
    return GovernanceState()


# ===========================================================================
# 1. Shelley UTxO rules
# ===========================================================================


class TestShelleyUTxOInputExistence:
    """Haskell: InputsNotInUTxO in ShelleyUtxoPredFailure.
    Spec: txins txb subseteq dom utxo
    """

    def test_valid_input_passes(self) -> None:
        """All inputs exist in UTxO -- no error."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 10_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(8_000_000)],
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert not any("InputsNotInUTxO" in e for e in errors)

    def test_missing_input_rejected(self) -> None:
        """Input not in UTxO raises InputsNotInUTxO."""
        missing = _make_txin(TX_ID_B, 99)
        utxo = _make_utxo()
        tx_body = TransactionBody(
            inputs=[missing],
            outputs=[_make_txout(1_000_000)],
            fee=1_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert any("InputsNotInUTxO" in e for e in errors)

    def test_empty_input_set_rejected(self) -> None:
        """Transaction with no inputs raises InputSetEmptyUTxO."""
        tx_body = TransactionBody(
            inputs=[],
            outputs=[_make_txout(1_000_000)],
            fee=1_000_000,
        )
        errors = validate_shelley_utxo(tx_body, {}, _default_params(), 0, 200)
        assert any("InputSetEmptyUTxO" in e for e in errors)

    def test_double_spend_same_utxo_in_set(self) -> None:
        """pycardano deduplicates inputs as a set, so the same input
        listed twice only appears once. This is Shelley's implicit
        double-spend prevention via set-based inputs.

        Haskell: inputs are a Set, so duplicates are inherently impossible.
        """
        txin = _make_txin()
        utxo = _make_utxo([(txin, 10_000_000)])
        # Even if we pass the same input twice, TransactionBody deduplicates
        tx_body = TransactionBody(
            inputs=[txin, txin],
            outputs=[_make_txout(8_000_000)],
            fee=2_000_000,
        )
        # Inputs should behave as a set — this tests the Python side
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        # Should not have InputsNotInUTxO since the single input exists
        assert not any("InputsNotInUTxO" in e for e in errors)


class TestShelleyUTxOValuePreservation:
    """Haskell: ValueNotConservedUTxO in ShelleyUtxoPredFailure.
    Spec: consumed pp utxo txb = produced pp stakePools txb
    """

    def test_balanced_tx_passes(self) -> None:
        """sum(inputs) == sum(outputs) + fee."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 5_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(3_000_000)],
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert not any("ValueNotConserved" in e for e in errors)

    def test_unbalanced_tx_rejected(self) -> None:
        """sum(inputs) != sum(outputs) + fee raises ValueNotConservedUTxO."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 5_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(4_000_000)],
            fee=2_000_000,  # 4M + 2M = 6M != 5M input
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert any("ValueNotConserved" in e for e in errors)

    def test_multiple_inputs_and_outputs(self) -> None:
        """Multiple inputs and outputs must balance."""
        txin_a = _make_txin(TX_ID_A, 0)
        txin_b = _make_txin(TX_ID_B, 0)
        utxo = _make_utxo([(txin_a, 3_000_000), (txin_b, 7_000_000)])
        tx_body = TransactionBody(
            inputs=[txin_a, txin_b],
            outputs=[_make_txout(4_000_000), _make_txout(4_000_000)],
            fee=2_000_000,  # 3M + 7M = 4M + 4M + 2M = 10M
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert not any("ValueNotConserved" in e for e in errors)


class TestShelleyOutputTooSmall:
    """Haskell: OutputTooSmallUTxO in ShelleyUtxoPredFailure.
    Spec: forall txout in txouts txb, coin txout >= minUTxOValue pp
    """

    def test_output_at_min_passes(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],  # Exactly min_utxo_value
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert not any("OutputTooSmall" in e for e in errors)

    def test_output_below_min_rejected(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(500_000)],  # Below 1 ADA min
            fee=2_500_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert any("OutputTooSmall" in e for e in errors)

    def test_zero_output_rejected(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(0)],
            fee=3_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert any("OutputTooSmall" in e for e in errors)


class TestShelleyTTLExpiry:
    """Haskell: ExpiredUTxO in ShelleyUtxoPredFailure.
    Spec: slot < txttl txb
    """

    def test_ttl_in_future_passes(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 500, 200)
        assert not any("ExpiredUTxO" in e for e in errors)

    def test_ttl_at_current_slot_rejected(self) -> None:
        """current_slot == ttl means expired (strict less-than)."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
            ttl=500,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 500, 200)
        assert any("ExpiredUTxO" in e for e in errors)

    def test_ttl_in_past_rejected(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
            ttl=100,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 500, 200)
        assert any("ExpiredUTxO" in e for e in errors)

    def test_no_ttl_passes(self) -> None:
        """No TTL set means no expiry check."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 999999, 200)
        assert not any("ExpiredUTxO" in e for e in errors)


class TestShelleyMaxTxSize:
    """Haskell: MaxTxSizeUTxO in ShelleyUtxoPredFailure.
    Spec: txsize txb <= maxTxSize pp
    """

    def test_within_limit_passes(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert not any("MaxTxSize" in e for e in errors)

    def test_exceeds_limit_rejected(self) -> None:
        txin = _make_txin()
        utxo = _make_utxo([(txin, 3_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(1_000_000)],
            fee=2_000_000,
        )
        errors = validate_shelley_utxo(
            tx_body, utxo, _default_params(), 0, 20000  # > 16384
        )
        assert any("MaxTxSize" in e for e in errors)


# ===========================================================================
# 2. Fee validation
# ===========================================================================


class TestShelleyMinFee:
    """Haskell: shelleyMinFeeTx in Cardano.Ledger.Shelley.Rules.Utxo.
    Spec: minfee pp tx = min_fee_a * txSize + min_fee_b
    """

    def test_min_fee_linear_formula(self) -> None:
        params = _default_params()
        # fee = 44 * 200 + 155381 = 8800 + 155381 = 164181
        assert shelley_min_fee(200, params) == 44 * 200 + 155381

    def test_min_fee_zero_size(self) -> None:
        params = _default_params()
        assert shelley_min_fee(0, params) == params.min_fee_b

    def test_min_fee_negative_size_raises(self) -> None:
        with pytest.raises(ValueError):
            shelley_min_fee(-1, _default_params())

    def test_fee_too_small_rejected(self) -> None:
        """Fee below minimum raises FeeTooSmallUTxO."""
        txin = _make_txin()
        utxo = _make_utxo([(txin, 10_000_000)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(9_999_900)],
            fee=100,  # Way below min_fee
        )
        errors = validate_shelley_utxo(tx_body, utxo, _default_params(), 0, 200)
        assert any("FeeTooSmall" in e for e in errors)

    def test_fee_at_minimum_passes(self) -> None:
        """Fee exactly at minimum passes."""
        params = _default_params()
        tx_size = 200
        min_fee = shelley_min_fee(tx_size, params)

        txin = _make_txin()
        input_amount = 5_000_000 + min_fee
        utxo = _make_utxo([(txin, input_amount)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(5_000_000)],
            fee=min_fee,
        )
        errors = validate_shelley_utxo(tx_body, utxo, params, 0, tx_size)
        assert not any("FeeTooSmall" in e for e in errors)

    def test_fee_above_minimum_passes(self) -> None:
        """Fee above minimum also passes (overpaying is allowed)."""
        params = _default_params()
        tx_size = 200
        overpay_fee = shelley_min_fee(tx_size, params) + 100_000

        txin = _make_txin()
        input_amount = 5_000_000 + overpay_fee
        utxo = _make_utxo([(txin, input_amount)])
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(5_000_000)],
            fee=overpay_fee,
        )
        errors = validate_shelley_utxo(tx_body, utxo, params, 0, tx_size)
        assert not any("FeeTooSmall" in e for e in errors)


# ===========================================================================
# 3. Certificate processing (strict mode)
# ===========================================================================


class TestStrictStakeRegistration:
    """Haskell: ShelleyDelegPredFailure — StakeKeyAlreadyRegisteredDELEG.
    Spec: DELEG rule, RegKey case — precondition: hk not-in dom rewards.
    """

    def test_registration_succeeds(self) -> None:
        state = DelegationState()
        cert = StakeRegistration(_make_stake_cred(CRED_A))
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert CRED_A in new_state.rewards
        assert new_state.rewards[CRED_A] == 0

    def test_duplicate_registration_raises(self) -> None:
        """Strict mode: duplicate registration raises DelegationError."""
        state = DelegationState()
        state.rewards[CRED_A] = 0
        cert = StakeRegistration(_make_stake_cred(CRED_A))
        with pytest.raises(DelegationError, match="StakeKeyAlreadyRegisteredDELEG"):
            process_certificate(cert, state, _default_params(), 0)


class TestStrictStakeDeregistration:
    """Haskell: StakeKeyNotRegisteredDELEG, StakeKeyNonZeroAccountBalanceDELEG.
    Spec: DELEG rule, DeRegKey case.
    """

    def test_deregistration_succeeds(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert CRED_A not in new_state.rewards

    def test_deregistration_removes_delegation(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        state.delegations[CRED_A] = POOL_1
        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert CRED_A not in new_state.delegations

    def test_deregistration_unregistered_raises(self) -> None:
        state = DelegationState()
        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        with pytest.raises(DelegationError, match="StakeKeyNotRegisteredDELEG"):
            process_certificate(cert, state, _default_params(), 0)

    def test_deregistration_nonzero_balance_raises(self) -> None:
        """Cannot deregister with non-zero reward balance."""
        state = DelegationState()
        state.rewards[CRED_A] = 1_000_000
        cert = StakeDeregistration(_make_stake_cred(CRED_A))
        with pytest.raises(DelegationError, match="StakeKeyNonZeroAccountBalance"):
            process_certificate(cert, state, _default_params(), 0)


class TestStrictDelegation:
    """Haskell: StakeKeyNotRegisteredDELEG, StakeDelegationImpossibleDELEG.
    Spec: DELEG rule, Delegate case.
    """

    def test_delegation_succeeds(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert new_state.delegations[CRED_A] == POOL_1

    def test_delegation_unregistered_credential_raises(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))
        with pytest.raises(DelegationError, match="StakeKeyNotRegisteredDELEG"):
            process_certificate(cert, state, _default_params(), 0)

    def test_delegation_unregistered_pool_raises(self) -> None:
        state = DelegationState()
        state.rewards[CRED_A] = 0
        cert = StakeDelegation(_make_stake_cred(CRED_A), _make_pkh(POOL_1))
        with pytest.raises(DelegationError, match="StakeDelegationImpossibleDELEG"):
            process_certificate(cert, state, _default_params(), 0)


class TestStrictPoolRegistration:
    """Haskell: ShelleyPoolPredFailure — StakePoolCostTooLowPOOL.
    Spec: POOL rule, RegPool case.
    """

    def test_pool_registration_succeeds(self) -> None:
        state = DelegationState()
        cert = PoolRegistration(_make_pool_params(POOL_1))
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert POOL_1 in new_state.pools

    def test_pool_cost_too_low_raises(self) -> None:
        """Pool cost below minPoolCost raises StakePoolCostTooLowPOOL."""
        state = DelegationState()
        # minPoolCost defaults to 340 ADA
        cert = PoolRegistration(
            _make_pool_params(POOL_1, cost=100_000_000)  # 100 ADA < 340 ADA
        )
        with pytest.raises(DelegationError, match="StakePoolCostTooLowPOOL"):
            process_certificate(cert, state, _default_params(), 0)

    def test_pool_reregistration_updates_params(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1, pledge=100_000_000)
        cert = PoolRegistration(
            _make_pool_params(POOL_1, pledge=200_000_000)
        )
        new_state = process_certificate(cert, state, _default_params(), 0)
        assert new_state.pools[POOL_1].pledge == 200_000_000

    def test_pool_reregistration_cancels_retirement(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        state.retiring[POOL_1] = 10
        cert = PoolRegistration(_make_pool_params(POOL_1))
        new_state = process_certificate(cert, state, _default_params(), 5)
        assert POOL_1 not in new_state.retiring

    def test_duplicate_vrf_key_raises(self) -> None:
        """Two different pools cannot share the same VRF key."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1, vrf_key=VRF_KEY_1)
        cert = PoolRegistration(
            _make_pool_params(POOL_2, vrf_key=VRF_KEY_1)
        )
        with pytest.raises(DelegationError, match="StakePoolDuplicateVrfKeyPOOL"):
            process_certificate(cert, state, _default_params(), 0)


class TestStrictPoolRetirement:
    """Haskell: StakePoolNotRegisteredOnKeyPOOL, StakePoolRetirementWrongEpochPOOL.
    Spec: POOL rule, RetirePool case.
    """

    def test_pool_retirement_succeeds(self) -> None:
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        cert = PoolRetirement(_make_pkh(POOL_1), epoch=15)
        new_state = process_certificate(cert, state, _default_params(), 5)
        assert new_state.retiring[POOL_1] == 15

    def test_retirement_unregistered_pool_raises(self) -> None:
        state = DelegationState()
        cert = PoolRetirement(_make_pkh(POOL_1), epoch=15)
        with pytest.raises(DelegationError, match="StakePoolNotRegisteredOnKeyPOOL"):
            process_certificate(cert, state, _default_params(), 5)

    def test_retirement_past_epoch_raises(self) -> None:
        """Retirement epoch must be in the future."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        cert = PoolRetirement(_make_pkh(POOL_1), epoch=3)
        with pytest.raises(DelegationError, match="StakePoolRetirementWrongEpochPOOL"):
            process_certificate(cert, state, _default_params(), 5)

    def test_retirement_current_epoch_raises(self) -> None:
        """Cannot retire at current epoch (must be strictly future)."""
        state = DelegationState()
        state.pools[POOL_1] = _make_pool_params(POOL_1)
        cert = PoolRetirement(_make_pkh(POOL_1), epoch=5)
        with pytest.raises(DelegationError, match="StakePoolRetirementWrongEpochPOOL"):
            process_certificate(cert, state, _default_params(), 5)


class TestCertificateDepositAccounting:
    """Haskell: totalCertsDeposits / totalCertsRefunds in Utxo.
    Spec: deposit accounting in consumed/produced equation.
    """

    def test_stake_registration_deposit(self) -> None:
        params = _default_params()
        certs = [StakeRegistration(_make_stake_cred(CRED_A))]
        assert compute_certificate_deposits(certs, params) == params.key_deposit

    def test_stake_deregistration_refund(self) -> None:
        params = _default_params()
        certs = [StakeDeregistration(_make_stake_cred(CRED_A))]
        assert compute_certificate_deposits(certs, params) == -params.key_deposit

    def test_reg_and_dereg_cancel(self) -> None:
        params = _default_params()
        certs = [
            StakeRegistration(_make_stake_cred(CRED_A)),
            StakeDeregistration(_make_stake_cred(CRED_B)),
        ]
        assert compute_certificate_deposits(certs, params) == 0

    def test_pool_registration_deposit(self) -> None:
        params = _default_params()
        certs = [PoolRegistration(_make_pool_params(POOL_1))]
        assert compute_certificate_deposits(certs, params) == params.pool_deposit

    def test_combined_deposits(self) -> None:
        params = _default_params()
        certs = [
            StakeRegistration(_make_stake_cred(CRED_A)),
            PoolRegistration(_make_pool_params(POOL_1)),
        ]
        expected = params.key_deposit + params.pool_deposit
        assert compute_certificate_deposits(certs, params) == expected


# ===========================================================================
# 4. Allegra/Mary: validity intervals and multi-asset
# ===========================================================================


class TestValidityInterval:
    """Haskell: OutsideValidityIntervalUTxO in ShelleyMAUtxoPredFailure.
    Spec: Allegra validity interval — invalid_before <= slot < invalid_hereafter.
    """

    def test_within_interval_passes(self) -> None:
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        errors = validate_validity_interval(interval, 150)
        assert errors == []

    def test_at_lower_bound_passes(self) -> None:
        """Slot equal to invalid_before is valid (inclusive lower bound)."""
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        errors = validate_validity_interval(interval, 100)
        assert errors == []

    def test_below_lower_bound_rejected(self) -> None:
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        errors = validate_validity_interval(interval, 50)
        assert any("OutsideValidityInterval" in e for e in errors)

    def test_at_upper_bound_rejected(self) -> None:
        """Slot equal to invalid_hereafter is invalid (exclusive upper bound)."""
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        errors = validate_validity_interval(interval, 200)
        assert any("OutsideValidityInterval" in e for e in errors)

    def test_above_upper_bound_rejected(self) -> None:
        interval = ValidityInterval(invalid_before=100, invalid_hereafter=200)
        errors = validate_validity_interval(interval, 300)
        assert any("OutsideValidityInterval" in e for e in errors)

    def test_unbounded_both_passes(self) -> None:
        """No bounds means always valid."""
        interval = ValidityInterval()
        errors = validate_validity_interval(interval, 999999)
        assert errors == []

    def test_unbounded_lower_passes(self) -> None:
        interval = ValidityInterval(invalid_hereafter=200)
        errors = validate_validity_interval(interval, 0)
        assert errors == []

    def test_unbounded_upper_passes(self) -> None:
        interval = ValidityInterval(invalid_before=100)
        errors = validate_validity_interval(interval, 999999)
        assert errors == []


class TestMaryMultiAssetValuePreservation:
    """Haskell: ValueNotConservedUTxO (multi-asset version).
    Spec: Mary consumed/produced equations with multi-asset.
    """

    def test_mint_preserves_value(self) -> None:
        """Minting adds tokens to the consumed side."""
        txin = _make_txin()
        policy = ScriptHash(b"\xff" * 28)
        asset_name = AssetName(b"TestToken")
        mint_qty = 100

        # Input: 5 ADA
        utxo = _make_utxo([(txin, 5_000_000)])

        # Output: 3 ADA + 100 tokens
        output_value = Value(
            coin=3_000_000,
            multi_asset=MultiAsset({policy: Asset({asset_name: mint_qty})}),
        )
        output = TransactionOutput(MAINNET_ADDR, output_value)

        mint_value = Value(
            coin=0,
            multi_asset=MultiAsset({policy: Asset({asset_name: mint_qty})}),
        )

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[output],
            fee=2_000_000,
            mint=MultiAsset({policy: Asset({asset_name: mint_qty})}),
        )

        params = MaryProtocolParams()
        errors = validate_mary_tx(
            tx_body, None, utxo, params, 0, tx_size=200, mint=mint_value
        )
        assert not any("ValueNotConserved" in e for e in errors)

    def test_burn_preserves_value(self) -> None:
        """Burning removes tokens — consumed side gets negative mint."""
        txin = _make_txin()
        policy = ScriptHash(b"\xff" * 28)
        asset_name = AssetName(b"TestToken")

        # Input: 5 ADA + 100 tokens
        input_value = Value(
            coin=5_000_000,
            multi_asset=MultiAsset({policy: Asset({asset_name: 100})}),
        )
        utxo: ShelleyUTxO = {txin: TransactionOutput(MAINNET_ADDR, input_value)}

        # Output: 3 ADA + 50 tokens (burned 50)
        output_value = Value(
            coin=3_000_000,
            multi_asset=MultiAsset({policy: Asset({asset_name: 50})}),
        )
        output = TransactionOutput(MAINNET_ADDR, output_value)

        # Mint of -50 (burn)
        mint_value = Value(
            coin=0,
            multi_asset=MultiAsset({policy: Asset({asset_name: -50})}),
        )

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[output],
            fee=2_000_000,
            mint=MultiAsset({policy: Asset({asset_name: -50})}),
        )

        params = MaryProtocolParams()
        errors = validate_mary_tx(
            tx_body, None, utxo, params, 0, tx_size=200, mint=mint_value
        )
        assert not any("ValueNotConserved" in e for e in errors)

    def test_unbalanced_multi_asset_rejected(self) -> None:
        """Missing tokens in outputs raises ValueNotConservedUTxO."""
        txin = _make_txin()
        policy = ScriptHash(b"\xff" * 28)
        asset_name = AssetName(b"TestToken")

        input_value = Value(
            coin=5_000_000,
            multi_asset=MultiAsset({policy: Asset({asset_name: 100})}),
        )
        utxo: ShelleyUTxO = {txin: TransactionOutput(MAINNET_ADDR, input_value)}

        # Output: only ADA, no tokens (tokens lost!)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[_make_txout(3_000_000)],
            fee=2_000_000,
        )

        params = MaryProtocolParams()
        errors = validate_mary_tx(tx_body, None, utxo, params, 0, tx_size=200)
        assert any("ValueNotConserved" in e for e in errors)


# ===========================================================================
# 5. Timelock evaluation
# ===========================================================================


class TestTimelockEvaluation:
    """Haskell: validateTimelock in Cardano.Ledger.Allegra.Scripts.
    Spec: Allegra timelock script evaluation.
    """

    def test_require_time_after_satisfied(self) -> None:
        """RequireTimeAfter: current_slot >= slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100)
        assert evaluate_timelock(script, frozenset(), 100) is True
        assert evaluate_timelock(script, frozenset(), 200) is True

    def test_require_time_after_not_satisfied(self) -> None:
        script = Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100)
        assert evaluate_timelock(script, frozenset(), 50) is False

    def test_require_time_before_satisfied(self) -> None:
        """RequireTimeBefore: current_slot < slot."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=100)
        assert evaluate_timelock(script, frozenset(), 50) is True

    def test_require_time_before_at_slot_fails(self) -> None:
        """current_slot == slot fails (strict less-than)."""
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=100)
        assert evaluate_timelock(script, frozenset(), 100) is False

    def test_require_time_before_after_slot_fails(self) -> None:
        script = Timelock(type=TimelockType.REQUIRE_TIME_BEFORE, slot=100)
        assert evaluate_timelock(script, frozenset(), 200) is False

    def test_require_signature_satisfied(self) -> None:
        key = b"\xaa" * 28
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key)
        assert evaluate_timelock(script, frozenset([key]), 0) is True

    def test_require_signature_not_satisfied(self) -> None:
        key = b"\xaa" * 28
        script = Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key)
        assert evaluate_timelock(script, frozenset(), 0) is False

    def test_all_of_satisfied(self) -> None:
        key_a = b"\xaa" * 28
        key_b = b"\xbb" * 28
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_a),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_b),
            ),
        )
        assert evaluate_timelock(script, frozenset([key_a, key_b]), 0) is True

    def test_all_of_partial_fails(self) -> None:
        key_a = b"\xaa" * 28
        key_b = b"\xbb" * 28
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_a),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_b),
            ),
        )
        assert evaluate_timelock(script, frozenset([key_a]), 0) is False

    def test_any_of_satisfied(self) -> None:
        key_a = b"\xaa" * 28
        key_b = b"\xbb" * 28
        script = Timelock(
            type=TimelockType.REQUIRE_ANY_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_a),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_b),
            ),
        )
        assert evaluate_timelock(script, frozenset([key_b]), 0) is True

    def test_any_of_none_fails(self) -> None:
        key_a = b"\xaa" * 28
        key_b = b"\xbb" * 28
        script = Timelock(
            type=TimelockType.REQUIRE_ANY_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_a),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key_b),
            ),
        )
        assert evaluate_timelock(script, frozenset(), 0) is False

    def test_m_of_n_satisfied(self) -> None:
        """2-of-3 multisig with 2 signatures."""
        keys = [bytes([i]) * 28 for i in range(3)]
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=tuple(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=k)
                for k in keys
            ),
        )
        assert evaluate_timelock(script, frozenset([keys[0], keys[2]]), 0) is True

    def test_m_of_n_insufficient(self) -> None:
        """2-of-3 multisig with only 1 signature."""
        keys = [bytes([i]) * 28 for i in range(3)]
        script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=tuple(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=k)
                for k in keys
            ),
        )
        assert evaluate_timelock(script, frozenset([keys[0]]), 0) is False

    def test_combined_time_and_signature(self) -> None:
        """AllOf(RequireSignature, RequireTimeAfter)."""
        key = b"\xaa" * 28
        script = Timelock(
            type=TimelockType.REQUIRE_ALL_OF,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key),
                Timelock(type=TimelockType.REQUIRE_TIME_AFTER, slot=100),
            ),
        )
        # Both conditions met
        assert evaluate_timelock(script, frozenset([key]), 200) is True
        # Signature present but too early
        assert evaluate_timelock(script, frozenset([key]), 50) is False
        # Time OK but no signature
        assert evaluate_timelock(script, frozenset(), 200) is False

    def test_all_of_empty_passes(self) -> None:
        """AllOf with empty scripts is vacuously true."""
        script = Timelock(type=TimelockType.REQUIRE_ALL_OF, scripts=())
        assert evaluate_timelock(script, frozenset(), 0) is True

    def test_any_of_empty_fails(self) -> None:
        """AnyOf with empty scripts fails (no script can satisfy)."""
        script = Timelock(type=TimelockType.REQUIRE_ANY_OF, scripts=())
        assert evaluate_timelock(script, frozenset(), 0) is False


# ===========================================================================
# 6. Conway governance
# ===========================================================================


class TestConwayProposalValidation:
    """Haskell: ConwayGovPredFailure — ProposalDepositIncorrect, etc.
    Spec: Conway formal spec, GOV transition rule for proposals.
    """

    def test_valid_proposal_passes(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        proposal = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        errors = validate_proposal(proposal, params, gov_state)
        assert errors == []

    def test_wrong_deposit_rejected(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        proposal = ProposalProcedure(
            deposit=1_000_000,  # Wrong amount
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        errors = validate_proposal(proposal, params, gov_state)
        assert any("ProposalDepositMismatch" in e for e in errors)

    def test_invalid_return_addr_rejected(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        proposal = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xaa" * 10,  # Wrong length
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        errors = validate_proposal(proposal, params, gov_state)
        assert any("ProposalReturnAddrInvalid" in e for e in errors)

    def test_empty_anchor_url_rejected(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        proposal = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=Anchor(url="", data_hash=ANCHOR_HASH),
        )
        errors = validate_proposal(proposal, params, gov_state)
        assert any("ProposalAnchorEmpty" in e for e in errors)


class TestConwayDRepLifecycle:
    """Haskell: ConwayGovCertPredFailure — DRepAlreadyRegistered, etc.
    Spec: Conway formal spec, GOVCERT transition rule.
    """

    def test_drep_registration_succeeds(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        cert = DRepRegistration(
            credential=CRED_A,
            deposit=params.drep_deposit,
        )
        new_state = process_drep_registration(cert, gov_state, params)
        assert CRED_A in new_state.dreps
        assert new_state.dreps[CRED_A] == params.drep_deposit

    def test_drep_duplicate_registration_raises(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        gov_state.dreps[CRED_A] = params.drep_deposit
        cert = DRepRegistration(credential=CRED_A, deposit=params.drep_deposit)
        with pytest.raises(ConwayGovernanceError, match="DRepAlreadyRegistered"):
            process_drep_registration(cert, gov_state, params)

    def test_drep_wrong_deposit_raises(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        cert = DRepRegistration(credential=CRED_A, deposit=1_000_000)
        with pytest.raises(ConwayGovernanceError, match="DRepDepositMismatch"):
            process_drep_registration(cert, gov_state, params)

    def test_drep_deregistration_succeeds(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        gov_state.dreps[CRED_A] = params.drep_deposit
        cert = DRepDeregistration(
            credential=CRED_A,
            deposit_refund=params.drep_deposit,
        )
        new_state = process_drep_deregistration(cert, gov_state)
        assert CRED_A not in new_state.dreps

    def test_drep_deregistration_unregistered_raises(self) -> None:
        gov_state = _make_gov_state()
        cert = DRepDeregistration(credential=CRED_A, deposit_refund=500_000_000)
        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_drep_deregistration(cert, gov_state)

    def test_drep_deregistration_wrong_refund_raises(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        gov_state.dreps[CRED_A] = params.drep_deposit
        cert = DRepDeregistration(credential=CRED_A, deposit_refund=1)
        with pytest.raises(ConwayGovernanceError, match="DRepDepositRefundMismatch"):
            process_drep_deregistration(cert, gov_state)


class TestConwayVotingProcedures:
    """Haskell: ConwayGovPredFailure — VoterNotAuthorized, GovActionIdNotFound.
    Spec: Conway formal spec, GOV transition rule for votes.
    """

    def _setup_gov_state_with_proposal(self) -> tuple[GovernanceState, GovActionId]:
        """Create a gov state with one active proposal and a DRep."""
        gov_state = _make_gov_state()
        action_id = GovActionId(tx_id=b"\xaa" * 32, gov_action_index=0)
        gov_state.proposals[action_id] = ProposalProcedure(
            deposit=100_000_000_000,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        gov_state.votes[action_id] = {}
        gov_state.dreps[CRED_A] = 500_000_000
        return gov_state, action_id

    def test_valid_drep_vote_passes(self) -> None:
        gov_state, action_id = self._setup_gov_state_with_proposal()
        params = _make_conway_params()
        voter = Voter(role=VoterRole.DREP, credential=CRED_A)
        procedures = {
            voter: {action_id: VotingProcedure(vote=Vote.YES)},
        }
        errors = validate_voting_procedures(procedures, gov_state, 0, params)
        assert errors == []

    def test_unregistered_drep_vote_rejected(self) -> None:
        gov_state, action_id = self._setup_gov_state_with_proposal()
        params = _make_conway_params()
        voter = Voter(role=VoterRole.DREP, credential=CRED_B)  # Not registered
        procedures = {
            voter: {action_id: VotingProcedure(vote=Vote.YES)},
        }
        errors = validate_voting_procedures(procedures, gov_state, 0, params)
        assert any("VoterNotAuthorized" in e for e in errors)

    def test_vote_on_nonexistent_proposal_rejected(self) -> None:
        gov_state, _ = self._setup_gov_state_with_proposal()
        params = _make_conway_params()
        voter = Voter(role=VoterRole.DREP, credential=CRED_A)
        fake_action_id = GovActionId(tx_id=b"\xff" * 32, gov_action_index=0)
        procedures = {
            voter: {fake_action_id: VotingProcedure(vote=Vote.YES)},
        }
        errors = validate_voting_procedures(procedures, gov_state, 0, params)
        assert any("GovActionIdNotFound" in e for e in errors)

    def test_cc_member_vote_passes(self) -> None:
        gov_state, action_id = self._setup_gov_state_with_proposal()
        gov_state.committee[CRED_B] = 100  # Expiry at epoch 100
        params = _make_conway_params()
        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=CRED_B)
        procedures = {
            voter: {action_id: VotingProcedure(vote=Vote.YES)},
        }
        errors = validate_voting_procedures(procedures, gov_state, 50, params)
        assert errors == []

    def test_expired_cc_member_rejected(self) -> None:
        gov_state, action_id = self._setup_gov_state_with_proposal()
        gov_state.committee[CRED_B] = 10  # Expired at epoch 10
        params = _make_conway_params()
        voter = Voter(role=VoterRole.CONSTITUTIONAL_COMMITTEE, credential=CRED_B)
        procedures = {
            voter: {action_id: VotingProcedure(vote=Vote.YES)},
        }
        errors = validate_voting_procedures(procedures, gov_state, 50, params)
        assert any("VoterExpired" in e for e in errors)


class TestConwayProposalExpiry:
    """Haskell: processProposals at epoch boundary.
    Spec: Conway formal spec, proposal expiry after govActionLifetime.
    """

    def test_proposals_within_lifetime_kept(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        action_id = GovActionId(tx_id=b"\xaa" * 32, gov_action_index=0)
        gov_state.proposals[action_id] = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        proposal_epochs = {action_id: 5}
        # lifetime=6, current=10, proposed=5 -> age=5 <= 6 -> not expired
        new_state = expire_proposals(gov_state, 10, proposal_epochs, params)
        assert action_id in new_state.proposals

    def test_proposals_beyond_lifetime_expired(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        action_id = GovActionId(tx_id=b"\xaa" * 32, gov_action_index=0)
        gov_state.proposals[action_id] = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        proposal_epochs = {action_id: 1}
        # lifetime=6, current=10, proposed=1 -> age=9 > 6 -> expired
        new_state = expire_proposals(gov_state, 10, proposal_epochs, params)
        assert action_id not in new_state.proposals


class TestConwayHardForkValidation:
    """Haskell: HardForkInitiation validation in Conway.Rules.Gov.
    Spec: Conway formal spec, hard fork initiation rules.
    """

    def test_valid_hard_fork_passes(self) -> None:
        gov_state = _make_gov_state()
        gov_state.current_protocol_version = (9, 0)
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(10, 0),
        )
        errors = validate_hard_fork_initiation(action, gov_state)
        assert errors == []

    def test_wrong_major_version_rejected(self) -> None:
        gov_state = _make_gov_state()
        gov_state.current_protocol_version = (9, 0)
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=(11, 0),  # Skipping version 10
        )
        errors = validate_hard_fork_initiation(action, gov_state)
        assert any("HardForkInitiationVersionMismatch" in e for e in errors)

    def test_missing_version_rejected(self) -> None:
        gov_state = _make_gov_state()
        action = GovAction(
            action_type=GovActionType.HARD_FORK_INITIATION,
            payload=None,
        )
        errors = validate_hard_fork_initiation(action, gov_state)
        assert any("HardForkInitiationMissingVersion" in e for e in errors)


class TestConwayTreasuryWithdrawals:
    """Haskell: TreasuryWithdrawals validation.
    Spec: Conway formal spec, treasury withdrawal rules.
    """

    def test_valid_withdrawal_passes(self) -> None:
        reward_addr = b"\xe1" + b"\xaa" * 28
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={reward_addr: 1_000_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert errors == []

    def test_zero_amount_rejected(self) -> None:
        reward_addr = b"\xe1" + b"\xaa" * 28
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={reward_addr: 0},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("NonPositiveAmount" in e for e in errors)

    def test_invalid_addr_length_rejected(self) -> None:
        action = GovAction(
            action_type=GovActionType.TREASURY_WITHDRAWALS,
            payload={b"\xaa" * 10: 1_000_000},
        )
        errors = validate_treasury_withdrawals(action)
        assert any("InvalidAddr" in e for e in errors)


class TestConwayWithdrawalDelegation:
    """Haskell: WithdrawalsNotInRewardsDELEGS / notDelegatedAddrs check.
    Spec: Conway requires withdrawal credentials to have DRep delegation.
    """

    def test_delegated_credential_passes(self) -> None:
        gov_state = _make_gov_state()
        gov_state.drep_delegations[CRED_A] = DRep(drep_type=DRepType.ALWAYS_ABSTAIN)
        errors = validate_withdrawal_delegation(CRED_A, gov_state)
        assert errors == []

    def test_undelegated_credential_rejected(self) -> None:
        gov_state = _make_gov_state()
        errors = validate_withdrawal_delegation(CRED_A, gov_state)
        assert any("WithdrawalNotDelegated" in e for e in errors)


class TestConwayDelegVote:
    """Haskell: ConwayGovCertPredFailure — DelegVoteNotRegistered, DRepNotRegistered.
    Spec: Conway formal spec, GOVCERT transition rule, DelegVote case.
    """

    def test_deleg_vote_to_always_abstain_succeeds(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        registered = {CRED_A}
        cert = DelegVote(
            credential=CRED_A,
            drep=DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
        )
        new_state = process_conway_certificate(cert, gov_state, params, registered)
        assert CRED_A in new_state.drep_delegations
        assert new_state.drep_delegations[CRED_A].drep_type == DRepType.ALWAYS_ABSTAIN

    def test_deleg_vote_unregistered_credential_raises(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        cert = DelegVote(
            credential=CRED_A,
            drep=DRep(drep_type=DRepType.ALWAYS_ABSTAIN),
        )
        with pytest.raises(ConwayGovernanceError, match="DelegVoteNotRegistered"):
            process_conway_certificate(cert, gov_state, params, set())

    def test_deleg_vote_to_unregistered_drep_raises(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        registered = {CRED_A}
        # Delegate to a key-hash DRep that is not registered
        cert = DelegVote(
            credential=CRED_A,
            drep=DRep(drep_type=DRepType.KEY_HASH, credential=CRED_B),
        )
        with pytest.raises(ConwayGovernanceError, match="DRepNotRegistered"):
            process_conway_certificate(cert, gov_state, params, registered)

    def test_deleg_vote_to_registered_drep_succeeds(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        gov_state.dreps[CRED_B] = params.drep_deposit
        registered = {CRED_A}
        cert = DelegVote(
            credential=CRED_A,
            drep=DRep(drep_type=DRepType.KEY_HASH, credential=CRED_B),
        )
        new_state = process_conway_certificate(cert, gov_state, params, registered)
        assert new_state.drep_delegations[CRED_A].credential == CRED_B


class TestConwayInfoActionRatification:
    """Haskell: ratifyAction — InfoAction is auto-ratified.
    Spec: Conway formal spec, Section 6 — InfoAction has no thresholds.
    """

    def test_info_action_auto_ratified(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        action_id = GovActionId(tx_id=b"\xaa" * 32, gov_action_index=0)
        gov_state.proposals[action_id] = ProposalProcedure(
            deposit=params.gov_action_deposit,
            return_addr=b"\xe1" + b"\xaa" * 28,
            gov_action=GovAction(action_type=GovActionType.INFO_ACTION),
            anchor=_make_anchor(),
        )
        assert check_ratification(action_id, gov_state, params) is True

    def test_nonexistent_proposal_not_ratified(self) -> None:
        params = _make_conway_params()
        gov_state = _make_gov_state()
        action_id = GovActionId(tx_id=b"\xff" * 32, gov_action_index=0)
        assert check_ratification(action_id, gov_state, params) is False


# ===========================================================================
# Accumulating errors: multiple failures reported at once
# ===========================================================================


class TestAccumulatingErrors:
    """Haskell uses Validation (fail-accumulating applicative) in UTXO rules.
    All failures are collected, not short-circuited.
    """

    def test_multiple_errors_reported(self) -> None:
        """A tx that violates multiple rules reports all of them."""
        missing_txin = _make_txin(TX_ID_B, 99)
        tx_body = TransactionBody(
            inputs=[missing_txin],
            outputs=[_make_txout(100)],  # Below min
            fee=50,  # Below min fee
            ttl=0,  # Already expired
        )
        errors = validate_shelley_utxo(tx_body, {}, _default_params(), 100, 200)
        # Should see: InputsNotInUTxO, ExpiredUTxO, FeeTooSmall, OutputTooSmall
        error_text = " ".join(errors)
        assert "InputsNotInUTxO" in error_text
        assert "ExpiredUTxO" in error_text
        assert "FeeTooSmall" in error_text
        assert "OutputTooSmall" in error_text
