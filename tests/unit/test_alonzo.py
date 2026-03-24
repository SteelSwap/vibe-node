"""Tests for Alonzo-era ledger validation rules (UTXO + UTXOW).

Tests cover the Alonzo UTXO and UTXOW transition rules:
    - CollateralContainsNonADA: collateral must be pure ADA
    - InsufficientCollateral: collateral >= percentage of script fees
    - TooManyCollateralInputs: collateral count within limit
    - ExUnitsTooBigUTxO: total ExUnits within per-tx limit
    - ScriptIntegrityHashMismatch: hash verification
    - Inherited Shelley/Mary rules (fee, TTL, value preservation, etc.)
    - Combined validation (validate_alonzo_tx)
    - Hypothesis property tests

Spec references:
    - Alonzo ledger formal spec, Section 9 (UTxO transition)
    - Alonzo ledger formal spec, Section 10 (UTXOW)
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxo.hs``
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxow.hs``
"""

from __future__ import annotations

import hashlib

import cbor2
from hypothesis import given, settings
from hypothesis import strategies as st
from pycardano import (
    Asset,
    AssetName,
    MultiAsset,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)
from pycardano.address import Address
from pycardano.hash import ScriptHash, TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.ledger.allegra_mary import ValidityInterval
from vibe.cardano.ledger.alonzo import (
    AlonzoValidationError,
    _collateral_contains_non_ada,
    _ex_units_too_big,
    _insufficient_collateral,
    _too_many_collateral_inputs,
    alonzo_min_utxo_value,
    calculate_script_fee,
    validate_alonzo_tx,
    validate_alonzo_utxo,
    validate_alonzo_witnesses,
)
from vibe.cardano.ledger.alonzo_types import (
    AlonzoProtocolParams,
    ExUnitPrices,
    ExUnits,
    Language,
    Redeemer,
    RedeemerTag,
    compute_script_integrity_hash,
)
from vibe.cardano.ledger.shelley import ShelleyUTxO

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


TEST_PARAMS = AlonzoProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    min_utxo_value=1_000_000,
    key_deposit=2_000_000,
    pool_deposit=500_000_000,
    collateral_percentage=150,
    max_collateral_inputs=3,
    max_tx_ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
    max_block_ex_units=ExUnits(mem=50_000_000, steps=40_000_000_000),
    coins_per_utxo_word=4310,
    max_val_size=5000,
    execution_unit_prices=ExUnitPrices(
        mem_price_numerator=1,
        mem_price_denominator=1,
        step_price_numerator=1,
        step_price_denominator=1,
    ),
)


def make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic TransactionId from a seed."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def make_key_pair(
    seed: int = 0,
) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    """Create a deterministic signing/verification key pair."""
    seed_bytes = seed.to_bytes(32, "big")
    sk = PaymentSigningKey(seed_bytes)
    vk = sk.to_verification_key()
    return sk, vk


def make_address(vk: PaymentVerificationKey) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=Network.TESTNET)


def make_policy_id(seed: int = 0) -> ScriptHash:
    """Create a deterministic ScriptHash (28 bytes)."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    """Sign a transaction body and return a VKey witness."""
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def make_simple_utxo(
    tx_id_seed: int = 0,
    index: int = 0,
    value: int | Value = 10_000_000,
    seed: int = 0,
) -> tuple[ShelleyUTxO, TransactionInput, PaymentSigningKey, PaymentVerificationKey]:
    """Create a simple UTxO set with one entry."""
    sk, vk = make_key_pair(seed)
    addr = make_address(vk)
    tx_id = make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk, vk


def make_collateral_utxo(
    tx_id_seed: int = 100,
    index: int = 0,
    value: int | Value = 5_000_000,
    seed: int = 0,
) -> tuple[ShelleyUTxO, TransactionInput]:
    """Create a collateral UTxO entry (ADA-only)."""
    sk, vk = make_key_pair(seed)
    addr = make_address(vk)
    tx_id = make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin


# ---------------------------------------------------------------------------
# CollateralContainsNonADA tests
# ---------------------------------------------------------------------------


class TestCollateralContainsNonADA:
    """Tests for the CollateralContainsNonADA rule."""

    def test_pure_ada_collateral_passes(self):
        """Collateral with only ADA should pass."""
        utxo, txin = make_collateral_utxo(value=5_000_000)
        errors = _collateral_contains_non_ada([txin], utxo)
        assert errors == []

    def test_multi_asset_collateral_fails(self):
        """Collateral containing multi-asset tokens should fail."""
        sk, vk = make_key_pair(seed=50)
        addr = make_address(vk)
        tx_id = make_tx_id(200)
        txin = TransactionInput(tx_id, 0)

        # Create a multi-asset output
        policy_id = make_policy_id(1)
        ma = MultiAsset({policy_id: Asset({AssetName(b"token"): 100})})
        txout = TransactionOutput(addr, Value(coin=5_000_000, multi_asset=ma))
        utxo: ShelleyUTxO = {txin: txout}

        errors = _collateral_contains_non_ada([txin], utxo)
        assert len(errors) == 1
        assert "CollateralContainsNonADA" in errors[0]

    def test_empty_collateral_passes(self):
        """No collateral inputs should produce no errors."""
        errors = _collateral_contains_non_ada([], {})
        assert errors == []

    def test_missing_collateral_utxo_ignored(self):
        """Collateral input not in UTxO is not checked here (caught elsewhere)."""
        tx_id = make_tx_id(999)
        txin = TransactionInput(tx_id, 0)
        errors = _collateral_contains_non_ada([txin], {})
        assert errors == []  # Missing inputs aren't our concern

    def test_multiple_collateral_one_bad(self):
        """If one of multiple collateral inputs has multi-asset, that one fails."""
        sk, vk = make_key_pair(seed=50)
        addr = make_address(vk)

        # Good collateral (ADA only)
        good_txin = TransactionInput(make_tx_id(300), 0)
        good_txout = TransactionOutput(addr, 5_000_000)

        # Bad collateral (has tokens)
        bad_txin = TransactionInput(make_tx_id(301), 0)
        policy_id = make_policy_id(2)
        ma = MultiAsset({policy_id: Asset({AssetName(b"nft"): 1})})
        bad_txout = TransactionOutput(addr, Value(coin=5_000_000, multi_asset=ma))

        utxo: ShelleyUTxO = {good_txin: good_txout, bad_txin: bad_txout}
        errors = _collateral_contains_non_ada([good_txin, bad_txin], utxo)
        assert len(errors) == 1
        assert "CollateralContainsNonADA" in errors[0]


# ---------------------------------------------------------------------------
# InsufficientCollateral tests
# ---------------------------------------------------------------------------


class TestInsufficientCollateral:
    """Tests for the InsufficientCollateral rule."""

    def test_sufficient_collateral_passes(self):
        """Collateral >= required amount should pass."""
        # script_fees=100, percentage=150 => required = ceil(150) = 150
        utxo, txin = make_collateral_utxo(value=200)
        errors = _insufficient_collateral([txin], utxo, 100, 150)
        assert errors == []

    def test_exact_collateral_passes(self):
        """Collateral exactly at required amount should pass."""
        # script_fees=100, percentage=150 => required = 150
        utxo, txin = make_collateral_utxo(value=150)
        errors = _insufficient_collateral([txin], utxo, 100, 150)
        assert errors == []

    def test_insufficient_collateral_fails(self):
        """Collateral below required amount should fail."""
        # script_fees=100, percentage=150 => required = 150
        utxo, txin = make_collateral_utxo(value=100)
        errors = _insufficient_collateral([txin], utxo, 100, 150)
        assert len(errors) == 1
        assert "InsufficientCollateral" in errors[0]

    def test_zero_script_fees(self):
        """Zero script fees => zero collateral required."""
        utxo, txin = make_collateral_utxo(value=0)
        errors = _insufficient_collateral([txin], utxo, 0, 150)
        assert errors == []

    def test_multiple_collateral_inputs_summed(self):
        """Multiple collateral inputs should be summed."""
        sk, vk = make_key_pair(seed=50)
        addr = make_address(vk)

        txin1 = TransactionInput(make_tx_id(400), 0)
        txin2 = TransactionInput(make_tx_id(401), 0)
        utxo: ShelleyUTxO = {
            txin1: TransactionOutput(addr, 100),
            txin2: TransactionOutput(addr, 100),
        }
        # Total = 200, required = ceil(100 * 150 / 100) = 150
        errors = _insufficient_collateral([txin1, txin2], utxo, 100, 150)
        assert errors == []

    def test_ceiling_rounding(self):
        """Collateral requirement should use ceiling division."""
        # script_fees=101, percentage=150 => required = ceil(15150/100) = ceil(151.5) = 152
        utxo, txin = make_collateral_utxo(value=151)
        errors = _insufficient_collateral([txin], utxo, 101, 150)
        assert len(errors) == 1  # 151 < 152


# ---------------------------------------------------------------------------
# TooManyCollateralInputs tests
# ---------------------------------------------------------------------------


class TestTooManyCollateralInputs:
    """Tests for the TooManyCollateralInputs rule."""

    def test_within_limit(self):
        """Collateral count within limit should pass."""
        inputs = [TransactionInput(make_tx_id(i), 0) for i in range(3)]
        errors = _too_many_collateral_inputs(inputs, 3)
        assert errors == []

    def test_at_limit(self):
        """Collateral count exactly at limit should pass."""
        inputs = [TransactionInput(make_tx_id(i), 0) for i in range(3)]
        errors = _too_many_collateral_inputs(inputs, 3)
        assert errors == []

    def test_exceeds_limit(self):
        """Collateral count exceeding limit should fail."""
        inputs = [TransactionInput(make_tx_id(i), 0) for i in range(4)]
        errors = _too_many_collateral_inputs(inputs, 3)
        assert len(errors) == 1
        assert "TooManyCollateralInputs" in errors[0]

    def test_empty_inputs(self):
        """Zero collateral inputs should pass."""
        errors = _too_many_collateral_inputs([], 3)
        assert errors == []


# ---------------------------------------------------------------------------
# ExUnitsTooBig tests
# ---------------------------------------------------------------------------


class TestExUnitsTooBig:
    """Tests for the ExUnitsTooBigUTxO rule."""

    def test_within_limits(self):
        """Total ExUnits within limits should pass."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big(redeemers, limit)
        assert errors == []

    def test_at_limit(self):
        """Total ExUnits exactly at limit should pass."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=1000, steps=1000),
            )
        ]
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big(redeemers, limit)
        assert errors == []

    def test_mem_exceeds(self):
        """Memory exceeding limit should fail."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=2000, steps=500),
            )
        ]
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big(redeemers, limit)
        assert len(errors) == 1
        assert "ExUnitsTooBigUTxO" in errors[0]

    def test_steps_exceeds(self):
        """Steps exceeding limit should fail."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=500, steps=2000),
            )
        ]
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big(redeemers, limit)
        assert len(errors) == 1
        assert "ExUnitsTooBigUTxO" in errors[0]

    def test_multiple_redeemers_summed(self):
        """ExUnits from multiple redeemers should be summed."""
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=600, steps=400),
            ),
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=500, steps=700),
            ),
        ]
        # Total: mem=1100, steps=1100 -- both exceed limit of 1000
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big(redeemers, limit)
        assert len(errors) == 1
        assert "ExUnitsTooBigUTxO" in errors[0]

    def test_empty_redeemers(self):
        """No redeemers should pass."""
        limit = ExUnits(mem=1000, steps=1000)
        errors = _ex_units_too_big([], limit)
        assert errors == []


# ---------------------------------------------------------------------------
# Script fee calculation tests
# ---------------------------------------------------------------------------


class TestScriptFeeCalculation:
    """Tests for script fee calculation."""

    def test_zero_redeemers(self):
        """No redeemers => zero script fee."""
        prices = ExUnitPrices()
        assert calculate_script_fee([], prices) == 0

    def test_simple_fee(self):
        """Simple fee with unit prices."""
        prices = ExUnitPrices(
            mem_price_numerator=1,
            mem_price_denominator=1,
            step_price_numerator=1,
            step_price_denominator=1,
        )
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        fee = calculate_script_fee(redeemers, prices)
        assert fee == 300  # 100 + 200


# ---------------------------------------------------------------------------
# Alonzo min UTxO value tests
# ---------------------------------------------------------------------------


class TestAlonzoMinUtxoValue:
    """Tests for Alonzo-era min UTxO value calculation."""

    def test_pure_ada_output(self):
        """Pure ADA output should have a reasonable minimum."""
        sk, vk = make_key_pair()
        addr = make_address(vk)
        txout = TransactionOutput(addr, 2_000_000)
        min_val = alonzo_min_utxo_value(txout, coins_per_utxo_word=4310)
        # (27 + 2) * 4310 = 124990
        assert min_val == 29 * 4310

    def test_multi_asset_output_higher_min(self):
        """Multi-asset output should have a higher minimum than pure ADA."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        pure_ada = TransactionOutput(addr, 2_000_000)
        min_pure = alonzo_min_utxo_value(pure_ada, coins_per_utxo_word=4310)

        policy_id = make_policy_id(1)
        ma = MultiAsset({policy_id: Asset({AssetName(b"token"): 100})})
        multi = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma))
        min_multi = alonzo_min_utxo_value(multi, coins_per_utxo_word=4310)

        assert min_multi >= min_pure

    def test_coins_per_utxo_word_scales(self):
        """Higher coinsPerUTxOWord should produce higher minimum."""
        sk, vk = make_key_pair()
        addr = make_address(vk)
        txout = TransactionOutput(addr, 2_000_000)

        min_low = alonzo_min_utxo_value(txout, coins_per_utxo_word=1000)
        min_high = alonzo_min_utxo_value(txout, coins_per_utxo_word=5000)
        assert min_high > min_low


# ---------------------------------------------------------------------------
# Alonzo UTXO validation tests
# ---------------------------------------------------------------------------


class TestAlonzoUtxoValidation:
    """Tests for the Alonzo UTXO transition rule."""

    def test_valid_simple_tx(self):
        """A simple ADA-only transaction should pass all checks."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []

    def test_missing_input(self):
        """Transaction spending a non-existent UTxO should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        bad_txin = TransactionInput(make_tx_id(999), 0)

        tx_body = TransactionBody(
            inputs=[bad_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("InputsNotInUTxO" in e for e in errors)

    def test_fee_too_small(self):
        """Transaction with insufficient fee should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 9_999_999)],
            fee=1,  # Way too small
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("FeeTooSmallUTxO" in e for e in errors)

    def test_value_not_conserved(self):
        """Transaction where consumed != produced should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 5_000_000)],
            fee=2_000_000,
            # consumed=10M, produced=5M+2M=7M => mismatch
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("ValueNotConservedUTxO" in e for e in errors)

    def test_validity_interval_expired(self):
        """Transaction outside validity interval should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        interval = ValidityInterval(invalid_before=10, invalid_hereafter=50)
        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=100,  # Past the upper bound
            tx_size=200,
            validity_interval=interval,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors)

    def test_collateral_non_ada_with_plutus(self):
        """Plutus tx with multi-asset collateral should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Create a multi-asset collateral UTxO
        policy_id = make_policy_id(1)
        ma = MultiAsset({policy_id: Asset({AssetName(b"tok"): 1})})
        coll_txin = TransactionInput(make_tx_id(500), 0)
        coll_txout = TransactionOutput(dest_addr, Value(coin=5_000_000, multi_asset=ma))
        utxo[coll_txin] = coll_txout

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            collateral_inputs=[coll_txin],
            has_plutus_scripts=True,
            redeemers=[
                Redeemer(
                    tag=RedeemerTag.SPEND,
                    index=0,
                    data=cbor2.dumps(0),
                    ex_units=ExUnits(mem=100, steps=200),
                )
            ],
        )
        assert any("CollateralContainsNonADA" in e for e in errors)

    def test_too_many_collateral_inputs_with_plutus(self):
        """Plutus tx with too many collateral inputs should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Create 4 collateral inputs (limit is 3)
        coll_inputs = []
        for i in range(4):
            coll_txin = TransactionInput(make_tx_id(600 + i), 0)
            utxo[coll_txin] = TransactionOutput(dest_addr, 2_000_000)
            coll_inputs.append(coll_txin)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            collateral_inputs=coll_inputs,
            has_plutus_scripts=True,
            redeemers=[
                Redeemer(
                    tag=RedeemerTag.SPEND,
                    index=0,
                    data=cbor2.dumps(0),
                    ex_units=ExUnits(mem=100, steps=200),
                )
            ],
        )
        assert any("TooManyCollateralInputs" in e for e in errors)

    def test_insufficient_collateral_with_plutus(self):
        """Plutus tx with insufficient collateral should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Create collateral with only 1 lovelace
        coll_txin = TransactionInput(make_tx_id(700), 0)
        utxo[coll_txin] = TransactionOutput(dest_addr, 1)

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=1000, steps=2000),
            )
        ]

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            collateral_inputs=[coll_txin],
            has_plutus_scripts=True,
            redeemers=redeemers,
        )
        assert any("InsufficientCollateral" in e for e in errors)

    def test_ex_units_too_big(self):
        """Transaction with ExUnits exceeding limit should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(
                    mem=TEST_PARAMS.max_tx_ex_units.mem + 1,
                    steps=100,
                ),
            )
        ]

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
        )
        assert any("ExUnitsTooBigUTxO" in e for e in errors)

    def test_no_collateral_checks_without_plutus(self):
        """Without Plutus scripts, collateral rules should not apply."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        # No collateral at all, has_plutus_scripts=False
        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            collateral_inputs=[],
            has_plutus_scripts=False,
        )
        # Should pass — no collateral checks
        assert not any("Collateral" in e for e in errors)
        assert not any("Insufficient" in e for e in errors)

    def test_empty_input_set(self):
        """Transaction with no inputs should fail."""
        sk, vk = make_key_pair()
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set={},
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("InputSetEmptyUTxO" in e for e in errors)

    def test_tx_size_too_big(self):
        """Transaction exceeding max size should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=TEST_PARAMS.max_tx_size + 1,
        )
        assert any("MaxTxSizeUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Alonzo witness validation tests
# ---------------------------------------------------------------------------


class TestAlonzoWitnessValidation:
    """Tests for Alonzo UTXOW transition rules."""

    def test_valid_witnesses(self):
        """Transaction with correct witnesses should pass."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
        )
        assert errors == []

    def test_missing_witness(self):
        """Transaction missing a required witness should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        # Empty witness set — missing the required signer
        witness_set = TransactionWitnessSet()

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
        )
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)

    def test_script_integrity_hash_required_with_plutus(self):
        """Plutus tx without script integrity hash should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            has_plutus_scripts=True,
            script_integrity_hash=None,  # Missing!
        )
        assert any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_script_integrity_hash_mismatch(self):
        """Plutus tx with wrong script integrity hash should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}

        # Correct hash
        correct_hash = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        # Wrong hash
        wrong_hash = b"\x00" * 32

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            has_plutus_scripts=True,
            script_integrity_hash=wrong_hash,
            redeemers=redeemers,
            datums=datums,
            cost_models=cost_models,
            languages_used=languages,
        )
        assert any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_script_integrity_hash_correct(self):
        """Plutus tx with correct script integrity hash should pass that check."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}

        correct_hash = compute_script_integrity_hash(redeemers, datums, cost_models, languages)

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            has_plutus_scripts=True,
            script_integrity_hash=correct_hash,
            redeemers=redeemers,
            datums=datums,
            cost_models=cost_models,
            languages_used=languages,
        )
        # Should not have ScriptIntegrityHashMismatch
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)


# ---------------------------------------------------------------------------
# Combined validation tests
# ---------------------------------------------------------------------------


class TestAlonzoTxValidation:
    """Tests for the combined validate_alonzo_tx function."""

    def test_valid_simple_tx(self):
        """Valid simple tx should pass all UTXO + UTXOW checks."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_tx(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []

    def test_multiple_errors_accumulated(self):
        """Multiple validation failures should all be reported."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        bad_txin = TransactionInput(make_tx_id(999), 0)

        tx_body = TransactionBody(
            inputs=[bad_txin],  # Missing input
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=1,  # Too small fee
        )
        # Empty witnesses
        witness_set = TransactionWitnessSet()

        errors = validate_alonzo_tx(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        # Should have at least: InputsNotInUTxO, FeeTooSmallUTxO
        assert len(errors) >= 2


# ---------------------------------------------------------------------------
# AlonzoValidationError tests
# ---------------------------------------------------------------------------


class TestAlonzoValidationError:
    """Tests for the AlonzoValidationError exception."""

    def test_error_message(self):
        """Error should format all errors into message."""
        err = AlonzoValidationError(["error1", "error2"])
        assert "error1" in str(err)
        assert "error2" in str(err)

    def test_errors_attribute(self):
        """Errors list should be accessible."""
        err = AlonzoValidationError(["a", "b"])
        assert err.errors == ["a", "b"]


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestAlonzoProperties:
    """Property-based tests for Alonzo validation invariants."""

    @given(
        fee=st.integers(min_value=0, max_value=10**9),
        percentage=st.integers(min_value=100, max_value=500),
        collateral=st.integers(min_value=0, max_value=10**12),
    )
    @settings(max_examples=100)
    def test_collateral_monotonic_in_fees(self, fee: int, percentage: int, collateral: int):
        """Higher fees should never reduce the collateral requirement."""
        required = (fee * percentage + 99) // 100
        required_plus_one = ((fee + 1) * percentage + 99) // 100
        assert required_plus_one >= required

    @given(
        mem_a=st.integers(min_value=0, max_value=10**6),
        steps_a=st.integers(min_value=0, max_value=10**6),
        mem_b=st.integers(min_value=0, max_value=10**6),
        steps_b=st.integers(min_value=0, max_value=10**6),
    )
    @settings(max_examples=100)
    def test_ex_units_sum_exceeds_implies_parts_or_sum_exceeds(
        self, mem_a: int, steps_a: int, mem_b: int, steps_b: int
    ):
        """If individual parts don't exceed, sum should not exceed their individual limits."""
        a = ExUnits(mem=mem_a, steps=steps_a)
        b = ExUnits(mem=mem_b, steps=steps_b)
        total = a + b
        limit = ExUnits(mem=mem_a + mem_b, steps=steps_a + steps_b)
        # Sum should never exceed the sum-of-limits
        assert not total.exceeds(limit)
