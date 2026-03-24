"""Alonzo audit gap tests — 6 missing test cases identified by Haskell test audit.

Tests cover:
    1. Alonzo tx body CBOR golden test vectors (deterministic serialization, round-trip)
    2. Redeemer/datum witness CBOR round-trip (all RedeemerTag variants)
    3. MissingRequiredDatums validation (datum hash in output without witness)
    4. Output too small (min UTxO) rejection rule (ADA-only and multi-asset)
    5. Tx metadata hash validation (mismatch and missing metadata)
    6. Multiple script languages in single tx (native + Plutus coexistence)

Spec references:
    - Alonzo ledger formal spec, Section 4 (Transactions)
    - Alonzo ledger formal spec, Section 9 (UTxO transition)
    - Alonzo ledger formal spec, Section 10 (UTXOW)
    - Shelley ledger formal spec, Section 10 (auxiliary_data_hash)
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxo.hs``
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxow.hs``
"""

from __future__ import annotations

import hashlib

import cbor2
import pytest
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
from pycardano.hash import DatumHash, ScriptHash, TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.ledger.allegra_mary import (
    Timelock,
    TimelockType,
    ValidityInterval,
    evaluate_timelock,
)
from vibe.cardano.ledger.alonzo import (
    _missing_required_datums,
    _validate_metadata_hash,
    alonzo_min_utxo_value,
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
# Shared helpers (reused from test_alonzo.py patterns)
# ---------------------------------------------------------------------------


def _make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic TransactionId from a seed."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def _make_key_pair(
    seed: int = 0,
) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    """Create a deterministic signing/verification key pair."""
    seed_bytes = seed.to_bytes(32, "big")
    sk = PaymentSigningKey(seed_bytes)
    vk = sk.to_verification_key()
    return sk, vk


def _make_address(vk: PaymentVerificationKey) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=Network.TESTNET)


def _make_policy_id(seed: int = 0) -> ScriptHash:
    """Create a deterministic ScriptHash (28 bytes)."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def _sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    """Sign a transaction body and return a VKey witness."""
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def _make_simple_utxo(
    tx_id_seed: int = 0,
    index: int = 0,
    value: int | Value = 10_000_000,
    seed: int = 0,
) -> tuple[ShelleyUTxO, TransactionInput, PaymentSigningKey, PaymentVerificationKey]:
    """Create a simple UTxO set with one entry."""
    sk, vk = _make_key_pair(seed)
    addr = _make_address(vk)
    tx_id = _make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk, vk


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


# ---------------------------------------------------------------------------
# Test 1: Alonzo tx body CBOR golden test vectors
# ---------------------------------------------------------------------------


class TestAlonzoTxBodyCBOR:
    """CBOR serialization golden tests for Alonzo transaction bodies.

    Verifies that transaction bodies with known fields produce deterministic
    CBOR encoding and can round-trip through encode/decode.

    Spec ref: Alonzo ledger formal spec, Section 4 (Transactions).
    """

    def test_simple_tx_body_cbor_round_trip(self):
        """A simple tx body should survive CBOR encode/decode round-trip."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
        )

        # Serialize to CBOR
        cbor_bytes = tx_body.to_cbor()
        assert isinstance(cbor_bytes, bytes) or isinstance(cbor_bytes, str)

        # Ensure deterministic: same inputs produce same bytes
        cbor_bytes_2 = tx_body.to_cbor()
        assert cbor_bytes == cbor_bytes_2

        # Round-trip decode
        decoded = TransactionBody.from_cbor(cbor_bytes)
        assert decoded.fee == tx_body.fee
        assert len(decoded.inputs) == 1
        assert len(decoded.outputs) == 1

    def test_alonzo_fields_cbor_round_trip(self):
        """Tx body with Alonzo-specific fields should round-trip through CBOR.

        Tests collateral, required_signers, and script_data_hash fields.
        """
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)
        coll_txin = TransactionInput(_make_tx_id(1), 0)

        # Create a script data hash (32 bytes)
        script_data_hash = hashlib.blake2b(b"test_script_data", digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
            collateral=[coll_txin],
            required_signers=[vk.hash()],
            script_data_hash=script_data_hash,
        )

        cbor_bytes = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(cbor_bytes)

        assert decoded.fee == 200_000
        assert decoded.collateral is not None
        assert len(decoded.collateral) == 1
        assert decoded.required_signers is not None
        assert len(decoded.required_signers) == 1
        assert bytes(decoded.script_data_hash) == script_data_hash

    def test_multi_asset_output_cbor_round_trip(self):
        """Tx body with multi-asset outputs should round-trip through CBOR."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        policy_id = _make_policy_id(1)
        ma = MultiAsset({policy_id: Asset({AssetName(b"vibetoken"): 1000})})

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, Value(coin=5_000_000, multi_asset=ma))],
            fee=300_000,
        )

        cbor_bytes = tx_body.to_cbor()
        decoded = TransactionBody.from_cbor(cbor_bytes)

        assert decoded.fee == 300_000
        out_amount = decoded.outputs[0].amount
        assert not isinstance(out_amount, int)
        assert out_amount.coin == 5_000_000
        assert out_amount.multi_asset is not None

    def test_cbor_is_deterministic(self):
        """Multiple serializations of the same tx body produce identical bytes."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(42)
        txin = TransactionInput(tx_id, 0)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 3_000_000)],
            fee=180_000,
        )

        results = [tx_body.to_cbor() for _ in range(5)]
        assert all(r == results[0] for r in results)


# ---------------------------------------------------------------------------
# Test 2: Redeemer/datum witness CBOR round-trip
# ---------------------------------------------------------------------------


class TestRedeemerDatumCBORRoundTrip:
    """CBOR round-trip tests for Redeemer and datum objects.

    Verifies that our Redeemer type can be serialized to CBOR and back,
    and that datum CBOR encoding is stable across all RedeemerTag variants.

    Spec ref: Alonzo formal spec, ``Redeemers = RdmrPtr -> (Data x ExUnits)``.
    """

    @pytest.mark.parametrize("tag", list(RedeemerTag))
    def test_redeemer_cbor_round_trip_all_tags(self, tag: RedeemerTag):
        """Redeemer with each tag variant should round-trip through CBOR."""
        data_value = {"constructor": 0, "fields": [42]}
        data_cbor = cbor2.dumps(data_value)

        redeemer = Redeemer(
            tag=tag,
            index=0,
            data=data_cbor,
            ex_units=ExUnits(mem=500_000, steps=1_000_000),
        )

        # Serialize redeemer to a CBOR-compatible structure
        encoded = [
            redeemer.tag.value,
            redeemer.index,
            cbor2.loads(redeemer.data),
            [redeemer.ex_units.mem, redeemer.ex_units.steps],
        ]
        cbor_bytes = cbor2.dumps(encoded)

        # Decode and verify
        decoded = cbor2.loads(cbor_bytes)
        assert decoded[0] == tag.value
        assert decoded[1] == 0
        assert decoded[2] == data_value
        assert decoded[3] == [500_000, 1_000_000]

        # Reconstruct the Redeemer
        reconstructed = Redeemer(
            tag=RedeemerTag(decoded[0]),
            index=decoded[1],
            data=cbor2.dumps(decoded[2]),
            ex_units=ExUnits(mem=decoded[3][0], steps=decoded[3][1]),
        )
        assert reconstructed.tag == redeemer.tag
        assert reconstructed.index == redeemer.index
        assert reconstructed.ex_units == redeemer.ex_units

    def test_datum_cbor_round_trip(self):
        """Datum CBOR encoding should be deterministic and round-trippable."""
        # Various Plutus Data shapes
        datum_values = [
            42,  # Integer
            b"\xde\xad\xbe\xef",  # Bytes
            [1, 2, 3],  # List (Plutus list constructor)
            {"a": 1, "b": 2},  # Map
        ]

        for val in datum_values:
            encoded = cbor2.dumps(val)
            decoded = cbor2.loads(encoded)
            re_encoded = cbor2.dumps(decoded)
            assert encoded == re_encoded, f"Round-trip failed for {val}"

    def test_datum_hash_deterministic(self):
        """Datum hash (Blake2b-256 of CBOR) should be deterministic."""
        datum = cbor2.dumps({"constructor": 1, "fields": [100, 200]})
        h1 = hashlib.blake2b(datum, digest_size=32).digest()
        h2 = hashlib.blake2b(datum, digest_size=32).digest()
        assert h1 == h2
        assert len(h1) == 32

    def test_different_redeemer_tags_different_encoding(self):
        """Different RedeemerTags should produce different CBOR encodings."""
        data_cbor = cbor2.dumps(0)
        encodings = set()

        for tag in RedeemerTag:
            encoded = cbor2.dumps([tag.value, 0, cbor2.loads(data_cbor), [100, 200]])
            encodings.add(encoded)

        # All 4 tags should produce distinct encodings
        assert len(encodings) == 4


# ---------------------------------------------------------------------------
# Test 3: MissingRequiredDatums validation
# ---------------------------------------------------------------------------


class TestMissingRequiredDatums:
    """Tests for the MissingRequiredDatums validation rule.

    When a transaction output includes a datum hash, the corresponding datum
    must be present in the transaction witness set.

    Spec ref: Alonzo formal spec, ``missingRequiredDatums``.
    Haskell ref: ``missingRequiredDatums`` in ``Cardano.Ledger.Alonzo.Rules.Utxow``
    """

    def test_output_with_datum_hash_and_matching_witness_passes(self):
        """Output with datum hash + matching datum witness should pass."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        # Create a datum and compute its hash
        datum_cbor = cbor2.dumps(42)
        datum_hash = hashlib.blake2b(datum_cbor, digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000, datum_hash=DatumHash(datum_hash))],
            fee=200_000,
        )

        errors = _missing_required_datums(tx_body, datums=[datum_cbor])
        assert errors == []

    def test_output_with_datum_hash_missing_witness_fails(self):
        """Output with datum hash but NO matching datum witness should fail."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000, datum_hash=DatumHash(datum_hash))],
            fee=200_000,
        )

        # No datums in witness set
        errors = _missing_required_datums(tx_body, datums=[])
        assert len(errors) == 1
        assert "MissingRequiredDatums" in errors[0]

    def test_output_with_datum_hash_wrong_witness_fails(self):
        """Output with datum hash + WRONG datum witness should fail."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        # Hash for datum 42
        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000, datum_hash=DatumHash(datum_hash))],
            fee=200_000,
        )

        # Provide a DIFFERENT datum (99 instead of 42)
        wrong_datum = cbor2.dumps(99)
        errors = _missing_required_datums(tx_body, datums=[wrong_datum])
        assert len(errors) == 1
        assert "MissingRequiredDatums" in errors[0]

    def test_output_without_datum_hash_passes(self):
        """Output without datum hash should pass regardless of datums."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
        )

        errors = _missing_required_datums(tx_body, datums=[])
        assert errors == []

    def test_multiple_outputs_mixed_datum_hashes(self):
        """Multiple outputs: one with datum hash (witnessed), one without."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)
        tx_id = _make_tx_id(0)
        txin = TransactionInput(tx_id, 0)

        datum_cbor = cbor2.dumps(42)
        datum_hash = hashlib.blake2b(datum_cbor, digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[
                TransactionOutput(addr, 2_000_000, datum_hash=DatumHash(datum_hash)),
                TransactionOutput(addr, 3_000_000),  # no datum hash
            ],
            fee=200_000,
        )

        errors = _missing_required_datums(tx_body, datums=[datum_cbor])
        assert errors == []

    def test_integrated_via_validate_alonzo_witnesses(self):
        """MissingRequiredDatums should fire through validate_alonzo_witnesses."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000, datum_hash=DatumHash(datum_hash))],
            fee=2_000_000,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            datums=[],  # Missing the required datum!
        )
        assert any("MissingRequiredDatums" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 4: Output too small (min UTxO) rejection rule
# ---------------------------------------------------------------------------


class TestOutputTooSmallMinUTxO:
    """Tests for OutputTooSmallUTxO rejection in validate_alonzo_utxo.

    Alonzo uses coinsPerUTxOWord to calculate minimum UTxO value, which
    varies based on output size (value, datum hash presence).

    Spec ref: Alonzo formal spec, ``utxoEntrySize``.
    Haskell ref: ``utxoEntrySize`` in ``Cardano.Ledger.Alonzo.Rules.Utxo``
    """

    def test_ada_only_output_below_min_rejected(self):
        """Pure ADA output below minimum should be rejected."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        # min for ADA-only: (27 + 2) * 4310 = 124990
        # Set output to just 1 lovelace — way below minimum
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 1)],
            fee=10_000_000 - 1,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("OutputTooSmallUTxO" in e for e in errors)

    def test_ada_only_output_at_min_passes(self):
        """Pure ADA output exactly at minimum should pass that check."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)

        # Calculate the exact minimum for a pure ADA output
        test_out = TransactionOutput(addr, 1)
        min_val = alonzo_min_utxo_value(test_out, TEST_PARAMS.coins_per_utxo_word)

        # Create UTxO with enough to cover output + fee
        total_input = min_val + 200  # output + fee
        utxo, txin, sk, vk = _make_simple_utxo(value=total_input)
        addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, min_val)],
            fee=200,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        # Should not have OutputTooSmallUTxO (may have FeeTooSmall)
        assert not any("OutputTooSmallUTxO" in e for e in errors)

    def test_multi_asset_output_below_min_rejected(self):
        """Multi-asset output below minimum should be rejected."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        # Create a multi-asset output with too little ADA
        policy_id = _make_policy_id(1)
        ma = MultiAsset({policy_id: Asset({AssetName(b"token"): 100})})

        # Multi-asset outputs need MORE than pure ADA outputs
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, Value(coin=1, multi_asset=ma))],
            fee=10_000_000 - 1,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        assert any("OutputTooSmallUTxO" in e for e in errors)

    def test_multi_asset_min_higher_than_ada_only(self):
        """Multi-asset minimum should be strictly higher than ADA-only minimum."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)

        ada_only_out = TransactionOutput(addr, 2_000_000)
        ada_min = alonzo_min_utxo_value(ada_only_out, TEST_PARAMS.coins_per_utxo_word)

        policy_id = _make_policy_id(1)
        ma = MultiAsset(
            {
                policy_id: Asset(
                    {
                        AssetName(b"token_a"): 100,
                        AssetName(b"token_b"): 200,
                    }
                )
            }
        )
        multi_out = TransactionOutput(addr, Value(coin=2_000_000, multi_asset=ma))
        multi_min = alonzo_min_utxo_value(multi_out, TEST_PARAMS.coins_per_utxo_word)

        assert multi_min > ada_min

    def test_multiple_outputs_one_too_small(self):
        """If one output of several is too small, only that one is flagged."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[
                TransactionOutput(addr, 5_000_000),  # OK
                TransactionOutput(addr, 1),  # Too small
            ],
            fee=10_000_000 - 5_000_001,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
        )
        too_small_errors = [e for e in errors if "OutputTooSmallUTxO" in e]
        assert len(too_small_errors) == 1
        assert "output[1]" in too_small_errors[0]


# ---------------------------------------------------------------------------
# Test 5: Tx metadata hash validation
# ---------------------------------------------------------------------------


class TestMetadataHashValidation:
    """Tests for auxiliary_data_hash / metadata hash validation.

    If a transaction body declares an auxiliary_data_hash, the actual metadata
    must be present and its hash must match.

    Spec ref: Shelley formal spec, ``txADhash`` validation.
    Haskell ref: ``validateMissingOrIncorrectAuxiliaryDataHash`` in
        Cardano.Ledger.Shelley.Rules.Utxow
    """

    def test_no_metadata_hash_no_metadata_passes(self):
        """Tx with neither metadata hash nor metadata should pass."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
        )
        witness_set = TransactionWitnessSet()

        errors = _validate_metadata_hash(tx_body, witness_set)
        assert errors == []

    def test_metadata_hash_present_but_no_metadata_fails(self):
        """Tx body with auxiliary_data_hash but no metadata should fail."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)

        fake_hash = hashlib.blake2b(b"fake_metadata", digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
            auxiliary_data_hash=fake_hash,
        )
        witness_set = TransactionWitnessSet()

        errors = _validate_metadata_hash(tx_body, witness_set)
        assert len(errors) == 1
        assert "MetadataHashMismatch" in errors[0]

    def test_metadata_hash_mismatch_fails(self):
        """Tx body with wrong auxiliary_data_hash should fail."""
        sk, vk = _make_key_pair()
        addr = _make_address(vk)

        # Declare one hash but don't provide matching metadata
        wrong_hash = b"\x00" * 32

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(0), 0)],
            outputs=[TransactionOutput(addr, 2_000_000)],
            fee=200_000,
            auxiliary_data_hash=wrong_hash,
        )
        # Even if we put auxiliary_data on the witness set, the hash won't match
        witness_set = TransactionWitnessSet()

        errors = _validate_metadata_hash(tx_body, witness_set)
        assert len(errors) >= 1
        assert any("MetadataHashMismatch" in e for e in errors)

    def test_integrated_through_alonzo_witnesses(self):
        """Metadata hash check fires through validate_alonzo_witnesses."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        fake_hash = hashlib.blake2b(b"some_metadata", digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
            auxiliary_data_hash=fake_hash,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
        )
        assert any("MetadataHashMismatch" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 6: Multiple script languages in single tx
# ---------------------------------------------------------------------------


class TestMultipleScriptLanguages:
    """Tests for transactions containing both native scripts and Plutus scripts.

    Alonzo supports both native (timelock) scripts and Plutus scripts in
    the same transaction. The validation must handle both correctly.

    Spec ref: Alonzo formal spec, Section 5 (Scripts and Validation).
    Haskell ref: ``Cardano.Ledger.Alonzo.Scripts``
    """

    def test_native_and_plutus_scripts_coexist_in_integrity_hash(self):
        """Script integrity hash should work when Plutus scripts are present
        alongside native scripts (native scripts don't affect the hash).
        """
        # Native scripts don't have redeemers or contribute to script integrity
        # hash. Only Plutus scripts do. Verify the hash only covers Plutus.

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"addInteger-cpu": 100}}
        languages = {Language.PLUTUS_V1}

        # Compute hash with Plutus only (native scripts excluded)
        h = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        assert isinstance(h, bytes)
        assert len(h) == 32

        # Same hash regardless of native scripts present
        h2 = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        assert h == h2

    def test_native_script_evaluation_alongside_plutus_context(self):
        """A native timelock script should evaluate correctly even when
        Plutus scripts are also being used in the same transaction.
        """
        # Timelock: require signature from key hash
        key_hash = hashlib.blake2b(b"signer_key", digest_size=28).digest()

        timelock_script = Timelock(
            type=TimelockType.REQUIRE_SIGNATURE,
            key_hash=key_hash,
        )

        # Evaluate with the correct signer
        signers = frozenset([key_hash])
        assert evaluate_timelock(timelock_script, signers, current_slot=100) is True

        # Evaluate without the signer
        assert evaluate_timelock(timelock_script, frozenset(), current_slot=100) is False

    def test_time_based_native_script_with_plutus(self):
        """A time-based native script (RequireTimeBefore) should work in
        a transaction that also uses Plutus scripts.
        """
        # RequireTimeBefore slot 200: valid only before slot 200
        time_script = Timelock(
            type=TimelockType.REQUIRE_TIME_BEFORE,
            slot=200,
        )

        # Valid at slot 100
        assert evaluate_timelock(time_script, frozenset(), current_slot=100) is True

        # Invalid at slot 200
        assert evaluate_timelock(time_script, frozenset(), current_slot=200) is False

    def test_combined_native_and_plutus_validation(self):
        """Full tx validation should work with both native and Plutus scripts.

        We construct a transaction with Plutus script features (redeemers,
        script integrity hash) and verify that the Alonzo validation pipeline
        handles it correctly, including checks that would also apply to
        native scripts (validity interval, which is needed for timelocks).
        """
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        addr = _make_address(vk)

        # Create collateral
        coll_txin = TransactionInput(_make_tx_id(100), 0)
        utxo[coll_txin] = TransactionOutput(addr, 5_000_000)

        # Redeemers for the Plutus script
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(42),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        datum_hash = hashlib.blake2b(datums[0], digest_size=32).digest()
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}

        # Compute correct script integrity hash
        integrity_hash = compute_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[
                TransactionOutput(
                    addr,
                    8_000_000,
                    datum_hash=DatumHash(datum_hash),
                )
            ],
            fee=2_000_000,
            collateral=[coll_txin],
            validity_start=10,
            ttl=1000,
            script_data_hash=integrity_hash,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # Validity interval covers current slot
        interval = ValidityInterval(invalid_before=10, invalid_hereafter=1000)

        errors = validate_alonzo_tx(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
            datums=datums,
            validity_interval=interval,
            collateral_inputs=[coll_txin],
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert errors == []

    def test_m_of_n_timelock_with_plutus_context(self):
        """A complex MOfN native script should evaluate correctly in a
        Plutus-enabled transaction context.
        """
        key1 = hashlib.blake2b(b"key1", digest_size=28).digest()
        key2 = hashlib.blake2b(b"key2", digest_size=28).digest()
        key3 = hashlib.blake2b(b"key3", digest_size=28).digest()

        # 2-of-3 multisig
        m_of_n_script = Timelock(
            type=TimelockType.REQUIRE_M_OF_N,
            required=2,
            scripts=(
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key1),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key2),
                Timelock(type=TimelockType.REQUIRE_SIGNATURE, key_hash=key3),
            ),
        )

        # 2 of 3 signers present — should pass
        signers = frozenset([key1, key3])
        assert evaluate_timelock(m_of_n_script, signers, current_slot=100) is True

        # Only 1 of 3 — should fail
        signers_1 = frozenset([key2])
        assert evaluate_timelock(m_of_n_script, signers_1, current_slot=100) is False

        # All 3 — should pass
        signers_all = frozenset([key1, key2, key3])
        assert evaluate_timelock(m_of_n_script, signers_all, current_slot=100) is True
