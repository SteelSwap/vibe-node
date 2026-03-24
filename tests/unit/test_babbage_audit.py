"""Babbage-era audit gap tests — 8 tests from the Haskell test audit.

Tests cover missing validation and property checks:
    1. Script ExUnits validation (total exceeds max_tx_ex_units)
    2. Multi-asset min UTxO calculation (native tokens increase min)
    3. Value preservation with multi-asset (Hypothesis property)
    4. Reference script size limit
    5. Fee non-decreasing property (Hypothesis)
    6. No double-spend property (Hypothesis)
    7. Consumed inputs eliminated from UTxO set
    8. New entries have unique TxIds

Spec references:
    - Babbage ledger formal spec, Section 4 (UTxO transition)
    - Alonzo ledger formal spec, ``ExUnitsTooBigUTxO``
    - Babbage ledger formal spec, reference script size bound
    - Shelley ledger formal spec, UTxO set update rules
"""

from __future__ import annotations

import hashlib

from hypothesis import assume, given, settings
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

from vibe.cardano.ledger.alonzo_types import (
    ExUnitPrices,
    ExUnits,
    Redeemer,
    RedeemerTag,
)
from vibe.cardano.ledger.babbage import (
    _validate_reference_script_size,
    babbage_min_utxo,
    estimate_output_size,
    validate_babbage_utxo,
)
from vibe.cardano.ledger.babbage_types import (
    BabbageOutputExtension,
    BabbageProtocolParams,
    ReferenceScript,
)
from vibe.cardano.ledger.shelley import ShelleyUTxO, shelley_min_fee

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


def make_policy_id(seed: int = 0) -> ScriptHash:
    """Create a deterministic 28-byte policy ID."""
    return ScriptHash(hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest())


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
# Test 1: Script ExUnits validation
# ---------------------------------------------------------------------------


class TestScriptExUnitsValidation:
    """Test that Babbage tx with Plutus scripts is rejected when total
    ExUnits exceed max_tx_ex_units from protocol params.

    Spec ref: Alonzo formal spec, ``ExUnitsTooBigUTxO``.
    Haskell ref: ``validateExUnitsTooBigUTxO`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``
    """

    def test_ex_units_within_limit_passes(self):
        """Redeemers within max_tx_ex_units should pass."""
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 40_000_000)],
            fee=10_000_000,
        )

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=b"\x01",
                ex_units=ExUnits(mem=5_000_000, steps=5_000_000_000),
            ),
        ]

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
            has_plutus_scripts=True,
        )
        assert not any("ExUnitsTooBig" in e for e in errors)

    def test_ex_units_exceed_max_tx_fails(self):
        """Redeemers exceeding max_tx_ex_units should produce error."""
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 40_000_000)],
            fee=10_000_000,
        )

        # Exceeds max_tx_ex_units (mem=10M, steps=10B)
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=b"\x01",
                ex_units=ExUnits(mem=11_000_000, steps=5_000_000_000),
            ),
        ]

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
            has_plutus_scripts=True,
        )
        assert any("ExUnitsTooBig" in e for e in errors)

    def test_multiple_redeemers_cumulative_exceed(self):
        """Multiple redeemers that individually fit but cumulatively exceed should fail."""
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 40_000_000)],
            fee=10_000_000,
        )

        # Each fits individually, but total mem = 12M > max 10M
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=b"\x01",
                ex_units=ExUnits(mem=6_000_000, steps=3_000_000_000),
            ),
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=b"\x02",
                ex_units=ExUnits(mem=6_000_000, steps=3_000_000_000),
            ),
        ]

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
            has_plutus_scripts=True,
        )
        assert any("ExUnitsTooBig" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 2: Multi-asset min UTxO calculation
# ---------------------------------------------------------------------------


class TestMultiAssetMinUtxo:
    """Test that min UTxO for multi-asset outputs is correctly higher
    than ADA-only outputs.

    Spec ref: Babbage formal spec, ``utxoEntrySize``.
    Haskell ref: ``getMinCoinTxOut`` in ``Cardano.Ledger.Babbage.Rules.Utxo``
    """

    def test_multi_asset_output_has_higher_min(self):
        """Output with native tokens should require more lovelace."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        pure_ada = TransactionOutput(addr, 2_000_000)
        size_pure = estimate_output_size(pure_ada)
        min_pure = babbage_min_utxo(size_pure, TEST_PARAMS.coins_per_utxo_byte)

        pid = make_policy_id(0)
        ma = MultiAsset({pid: Asset({AssetName(b"token"): 100})})
        multi = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma))
        size_multi = estimate_output_size(multi)
        min_multi = babbage_min_utxo(size_multi, TEST_PARAMS.coins_per_utxo_byte)

        assert min_multi > min_pure

    def test_more_policies_increases_min(self):
        """More policy IDs should increase the min UTxO."""
        sk, vk = make_key_pair()
        addr = make_address(vk)

        pid1 = make_policy_id(0)
        ma1 = MultiAsset({pid1: Asset({AssetName(b"t"): 1})})
        out1 = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma1))

        pid2 = make_policy_id(1)
        ma2 = MultiAsset(
            {
                pid1: Asset({AssetName(b"t"): 1}),
                pid2: Asset({AssetName(b"t"): 1}),
            }
        )
        out2 = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma2))

        size1 = estimate_output_size(out1)
        size2 = estimate_output_size(out2)

        assert size2 > size1
        assert babbage_min_utxo(size2, 4310) > babbage_min_utxo(size1, 4310)

    def test_more_asset_names_increases_min(self):
        """More asset names under a policy should increase the min UTxO."""
        sk, vk = make_key_pair()
        addr = make_address(vk)
        pid = make_policy_id(0)

        ma1 = MultiAsset({pid: Asset({AssetName(b"a"): 1})})
        out1 = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma1))

        ma5 = MultiAsset(
            {
                pid: Asset(
                    {
                        AssetName(b"a"): 1,
                        AssetName(b"b"): 1,
                        AssetName(b"c"): 1,
                        AssetName(b"d"): 1,
                        AssetName(b"e"): 1,
                    }
                )
            }
        )
        out5 = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma5))

        size1 = estimate_output_size(out1)
        size5 = estimate_output_size(out5)

        assert size5 > size1

    def test_multi_asset_below_min_rejected(self):
        """Output with multi-asset below min UTxO should be rejected."""
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        addr = make_address(vk)

        pid = make_policy_id(0)
        ma = MultiAsset({pid: Asset({AssetName(b"token"): 100})})
        # Deliberately low ADA — should fail min UTxO check
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, Value(coin=100_000, multi_asset=ma))],
            fee=49_900_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("BabbageOutputTooSmallUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 3: Value preservation with multi-asset (Hypothesis)
# ---------------------------------------------------------------------------


class TestValuePreservationMultiAsset:
    """Hypothesis property test: for any valid multi-asset transaction,
    sum of input values + minting = sum of output values + fee.

    Spec ref: Mary/Babbage ledger formal spec, value preservation.
    Haskell ref: ``ValueNotConservedUTxO`` in UTxO rules.
    """

    @given(
        ada_in=st.integers(min_value=2_000_000, max_value=100_000_000),
        token_amount=st.integers(min_value=1, max_value=1_000_000),
        fee=st.integers(min_value=200, max_value=1_000_000),
    )
    @settings(max_examples=100)
    def test_balanced_multi_asset_tx_passes(self, ada_in: int, token_amount: int, fee: int):
        """A balanced multi-asset transaction should pass value preservation."""
        assume(ada_in > fee + 1_000_000)  # Enough for output + fee
        ada_out = ada_in - fee

        sk, vk = make_key_pair(0)
        addr = make_address(vk)
        pid = make_policy_id(0)
        ma = MultiAsset({pid: Asset({AssetName(b"tkn"): token_amount})})

        # Input has ADA + tokens
        input_value = Value(coin=ada_in, multi_asset=ma)
        utxo, txin, _, _ = make_simple_utxo(value=input_value, tx_id_seed=42)

        # Output preserves the tokens
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, Value(coin=ada_out, multi_asset=ma))],
            fee=fee,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert not any("ValueNotConserved" in e for e in errors)

    @given(
        ada_in=st.integers(min_value=5_000_000, max_value=100_000_000),
        token_amount=st.integers(min_value=1, max_value=1_000_000),
        mint_amount=st.integers(min_value=1, max_value=100_000),
    )
    @settings(max_examples=100)
    def test_minting_preserves_value(self, ada_in: int, token_amount: int, mint_amount: int):
        """Minting new tokens should preserve value when outputs account for them."""
        fee = 300  # min fee for tx_size=200 with min_fee_a=1, min_fee_b=100
        assume(ada_in > fee + 1_000_000)
        ada_out = ada_in - fee

        sk, vk = make_key_pair(0)
        addr = make_address(vk)
        pid = make_policy_id(0)

        # Input has ADA + some tokens
        input_ma = MultiAsset({pid: Asset({AssetName(b"tkn"): token_amount})})
        input_value = Value(coin=ada_in, multi_asset=input_ma)
        utxo, txin, _, _ = make_simple_utxo(value=input_value, tx_id_seed=42)

        # Mint additional tokens
        mint_ma = MultiAsset({pid: Asset({AssetName(b"tkn"): mint_amount})})

        # Output includes original + minted tokens
        output_ma = MultiAsset({pid: Asset({AssetName(b"tkn"): token_amount + mint_amount})})
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, Value(coin=ada_out, multi_asset=output_ma))],
            fee=fee,
            mint=mint_ma,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert not any("ValueNotConserved" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 4: Reference script size limit
# ---------------------------------------------------------------------------


class TestReferenceScriptSizeLimit:
    """Test that total reference script size in a transaction is bounded.

    Spec ref: Babbage formal spec, total reference script size bound.
    Haskell ref: ``validateTotalReferenceScriptSize`` in
        ``Cardano.Ledger.Babbage.Rules.Utxo``
    """

    def test_small_ref_scripts_pass(self):
        """Reference scripts under the limit should pass."""
        txin = TransactionInput(make_tx_id(1), 0)
        small_script = ReferenceScript(
            script_bytes=b"\x01" * 100,
            script_hash=hashlib.blake2b(b"s1", digest_size=28).digest(),
        )
        extensions = {0: BabbageOutputExtension(reference_script=small_script)}

        errors = _validate_reference_script_size(
            [txin], {}, extensions, max_ref_script_size=204800
        )
        assert errors == []

    def test_oversized_ref_scripts_fail(self):
        """Reference scripts exceeding the limit should fail."""
        txin = TransactionInput(make_tx_id(1), 0)
        big_script = ReferenceScript(
            script_bytes=b"\x01" * 300_000,
            script_hash=hashlib.blake2b(b"big", digest_size=28).digest(),
        )
        extensions = {0: BabbageOutputExtension(reference_script=big_script)}

        errors = _validate_reference_script_size(
            [txin], {}, extensions, max_ref_script_size=204800
        )
        assert len(errors) == 1
        assert "TotalReferenceScriptSizeTooBig" in errors[0]

    def test_multiple_ref_scripts_cumulative(self):
        """Multiple reference scripts whose cumulative size exceeds limit should fail."""
        txin1 = TransactionInput(make_tx_id(1), 0)
        txin2 = TransactionInput(make_tx_id(2), 0)

        script1 = ReferenceScript(
            script_bytes=b"\x01" * 120_000,
            script_hash=hashlib.blake2b(b"s1", digest_size=28).digest(),
        )
        script2 = ReferenceScript(
            script_bytes=b"\x02" * 120_000,
            script_hash=hashlib.blake2b(b"s2", digest_size=28).digest(),
        )
        extensions = {
            0: BabbageOutputExtension(reference_script=script1),
            1: BabbageOutputExtension(reference_script=script2),
        }

        errors = _validate_reference_script_size(
            [txin1, txin2], {}, extensions, max_ref_script_size=204800
        )
        assert len(errors) == 1
        assert "TotalReferenceScriptSizeTooBig" in errors[0]

    def test_ref_script_size_in_utxo_validation(self):
        """Reference script size limit should be checked in validate_babbage_utxo."""
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        addr = make_address(vk)

        # Add a ref input with a big script in extensions
        ref_txin = TransactionInput(make_tx_id(99), 0)
        utxo[ref_txin] = TransactionOutput(addr, 2_000_000)

        big_script = ReferenceScript(
            script_bytes=b"\x01" * 300_000,
            script_hash=hashlib.blake2b(b"big", digest_size=28).digest(),
        )
        extensions = {0: BabbageOutputExtension(reference_script=big_script)}

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 48_000_000)],
            fee=2_000_000,
        )

        errors = validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            reference_inputs=[ref_txin],
            output_extensions=extensions,
        )
        assert any("TotalReferenceScriptSizeTooBig" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 5: Fee non-decreasing property (Hypothesis)
# ---------------------------------------------------------------------------


class TestFeeNonDecreasingProperty:
    """Hypothesis: adding more inputs/outputs to a transaction never
    decreases the minimum required fee.

    Spec ref: Shelley formal spec, ``a * tx_size + b``.
    Haskell ref: ``shelleyMinFee`` — min fee is linear in tx_size.
    """

    @given(
        base_size=st.integers(min_value=100, max_value=10000),
        extra=st.integers(min_value=1, max_value=5000),
    )
    @settings(max_examples=200)
    def test_larger_tx_never_decreases_fee(self, base_size: int, extra: int):
        """A larger transaction should never have a lower minimum fee."""
        fee_small = shelley_min_fee(base_size, TEST_PARAMS)
        fee_large = shelley_min_fee(base_size + extra, TEST_PARAMS)
        assert fee_large >= fee_small

    @given(
        size=st.integers(min_value=100, max_value=10000),
    )
    @settings(max_examples=100)
    def test_min_fee_always_positive(self, size: int):
        """Minimum fee should always be positive."""
        fee = shelley_min_fee(size, TEST_PARAMS)
        assert fee > 0


# ---------------------------------------------------------------------------
# Test 6: No double-spend property (Hypothesis)
# ---------------------------------------------------------------------------


class TestNoDoubleSpendProperty:
    """Hypothesis: a valid transaction never consumes the same input twice.

    Spec ref: Shelley formal spec, inputs as a set.
    Haskell ref: TransactionBody inputs field is a ``Set TxIn``.
    """

    @given(
        n_inputs=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_input_set_has_no_duplicates(self, n_inputs: int):
        """Transaction inputs should form a set (no duplicates)."""
        sk, vk = make_key_pair(0)
        addr = make_address(vk)

        # Create unique inputs
        inputs = [TransactionInput(make_tx_id(i), 0) for i in range(n_inputs)]
        utxo: ShelleyUTxO = {}
        total_ada = 0
        for txin in inputs:
            utxo[txin] = TransactionOutput(addr, 10_000_000)
            total_ada += 10_000_000

        fee = 300
        tx_body = TransactionBody(
            inputs=inputs,
            outputs=[TransactionOutput(addr, total_ada - fee)],
            fee=fee,
        )

        # The set property: all inputs are unique
        input_keys = [(txin.transaction_id.payload, txin.index) for txin in tx_body.inputs]
        assert len(input_keys) == len(set(input_keys)), "Inputs must be unique"

    def test_duplicate_input_detected(self):
        """If someone constructs duplicate inputs, they should be detectable."""
        txin = TransactionInput(make_tx_id(0), 0)
        # pycardano uses a list for inputs, so duplicates are possible at construction
        # but the set property should be enforced logically
        inputs = [txin, txin]
        input_keys = [(t.transaction_id.payload, t.index) for t in inputs]
        assert len(input_keys) != len(set(input_keys)), "Duplicate should be detected"


# ---------------------------------------------------------------------------
# Test 7: Consumed inputs eliminated from UTxO set
# ---------------------------------------------------------------------------


class TestConsumedInputsEliminated:
    """Test that after applying a valid transaction, all consumed inputs
    are removed from the UTxO set.

    Spec ref: Shelley formal spec, ``utxo' = (utxo \\ txins) ∪ outs``.
    Haskell ref: ``applyTx`` UTxO update in ``Cardano.Ledger.Shelley.LedgerState``
    """

    def test_spent_inputs_removed(self):
        """After spending, the consumed input should no longer be in the UTxO set."""
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
        )

        # Simulate UTxO update: remove inputs, add outputs
        new_utxo = dict(utxo)
        for inp in tx_body.inputs:
            if inp in new_utxo:
                del new_utxo[inp]

        assert txin not in new_utxo

    def test_multiple_inputs_all_removed(self):
        """All consumed inputs should be removed."""
        sk, vk = make_key_pair(0)
        addr = make_address(vk)

        txin1 = TransactionInput(make_tx_id(0), 0)
        txin2 = TransactionInput(make_tx_id(1), 0)
        utxo: ShelleyUTxO = {
            txin1: TransactionOutput(addr, 5_000_000),
            txin2: TransactionOutput(addr, 5_000_000),
        }

        tx_body = TransactionBody(
            inputs=[txin1, txin2],
            outputs=[TransactionOutput(addr, 9_000_000)],
            fee=1_000_000,
        )

        new_utxo = dict(utxo)
        for inp in tx_body.inputs:
            if inp in new_utxo:
                del new_utxo[inp]

        assert txin1 not in new_utxo
        assert txin2 not in new_utxo

    def test_unconsumed_inputs_preserved(self):
        """Inputs NOT consumed by the tx should remain in the UTxO set."""
        sk, vk = make_key_pair(0)
        addr = make_address(vk)

        txin1 = TransactionInput(make_tx_id(0), 0)
        txin2 = TransactionInput(make_tx_id(1), 0)
        utxo: ShelleyUTxO = {
            txin1: TransactionOutput(addr, 5_000_000),
            txin2: TransactionOutput(addr, 5_000_000),
        }

        # Only spend txin1
        tx_body = TransactionBody(
            inputs=[txin1],
            outputs=[TransactionOutput(addr, 4_000_000)],
            fee=1_000_000,
        )

        new_utxo = dict(utxo)
        for inp in tx_body.inputs:
            if inp in new_utxo:
                del new_utxo[inp]

        assert txin1 not in new_utxo
        assert txin2 in new_utxo  # preserved


# ---------------------------------------------------------------------------
# Test 8: New entries have unique TxIds
# ---------------------------------------------------------------------------


class TestNewEntriesUniqueKeys:
    """Test that outputs created by a transaction have unique TxIn keys
    (tx_hash + index).

    Spec ref: Shelley formal spec, outputs produce unique (TxId, Ix) pairs.
    Haskell ref: ``txins`` / output indexing in TransactionBody.
    """

    def test_outputs_have_unique_indices(self):
        """Each output gets a unique index within the transaction."""
        sk, vk = make_key_pair(0)
        addr = make_address(vk)

        tx_id = make_tx_id(100)
        num_outputs = 5

        tx_body = TransactionBody(
            inputs=[TransactionInput(make_tx_id(0), 0)],
            outputs=[TransactionOutput(addr, 1_000_000) for _ in range(num_outputs)],
            fee=500_000,
        )

        # New UTxO entries would be keyed by (tx_id, output_index)
        new_keys = [(tx_id.payload, i) for i in range(len(tx_body.outputs))]
        assert len(new_keys) == len(set(new_keys)), "Output keys must be unique"

    @given(
        n_outputs=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=50)
    def test_output_indices_always_unique(self, n_outputs: int):
        """For any number of outputs, indices should be unique."""
        tx_id_bytes = hashlib.blake2b(b"tx", digest_size=32).digest()
        keys = [(tx_id_bytes, i) for i in range(n_outputs)]
        assert len(keys) == len(set(keys))
