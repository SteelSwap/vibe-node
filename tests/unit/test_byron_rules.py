"""Tests for Byron-era ledger validation rules.

Tests cover the UTXO transition rules from the Byron ledger formal spec:
    - Valid transaction passes all checks
    - Missing input detection
    - Double-spend detection
    - Insufficient fee rejection
    - Zero-value output rejection
    - Value preservation (outputs > inputs)
    - Full block application with multiple transactions
    - Minimum fee calculation

Spec references:
    - Byron ledger formal spec, Section 10 (UTXO transition)
    - ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/Validation.hs``
    - DB test specs: test_authorized_input_not_in_utxo,
      test_fee_extraction_from_tx, test_initial_ledger_state_utxo_empty
"""

from __future__ import annotations

import hashlib

import pytest
from pycardano.address import Address

from vibe.cardano.ledger.byron import (
    ByronTx,
    ByronTxAux,
    ByronTxId,
    ByronTxIn,
    ByronTxOut,
    ByronVKWitness,
)
from vibe.cardano.ledger.byron_rules import (
    BYRON_MAINNET_FEE_PARAMS,
    ByronFeeParams,
    ByronUTxO,
    ByronValidationError,
    apply_byron_block,
    apply_byron_tx,
    byron_min_fee,
    validate_byron_tx,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

BYRON_MAINNET_ADDR = "Ae2tdPwUPEZFRbyhz3cpfC2CumGzNkFBN2L42rcUc2yjQpEkxDbkPodpMAi"


def make_dummy_txid(seed: int = 0) -> ByronTxId:
    """Create a deterministic 32-byte TxId from a seed."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return ByronTxId(digest)


def make_byron_address() -> Address:
    """Return a decoded Byron mainnet address."""
    return Address.from_primitive(BYRON_MAINNET_ADDR)


def make_dummy_witness() -> ByronVKWitness:
    """Create a dummy VK witness (signature not verified in UTXO rules)."""
    return ByronVKWitness(
        verification_key=b"\x01" * 64,
        signature=b"\x02" * 64,
    )


def make_utxo_entry(
    tx_id_seed: int,
    index: int,
    value: int,
) -> tuple[tuple[bytes, int], ByronTxOut]:
    """Create a single UTxO entry for testing."""
    txid = make_dummy_txid(tx_id_seed)
    txout = ByronTxOut(address=make_byron_address(), value=value)
    return (txid.digest, index), txout


def make_valid_tx_aux(
    input_seed: int,
    input_index: int,
    input_value: int,
    output_value: int,
) -> tuple[ByronTxAux, ByronUTxO]:
    """Create a valid transaction and its required UTxO set.

    Returns (tx_aux, utxo_set) where the tx spends from a single UTxO
    entry with `input_value` and produces a single output with
    `output_value`. The fee is implicit: input_value - output_value.

    We use generous fee params to make most test txs valid by default.
    """
    txid = make_dummy_txid(input_seed)
    txin = ByronTxIn(tx_id=txid, index=input_index)
    txout = ByronTxOut(address=make_byron_address(), value=output_value)
    tx = ByronTx(inputs=[txin], outputs=[txout])
    tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

    utxo_set: ByronUTxO = {
        (txid.digest, input_index): ByronTxOut(address=make_byron_address(), value=input_value)
    }
    return tx_aux, utxo_set


# Use generous fee params for most tests so we don't accidentally
# fail on fee checks when testing other rules.
ZERO_FEE_PARAMS = ByronFeeParams(a=0, b_numerator=0, b_denominator=1)


# ---------------------------------------------------------------------------
# Minimum fee calculation tests
# ---------------------------------------------------------------------------


class TestByronMinFee:
    """Tests for byron_min_fee calculation.

    DB spec ref: test_fee_extraction_from_tx
    """

    def test_zero_size_returns_constant(self):
        """fee(0) = a."""
        fee = byron_min_fee(0, BYRON_MAINNET_FEE_PARAMS)
        assert fee == BYRON_MAINNET_FEE_PARAMS.a

    def test_mainnet_params_100_bytes(self):
        """fee(100) = 155381 + ceil(43946 * 100 / 1000) = 155381 + 4395."""
        fee = byron_min_fee(100, BYRON_MAINNET_FEE_PARAMS)
        # 43946 * 100 / 1000 = 4394.6 -> ceil = 4395
        assert fee == 155381 + 4395

    def test_mainnet_params_1000_bytes(self):
        """fee(1000) = 155381 + ceil(43946 * 1000 / 1000) = 155381 + 43946."""
        fee = byron_min_fee(1000, BYRON_MAINNET_FEE_PARAMS)
        assert fee == 155381 + 43946

    def test_custom_params(self):
        """Custom fee parameters."""
        params = ByronFeeParams(a=1000, b_numerator=500, b_denominator=100)
        fee = byron_min_fee(200, params)
        # 1000 + ceil(500 * 200 / 100) = 1000 + 1000 = 2000
        assert fee == 2000

    def test_zero_fee_params(self):
        """Zero fee parameters give zero fee."""
        fee = byron_min_fee(500, ZERO_FEE_PARAMS)
        assert fee == 0

    def test_negative_size_raises(self):
        """Negative tx size is invalid."""
        with pytest.raises(ValueError, match="non-negative"):
            byron_min_fee(-1)

    def test_ceiling_applied(self):
        """Variable component should be ceiled, not floored.

        Haskell ref: TxSizeLinear uses Rational arithmetic then
        ceiling for the final Lovelace value.
        """
        # b = 1/3 per byte, tx_size = 1 -> variable = ceil(1/3) = 1
        params = ByronFeeParams(a=0, b_numerator=1, b_denominator=3)
        assert byron_min_fee(1, params) == 1
        # tx_size = 2 -> ceil(2/3) = 1
        assert byron_min_fee(2, params) == 1
        # tx_size = 3 -> ceil(3/3) = 1
        assert byron_min_fee(3, params) == 1
        # tx_size = 4 -> ceil(4/3) = 2
        assert byron_min_fee(4, params) == 2


# ---------------------------------------------------------------------------
# Transaction validation tests
# ---------------------------------------------------------------------------


class TestValidateByronTx:
    """Tests for validate_byron_tx.

    DB spec refs:
        - test_authorized_input_not_in_utxo
        - test_initial_ledger_state_utxo_empty
    """

    def test_valid_transaction_passes(self):
        """A well-formed transaction with sufficient fee passes."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert errors == []

    def test_valid_transaction_with_real_fee_params(self):
        """Transaction with enough fee for mainnet params passes."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        # Fee = 9_000_000 which is way above any min fee
        errors = validate_byron_tx(tx_aux, utxo, BYRON_MAINNET_FEE_PARAMS)
        assert errors == []

    def test_missing_input_fails(self):
        """Spending a UTxO that doesn't exist must fail.

        DB spec: test_authorized_input_not_in_utxo
        """
        tx_aux, _ = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        # Empty UTxO set -- input won't be found
        errors = validate_byron_tx(tx_aux, {}, ZERO_FEE_PARAMS)
        assert len(errors) >= 1
        assert "Input not in UTxO" in errors[0]

    def test_double_spend_fails(self):
        """Duplicate inputs within a single transaction must fail."""
        txid = make_dummy_txid(0)
        txin = ByronTxIn(tx_id=txid, index=0)
        txout = ByronTxOut(address=make_byron_address(), value=500_000)

        # Create tx with the same input twice
        # ByronTx __post_init__ doesn't check for duplicate inputs,
        # that's the validation layer's job.
        tx = ByronTx.__new__(ByronTx)
        object.__setattr__(tx, "inputs", [txin, txin])
        object.__setattr__(tx, "outputs", [txout])
        object.__setattr__(tx, "attributes", {})

        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()] * 2)

        utxo: ByronUTxO = {
            (txid.digest, 0): ByronTxOut(address=make_byron_address(), value=1_000_000)
        }
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert any("Duplicate inputs" in e for e in errors)

    def test_insufficient_fee_fails(self):
        """Fee below minimum must fail."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=1_000_001,
            output_value=1_000_000,
        )
        # Implicit fee = 1 lovelace, way below mainnet minimum
        errors = validate_byron_tx(tx_aux, utxo, BYRON_MAINNET_FEE_PARAMS)
        assert len(errors) >= 1
        assert any("Insufficient fee" in e for e in errors)

    def test_zero_value_output_fails(self):
        """Output with value 0 must fail validation.

        Note: ByronTxOut allows 0 at the type level (only rejects negative),
        but the UTXO rules require strictly positive outputs.
        """
        txid = make_dummy_txid(0)
        txin = ByronTxIn(tx_id=txid, index=0)
        txout_zero = ByronTxOut(address=make_byron_address(), value=0)
        tx = ByronTx(inputs=[txin], outputs=[txout_zero])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

        utxo: ByronUTxO = {
            (txid.digest, 0): ByronTxOut(address=make_byron_address(), value=1_000_000)
        }
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert any("non-positive value" in e for e in errors)

    def test_value_not_preserved_fails(self):
        """Outputs exceeding inputs must fail."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=1_000_000,
            output_value=2_000_000,  # More than input!
        )
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert len(errors) >= 1
        assert any("Outputs exceed inputs" in e for e in errors)

    def test_multiple_errors_accumulated(self):
        """Validation should report all errors, not just the first."""
        txid_missing = make_dummy_txid(99)
        txin = ByronTxIn(tx_id=txid_missing, index=0)
        txout_zero = ByronTxOut(address=make_byron_address(), value=0)
        tx = ByronTx(inputs=[txin], outputs=[txout_zero])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

        # Missing input AND zero output
        errors = validate_byron_tx(tx_aux, {}, ZERO_FEE_PARAMS)
        assert len(errors) >= 2
        assert any("Input not in UTxO" in e for e in errors)
        assert any("non-positive value" in e for e in errors)


# ---------------------------------------------------------------------------
# UTxO application tests
# ---------------------------------------------------------------------------


class TestApplyByronTx:
    def test_apply_valid_tx_updates_utxo(self):
        """Applying a valid tx removes consumed UTxOs and adds produced ones."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        new_utxo = apply_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)

        # Old input should be gone
        old_key = (make_dummy_txid(0).digest, 0)
        assert old_key not in new_utxo

        # New output should exist (keyed by new tx_id)
        tx_id = ByronTxId.from_tx(tx_aux.tx)
        new_key = (tx_id.digest, 0)
        assert new_key in new_utxo
        assert new_utxo[new_key].value == 1_000_000

    def test_apply_invalid_tx_raises(self):
        """Applying an invalid tx raises ByronValidationError."""
        tx_aux, _ = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        with pytest.raises(ByronValidationError, match="Input not in UTxO"):
            apply_byron_tx(tx_aux, {}, ZERO_FEE_PARAMS)

    def test_apply_does_not_mutate_original(self):
        """apply_byron_tx must not modify the input UTxO dict."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        original_keys = set(utxo.keys())
        _ = apply_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert set(utxo.keys()) == original_keys

    def test_apply_preserves_unrelated_utxos(self):
        """UTxO entries not consumed by the tx survive."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        # Add an unrelated UTxO entry
        unrelated_key, unrelated_out = make_utxo_entry(tx_id_seed=99, index=0, value=5_000_000)
        utxo[unrelated_key] = unrelated_out

        new_utxo = apply_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert unrelated_key in new_utxo
        assert new_utxo[unrelated_key].value == 5_000_000


# ---------------------------------------------------------------------------
# Block application tests
# ---------------------------------------------------------------------------


class TestApplyByronBlock:
    def test_empty_block(self):
        """A block with no transactions returns the UTxO unchanged."""
        utxo: ByronUTxO = {}
        result = apply_byron_block([], utxo, ZERO_FEE_PARAMS)
        assert result == utxo

    def test_single_transaction_block(self):
        """Block with one valid transaction applies correctly."""
        tx_aux, utxo = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        new_utxo = apply_byron_block([tx_aux], utxo, ZERO_FEE_PARAMS)

        # Consumed input is gone
        old_key = (make_dummy_txid(0).digest, 0)
        assert old_key not in new_utxo

        # New output exists
        tx_id = ByronTxId.from_tx(tx_aux.tx)
        assert (tx_id.digest, 0) in new_utxo

    def test_multi_transaction_block_chained(self):
        """Block with chained transactions: tx2 spends tx1's output.

        This tests that transactions within a block see the UTxO
        modifications from prior transactions.
        """
        # TX1: Spend initial UTxO, produce output worth 5M
        txid0 = make_dummy_txid(0)
        txin1 = ByronTxIn(tx_id=txid0, index=0)
        txout1 = ByronTxOut(address=make_byron_address(), value=5_000_000)
        tx1 = ByronTx(inputs=[txin1], outputs=[txout1])
        tx1_aux = ByronTxAux(tx=tx1, witnesses=[make_dummy_witness()])
        tx1_id = ByronTxId.from_tx(tx1)

        # TX2: Spend TX1's output, produce output worth 3M
        txin2 = ByronTxIn(tx_id=tx1_id, index=0)
        txout2 = ByronTxOut(address=make_byron_address(), value=3_000_000)
        tx2 = ByronTx(inputs=[txin2], outputs=[txout2])
        tx2_aux = ByronTxAux(tx=tx2, witnesses=[make_dummy_witness()])
        tx2_id = ByronTxId.from_tx(tx2)

        # Initial UTxO: just the seed entry
        initial_utxo: ByronUTxO = {
            (txid0.digest, 0): ByronTxOut(address=make_byron_address(), value=10_000_000)
        }

        new_utxo = apply_byron_block([tx1_aux, tx2_aux], initial_utxo, ZERO_FEE_PARAMS)

        # Original input consumed
        assert (txid0.digest, 0) not in new_utxo
        # TX1 output consumed by TX2
        assert (tx1_id.digest, 0) not in new_utxo
        # TX2 output remains
        assert (tx2_id.digest, 0) in new_utxo
        assert new_utxo[(tx2_id.digest, 0)].value == 3_000_000

    def test_block_with_invalid_tx_raises(self):
        """A block containing an invalid transaction raises with tx index."""
        tx_aux, _ = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        with pytest.raises(ByronValidationError, match="Transaction 0"):
            apply_byron_block([tx_aux], {}, ZERO_FEE_PARAMS)

    def test_block_multiple_independent_txs(self):
        """Block with multiple independent transactions (no chaining)."""
        # Create two independent UTxO entries and two txs spending them
        utxo: ByronUTxO = {}
        txs: list[ByronTxAux] = []

        for seed in range(3):
            txid = make_dummy_txid(seed)
            utxo[(txid.digest, 0)] = ByronTxOut(address=make_byron_address(), value=10_000_000)
            txin = ByronTxIn(tx_id=txid, index=0)
            txout = ByronTxOut(address=make_byron_address(), value=5_000_000)
            tx = ByronTx(inputs=[txin], outputs=[txout])
            txs.append(ByronTxAux(tx=tx, witnesses=[make_dummy_witness()]))

        new_utxo = apply_byron_block(txs, utxo, ZERO_FEE_PARAMS)

        # All original entries consumed
        for seed in range(3):
            txid = make_dummy_txid(seed)
            assert (txid.digest, 0) not in new_utxo

        # Three new outputs created
        assert len(new_utxo) == 3


# ---------------------------------------------------------------------------
# ByronValidationError tests
# ---------------------------------------------------------------------------


class TestByronValidationError:
    def test_error_message_contains_all_errors(self):
        err = ByronValidationError(["error1", "error2"])
        assert "error1" in str(err)
        assert "error2" in str(err)

    def test_errors_attribute(self):
        err = ByronValidationError(["foo", "bar"])
        assert err.errors == ["foo", "bar"]


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_tx_with_multiple_outputs(self):
        """Transaction splitting value into multiple outputs."""
        txid = make_dummy_txid(0)
        txin = ByronTxIn(tx_id=txid, index=0)
        addr = make_byron_address()
        txout1 = ByronTxOut(address=addr, value=3_000_000)
        txout2 = ByronTxOut(address=addr, value=4_000_000)
        tx = ByronTx(inputs=[txin], outputs=[txout1, txout2])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

        utxo: ByronUTxO = {(txid.digest, 0): ByronTxOut(address=addr, value=10_000_000)}
        # Fee = 10M - 7M = 3M (more than enough for zero fee params)
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert errors == []

        new_utxo = apply_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        tx_id = ByronTxId.from_tx(tx)
        assert (tx_id.digest, 0) in new_utxo
        assert (tx_id.digest, 1) in new_utxo
        assert new_utxo[(tx_id.digest, 0)].value == 3_000_000
        assert new_utxo[(tx_id.digest, 1)].value == 4_000_000

    def test_tx_with_multiple_inputs(self):
        """Transaction consuming multiple UTxO entries."""
        txid0 = make_dummy_txid(0)
        txid1 = make_dummy_txid(1)
        txin0 = ByronTxIn(tx_id=txid0, index=0)
        txin1 = ByronTxIn(tx_id=txid1, index=0)
        txout = ByronTxOut(address=make_byron_address(), value=15_000_000)
        tx = ByronTx(inputs=[txin0, txin1], outputs=[txout])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()] * 2)

        utxo: ByronUTxO = {
            (txid0.digest, 0): ByronTxOut(address=make_byron_address(), value=10_000_000),
            (txid1.digest, 0): ByronTxOut(address=make_byron_address(), value=10_000_000),
        }
        # Fee = 20M - 15M = 5M
        errors = validate_byron_tx(tx_aux, utxo, ZERO_FEE_PARAMS)
        assert errors == []

    def test_exact_fee_passes(self):
        """Transaction with fee exactly at minimum should pass."""
        # Build a tx, compute its size, then set up UTxO with exact amounts
        txid = make_dummy_txid(0)
        txin = ByronTxIn(tx_id=txid, index=0)
        txout = ByronTxOut(address=make_byron_address(), value=1_000_000)
        tx = ByronTx(inputs=[txin], outputs=[txout])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

        tx_size = len(tx_aux.to_cbor())
        min_fee = byron_min_fee(tx_size, BYRON_MAINNET_FEE_PARAMS)

        # Set input value = output + exact min fee
        utxo: ByronUTxO = {
            (txid.digest, 0): ByronTxOut(
                address=make_byron_address(),
                value=1_000_000 + min_fee,
            )
        }
        errors = validate_byron_tx(tx_aux, utxo, BYRON_MAINNET_FEE_PARAMS)
        assert errors == []

    def test_fee_one_below_minimum_fails(self):
        """Transaction with fee one lovelace below minimum must fail."""
        txid = make_dummy_txid(0)
        txin = ByronTxIn(tx_id=txid, index=0)
        txout = ByronTxOut(address=make_byron_address(), value=1_000_000)
        tx = ByronTx(inputs=[txin], outputs=[txout])
        tx_aux = ByronTxAux(tx=tx, witnesses=[make_dummy_witness()])

        tx_size = len(tx_aux.to_cbor())
        min_fee = byron_min_fee(tx_size, BYRON_MAINNET_FEE_PARAMS)

        # Set input value = output + min_fee - 1
        utxo: ByronUTxO = {
            (txid.digest, 0): ByronTxOut(
                address=make_byron_address(),
                value=1_000_000 + min_fee - 1,
            )
        }
        errors = validate_byron_tx(tx_aux, utxo, BYRON_MAINNET_FEE_PARAMS)
        assert any("Insufficient fee" in e for e in errors)

    def test_initial_utxo_empty(self):
        """Empty UTxO set should reject any transaction.

        DB spec: test_initial_ledger_state_utxo_empty
        """
        tx_aux, _ = make_valid_tx_aux(
            input_seed=0,
            input_index=0,
            input_value=10_000_000,
            output_value=1_000_000,
        )
        errors = validate_byron_tx(tx_aux, {}, ZERO_FEE_PARAMS)
        assert len(errors) >= 1
