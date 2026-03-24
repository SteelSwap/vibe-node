"""Tests for Babbage-era ledger validation rules (UTXO + UTXOW).

Tests cover the Babbage UTXO and UTXOW transition rules:
    - Reference inputs must exist in UTxO set
    - Inline datum validation (well-formedness)
    - Reference script resolution
    - Collateral return + total_collateral validation
    - Min UTxO with coinsPerUTxOByte
    - Inherited Alonzo/Shelley rules
    - Combined validation (validate_babbage_tx)
    - Hypothesis property tests

Spec references:
    - Babbage ledger formal spec, Section 4 (UTxO transition)
    - Babbage ledger formal spec, Section 5 (UTXOW)
    - ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/Rules/Utxo.hs``
    - ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/Rules/Utxow.hs``
"""

from __future__ import annotations

import hashlib

from hypothesis import given, settings
from hypothesis import strategies as st
from pycardano import (
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)
from pycardano.address import Address
from pycardano.hash import TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.ledger.alonzo_types import ExUnitPrices, ExUnits
from vibe.cardano.ledger.babbage import (
    BabbageValidationError,
    _reference_inputs_not_in_utxo,
    _validate_collateral_return,
    _validate_inline_datums,
    babbage_min_utxo,
    estimate_output_size,
    resolve_reference_scripts,
    validate_babbage_tx,
    validate_babbage_utxo,
)
from vibe.cardano.ledger.babbage_types import (
    BabbageOutputExtension,
    BabbageProtocolParams,
    DatumOption,
    DatumOptionTag,
    ReferenceScript,
)
from vibe.cardano.ledger.shelley import ShelleyUTxO

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


TEST_PARAMS = BabbageProtocolParams(
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
    coins_per_utxo_byte=4310,
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


# ---------------------------------------------------------------------------
# Babbage min UTxO tests
# ---------------------------------------------------------------------------


class TestBabbageMinUtxo:
    """Tests for Babbage-era min UTxO value calculation (coinsPerUTxOByte)."""

    def test_small_output(self):
        """Small output should have min based on overhead + size."""
        # 160 byte overhead + 60 byte output = 220 bytes * 4310
        min_val = babbage_min_utxo(60, coins_per_utxo_byte=4310)
        assert min_val == (160 + 60) * 4310

    def test_larger_output(self):
        """Larger output should have proportionally higher min."""
        min_small = babbage_min_utxo(60, coins_per_utxo_byte=4310)
        min_large = babbage_min_utxo(200, coins_per_utxo_byte=4310)
        assert min_large > min_small

    def test_coins_per_byte_scales(self):
        """Higher coinsPerUTxOByte should produce higher minimum."""
        min_low = babbage_min_utxo(100, coins_per_utxo_byte=1000)
        min_high = babbage_min_utxo(100, coins_per_utxo_byte=5000)
        assert min_high > min_low

    def test_zero_size_output(self):
        """Zero-size output should still have the overhead cost."""
        min_val = babbage_min_utxo(0, coins_per_utxo_byte=4310)
        assert min_val == 160 * 4310


class TestEstimateOutputSize:
    """Tests for output size estimation."""

    def test_pure_ada_output(self):
        """Pure ADA output should have a reasonable size estimate."""
        sk, vk = make_key_pair()
        addr = make_address(vk)
        txout = TransactionOutput(addr, 2_000_000)
        size = estimate_output_size(txout)
        assert 60 < size < 200

    def test_multi_asset_output_larger(self):
        """Multi-asset output should be estimated as larger."""
        from pycardano import Asset, AssetName, MultiAsset
        from pycardano.hash import ScriptHash

        sk, vk = make_key_pair()
        addr = make_address(vk)

        pure = TransactionOutput(addr, 2_000_000)
        size_pure = estimate_output_size(pure)

        pid = ScriptHash(hashlib.blake2b(b"policy", digest_size=28).digest())
        ma = MultiAsset({pid: Asset({AssetName(b"token"): 100})})
        multi = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma))
        size_multi = estimate_output_size(multi)

        assert size_multi > size_pure


# ---------------------------------------------------------------------------
# Reference inputs tests
# ---------------------------------------------------------------------------


class TestReferenceInputsNotInUtxo:
    """Tests for the ReferenceInputsNotInUTxO rule."""

    def test_existing_ref_inputs_pass(self):
        """Reference inputs that exist in UTxO should pass."""
        utxo, txin, sk, vk = make_simple_utxo()
        errors = _reference_inputs_not_in_utxo([txin], utxo)
        assert errors == []

    def test_missing_ref_input_fails(self):
        """Reference input not in UTxO should fail."""
        bad_txin = TransactionInput(make_tx_id(999), 0)
        errors = _reference_inputs_not_in_utxo([bad_txin], {})
        assert len(errors) == 1
        assert "ReferenceInputsNotInUTxO" in errors[0]

    def test_empty_ref_inputs_pass(self):
        """No reference inputs should produce no errors."""
        errors = _reference_inputs_not_in_utxo([], {})
        assert errors == []

    def test_multiple_ref_inputs_partial_missing(self):
        """Only missing reference inputs should be reported."""
        utxo, txin, sk, vk = make_simple_utxo()
        bad_txin = TransactionInput(make_tx_id(999), 0)
        errors = _reference_inputs_not_in_utxo([txin, bad_txin], utxo)
        assert len(errors) == 1
        assert "ReferenceInputsNotInUTxO" in errors[0]


# ---------------------------------------------------------------------------
# Collateral return tests
# ---------------------------------------------------------------------------


class TestCollateralReturn:
    """Tests for collateral return + total_collateral validation."""

    def test_correct_total_with_return(self):
        """Correct total_collateral with return should pass."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        txin = TransactionInput(make_tx_id(100), 0)
        utxo: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        return_out = TransactionOutput(addr, 2_000_000)
        # total = 5M - 2M = 3M
        errors = _validate_collateral_return([txin], utxo, return_out, 3_000_000)
        assert errors == []

    def test_incorrect_total_with_return(self):
        """Wrong total_collateral with return should fail."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        txin = TransactionInput(make_tx_id(100), 0)
        utxo: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        return_out = TransactionOutput(addr, 2_000_000)
        # total should be 3M but we claim 4M
        errors = _validate_collateral_return([txin], utxo, return_out, 4_000_000)
        assert len(errors) == 1
        assert "IncorrectTotalCollateralField" in errors[0]

    def test_total_without_return(self):
        """total_collateral without return must equal collateral sum."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        txin = TransactionInput(make_tx_id(100), 0)
        utxo: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        # Correct: total = 5M, no return
        errors = _validate_collateral_return([txin], utxo, None, 5_000_000)
        assert errors == []

    def test_total_without_return_mismatch(self):
        """total_collateral != collateral_sum without return should fail."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        txin = TransactionInput(make_tx_id(100), 0)
        utxo: ShelleyUTxO = {txin: TransactionOutput(addr, 5_000_000)}

        errors = _validate_collateral_return([txin], utxo, None, 3_000_000)
        assert len(errors) == 1
        assert "IncorrectTotalCollateralField" in errors[0]

    def test_no_total_no_return(self):
        """No total_collateral and no return should pass (both None)."""
        errors = _validate_collateral_return([], {}, None, None)
        assert errors == []


# ---------------------------------------------------------------------------
# Inline datum validation tests
# ---------------------------------------------------------------------------


class TestInlineDatumValidation:
    """Tests for inline datum validation."""

    def test_valid_inline_datum(self):
        """Well-formed inline datum should pass."""
        ext = {
            0: BabbageOutputExtension(
                datum_option=DatumOption(
                    tag=DatumOptionTag.INLINE,
                    data=b"\xa1\x01\x02",  # some CBOR data
                )
            )
        }
        errors = _validate_inline_datums(ext)
        assert errors == []

    def test_empty_inline_datum_fails(self):
        """Empty inline datum data should fail."""
        ext = {
            0: BabbageOutputExtension(
                datum_option=DatumOption(
                    tag=DatumOptionTag.INLINE,
                    data=b"",
                )
            )
        }
        errors = _validate_inline_datums(ext)
        assert len(errors) == 1
        assert "InlineDatumEmpty" in errors[0]

    def test_valid_datum_hash(self):
        """32-byte datum hash should pass."""
        ext = {
            0: BabbageOutputExtension(
                datum_option=DatumOption(
                    tag=DatumOptionTag.HASH,
                    data=b"\x00" * 32,
                )
            )
        }
        errors = _validate_inline_datums(ext)
        assert errors == []

    def test_wrong_size_datum_hash(self):
        """Non-32-byte datum hash should fail."""
        ext = {
            0: BabbageOutputExtension(
                datum_option=DatumOption(
                    tag=DatumOptionTag.HASH,
                    data=b"\x00" * 16,
                )
            )
        }
        errors = _validate_inline_datums(ext)
        assert len(errors) == 1
        assert "DatumHashWrongSize" in errors[0]

    def test_no_extensions(self):
        """No output extensions should produce no errors."""
        errors = _validate_inline_datums(None)
        assert errors == []

    def test_no_datum_option(self):
        """Extension without datum_option should produce no errors."""
        ext = {0: BabbageOutputExtension()}
        errors = _validate_inline_datums(ext)
        assert errors == []


# ---------------------------------------------------------------------------
# Reference script resolution tests
# ---------------------------------------------------------------------------


class TestReferenceScriptResolution:
    """Tests for reference script resolution from UTxO set."""

    def test_resolve_from_extensions(self):
        """Should resolve reference scripts from output extensions."""
        script_hash = hashlib.blake2b(b"script1", digest_size=28).digest()
        ref_script = ReferenceScript(
            script_bytes=b"\x01\x02\x03",
            script_hash=script_hash,
        )

        txin = TransactionInput(make_tx_id(1), 0)
        extensions = {
            txin: BabbageOutputExtension(reference_script=ref_script),
        }

        result = resolve_reference_scripts([txin], {}, extensions)
        assert script_hash in result
        assert result[script_hash].script_bytes == b"\x01\x02\x03"

    def test_no_extensions_returns_empty(self):
        """No extensions should return empty dict."""
        txin = TransactionInput(make_tx_id(1), 0)
        result = resolve_reference_scripts([txin], {}, None)
        assert result == {}

    def test_extension_without_script(self):
        """Extension without reference_script should not be included."""
        txin = TransactionInput(make_tx_id(1), 0)
        extensions = {
            txin: BabbageOutputExtension(),  # No script
        }
        result = resolve_reference_scripts([txin], {}, extensions)
        assert result == {}


# ---------------------------------------------------------------------------
# Babbage UTXO validation tests
# ---------------------------------------------------------------------------


class TestBabbageUtxoValidation:
    """Tests for the Babbage UTXO transition rule."""

    def test_valid_simple_tx(self):
        """A simple ADA-only transaction should pass all checks."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []

    def test_missing_reference_input(self):
        """Reference input not in UTxO should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        bad_ref = TransactionInput(make_tx_id(999), 0)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            reference_inputs=[bad_ref],
        )
        assert any("ReferenceInputsNotInUTxO" in e for e in errors)

    def test_valid_reference_input(self):
        """Reference input that exists should pass."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Add another UTxO for reference
        ref_txin = TransactionInput(make_tx_id(42), 0)
        utxo[ref_txin] = TransactionOutput(dest_addr, 2_000_000)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            reference_inputs=[ref_txin],
        )
        assert not any("ReferenceInputsNotInUTxO" in e for e in errors)

    def test_value_not_conserved(self):
        """Transaction where consumed != produced should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 5_000_000)],
            fee=2_000_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("ValueNotConservedUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Combined validation tests
# ---------------------------------------------------------------------------


class TestBabbageTxValidation:
    """Tests for the combined validate_babbage_tx function."""

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

        errors = validate_babbage_tx(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert errors == []


# ---------------------------------------------------------------------------
# BabbageValidationError tests
# ---------------------------------------------------------------------------


class TestBabbageValidationError:
    """Tests for the BabbageValidationError exception."""

    def test_error_message(self):
        """Error should format all errors into message."""
        err = BabbageValidationError(["error1", "error2"])
        assert "error1" in str(err)
        assert "error2" in str(err)

    def test_errors_attribute(self):
        """Errors list should be accessible."""
        err = BabbageValidationError(["a", "b"])
        assert err.errors == ["a", "b"]


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestBabbageProperties:
    """Property-based tests for Babbage validation invariants."""

    @given(
        size=st.integers(min_value=0, max_value=10000),
        cpb=st.integers(min_value=1, max_value=100000),
    )
    @settings(max_examples=100)
    def test_min_utxo_monotonic_in_size(self, size: int, cpb: int):
        """Larger outputs should never have a lower min UTxO requirement."""
        min_small = babbage_min_utxo(size, cpb)
        min_larger = babbage_min_utxo(size + 1, cpb)
        assert min_larger >= min_small

    @given(
        size=st.integers(min_value=0, max_value=10000),
        cpb=st.integers(min_value=1, max_value=100000),
    )
    @settings(max_examples=100)
    def test_min_utxo_monotonic_in_cpb(self, size: int, cpb: int):
        """Higher coinsPerUTxOByte should never decrease min UTxO."""
        min_low = babbage_min_utxo(size, cpb)
        min_high = babbage_min_utxo(size, cpb + 1)
        assert min_high >= min_low

    @given(
        size=st.integers(min_value=0, max_value=10000),
        cpb=st.integers(min_value=1, max_value=100000),
    )
    @settings(max_examples=100)
    def test_min_utxo_always_positive(self, size: int, cpb: int):
        """Min UTxO should always be positive for positive coinsPerUTxOByte."""
        min_val = babbage_min_utxo(size, cpb)
        assert min_val > 0
