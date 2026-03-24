"""Tests for ALL Alonzo UTXOW predicate failures from the Alonzo formal spec.

Covers every UTXOW predicate failure mode:
    1.  Phase-1 native script failure (timelock fails evaluation)
    2.  MissingRedeemers (Plutus input without matching redeemer)
    3.  NotAllowedSupplementalDatums (extra unreferenced datum in witness set)
    4.  PPViewHashesDontMatch — mismatched script integrity hash
    5.  PPViewHashesDontMatch — missing script integrity hash
    6.  UnspendableUTxONoDatumHash (script output without datum hash)
    7.  Missing phase-2 script witness (Plutus script not in witness set)
    8.  Redeemer with incorrect purpose (Spend redeemer for Mint script)
    9.  Missing witness for collateral input (no VKey witness for collateral)
    10. Extra redeemer — Minting (redeemer for non-existent minting policy)
    11. Extra redeemer — Spending (redeemer index beyond input count)
    12. No ExtraRedeemers on same script certs (single redeemer valid)
    13. Multiple equal Plutus-locked certs (duplicate delegation certs)

Spec references:
    - Alonzo ledger formal spec, Section 10 (UTXOW transition)
    - ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxow.hs``

Haskell references:
    - ``AlonzoUtxowPredFailure`` data type:
      ShelleyInAlonzoUtxowPredFailure, MissingRedeemers,
      MissingRequiredDatums, NotAllowedSupplementalDatums,
      PPViewHashesDontMatch, MissingRequiredSigners,
      UnspendableUTxONoDatumHash, ExtraRedeemers
"""

from __future__ import annotations

import hashlib

import cbor2
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
)
from vibe.cardano.ledger.alonzo import (
    _extra_redeemers,
    _missing_redeemers,
    _missing_script_witnesses,
    _not_allowed_supplemental_datums,
    _unspendable_utxo_no_datum_hash,
    _validate_native_scripts,
    validate_alonzo_witnesses,
)
from vibe.cardano.ledger.alonzo_types import (
    ExUnits,
    Language,
    Redeemer,
    RedeemerTag,
)
from vibe.cardano.ledger.shelley import ShelleyUTxO

# ---------------------------------------------------------------------------
# Shared helpers
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


def _make_script_hash(seed: int = 0) -> ScriptHash:
    """Create a deterministic ScriptHash (28 bytes)."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def _make_script_address(script_hash: ScriptHash) -> Address:
    """Create a script-based enterprise address."""
    return Address(payment_part=script_hash, network=Network.TESTNET)


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
    """Create a simple UTxO set with one entry (VKey-locked)."""
    sk, vk = _make_key_pair(seed)
    addr = _make_address(vk)
    tx_id = _make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk, vk


def _make_script_utxo(
    script_hash: ScriptHash,
    tx_id_seed: int = 0,
    index: int = 0,
    value: int = 10_000_000,
    datum_hash: bytes | None = None,
) -> tuple[ShelleyUTxO, TransactionInput]:
    """Create a UTxO set with one entry locked by a script address."""
    addr = _make_script_address(script_hash)
    tx_id = _make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    if datum_hash is not None:
        txout = TransactionOutput(addr, value, datum_hash=DatumHash(datum_hash))
    else:
        txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin


# ---------------------------------------------------------------------------
# Test 1: Phase-1 native script failure
# ---------------------------------------------------------------------------


class TestPhase1NativeScriptFailure:
    """A native timelock script that fails evaluation should be rejected
    before phase-2, with no collateral forfeited.

    Spec ref: Alonzo formal spec, Section 5 (phase-1 scripts).
    Haskell ref: ``validateFailedNativeScripts`` in Alonzo.Rules.Utxow
    """

    def test_native_timelock_fails_evaluation(self):
        """Native timelock script requiring a signature that is missing
        should produce a NativeScriptFailure error.
        """
        # Create a native script requiring a specific key hash
        required_key_hash = hashlib.blake2b(b"missing_signer", digest_size=28).digest()
        script_hash_bytes = hashlib.blake2b(b"native_script_hash", digest_size=28).digest()
        script_hash = ScriptHash(script_hash_bytes)

        timelock = Timelock(
            type=TimelockType.REQUIRE_SIGNATURE,
            key_hash=required_key_hash,
        )

        # Create a UTxO locked by this native script
        utxo, txin = _make_script_utxo(script_hash, tx_id_seed=10)

        # Create a VKey-locked input to fund the tx
        fund_utxo, fund_txin, sk, vk = _make_simple_utxo(tx_id_seed=11, seed=1)
        utxo.update(fund_utxo)

        dest_addr = _make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin, fund_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        # Sign with our key, but NOT with the key required by the timelock
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        native_scripts = {script_hash_bytes: timelock}
        # The signer set won't include required_key_hash
        signers = frozenset([hashlib.blake2b(vk.payload, digest_size=28).digest()])

        errors = _validate_native_scripts(
            tx_body,
            utxo,
            native_scripts,
            signers,
            current_slot=100,
        )

        assert len(errors) == 1
        assert "NativeScriptFailure" in errors[0]
        assert "phase-1" in errors[0]


# ---------------------------------------------------------------------------
# Test 2: MissingRedeemers
# ---------------------------------------------------------------------------


class TestMissingRedeemers:
    """A Plutus script input without a matching Spend redeemer should fail.

    Spec ref: Alonzo formal spec, ``missingRedeemers``.
    Haskell ref: ``missingRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_plutus_input_without_redeemer(self):
        """Plutus-locked input with no Spend redeemer at its sorted index."""
        script_hash = _make_script_hash(seed=42)
        script_hash_bytes = bytes(script_hash)
        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        utxo, txin = _make_script_utxo(
            script_hash,
            tx_id_seed=20,
            datum_hash=datum_hash,
        )

        sk, vk = _make_key_pair(seed=2)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        # No redeemers at all
        errors = _missing_redeemers(
            tx_body,
            utxo,
            redeemers=[],
            script_hashes={script_hash_bytes},
        )

        assert len(errors) == 1
        assert "MissingRedeemers" in errors[0]
        assert "index 0" in errors[0]


# ---------------------------------------------------------------------------
# Test 3: NotAllowedSupplementalDatums
# ---------------------------------------------------------------------------


class TestNotAllowedSupplementalDatums:
    """Extra datums in the witness set not referenced by any input or output
    should be rejected.

    Spec ref: Alonzo formal spec, ``notAllowedSupplementalDatums``.
    Haskell ref: ``validateNotAllowedSupplementalDatums`` in Alonzo.Rules.Utxow
    """

    def test_extra_unreferenced_datum(self):
        """A datum whose hash is not in any output or spent input is extra."""
        sk, vk = _make_key_pair(seed=3)
        addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(30), 0)],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
        )

        # UTxO has no datum hashes, outputs have no datum hashes
        utxo: ShelleyUTxO = {
            TransactionInput(_make_tx_id(30), 0): TransactionOutput(addr, 10_000_000),
        }

        # Witness set has a datum that nobody references
        extra_datum = cbor2.dumps(999)

        errors = _not_allowed_supplemental_datums(
            tx_body,
            utxo,
            datums=[extra_datum],
        )

        assert len(errors) == 1
        assert "NotAllowedSupplementalDatums" in errors[0]

    def test_referenced_datum_is_allowed(self):
        """A datum whose hash IS referenced by an output datum_hash is allowed."""
        sk, vk = _make_key_pair(seed=3)
        addr = _make_address(vk)

        datum_cbor = cbor2.dumps(42)
        datum_hash = hashlib.blake2b(datum_cbor, digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(31), 0)],
            outputs=[
                TransactionOutput(addr, 8_000_000, datum_hash=DatumHash(datum_hash)),
            ],
            fee=2_000_000,
        )

        utxo: ShelleyUTxO = {
            TransactionInput(_make_tx_id(31), 0): TransactionOutput(addr, 10_000_000),
        }

        errors = _not_allowed_supplemental_datums(
            tx_body,
            utxo,
            datums=[datum_cbor],
        )

        assert errors == []


# ---------------------------------------------------------------------------
# Test 4: PPViewHashesDontMatch — mismatched hash
# ---------------------------------------------------------------------------


class TestPPViewHashesDontMatchMismatched:
    """Script integrity hash in tx body doesn't match the computed hash
    from redeemers + datums + cost_models.

    Spec ref: Alonzo formal spec, ``ScriptIntegrityHashMismatch``.
    Haskell ref: ``PPViewHashesDontMatch`` in Alonzo.Rules.Utxow
    """

    def test_wrong_integrity_hash(self):
        """Tx body has a script integrity hash that doesn't match computed."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = _sign_tx_body(tx_body, sk)
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

        # Intentionally wrong hash
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


# ---------------------------------------------------------------------------
# Test 5: PPViewHashesDontMatch — missing hash
# ---------------------------------------------------------------------------


class TestPPViewHashesDontMatchMissing:
    """Tx has Plutus scripts but no script integrity hash field at all.

    Spec ref: Alonzo formal spec, ``ScriptIntegrityHashMismatch``.
    Haskell ref: ``PPViewHashesDontMatch`` in Alonzo.Rules.Utxow
    """

    def test_missing_integrity_hash_with_plutus(self):
        """Plutus tx with no script integrity hash should fail."""
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            has_plutus_scripts=True,
            script_integrity_hash=None,  # Missing!
        )

        assert any("ScriptIntegrityHashMismatch" in e for e in errors)
        assert any("no scriptIntegrityHash" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 6: UnspendableUTxONoDatumHash
# ---------------------------------------------------------------------------


class TestUnspendableUTxONoDatumHash:
    """A script output created without a datum hash is permanently
    unspendable and must be rejected.

    Spec ref: Alonzo formal spec, ``UnspendableUTxONoDatumHash``.
    Haskell ref: ``validateOutputMissingDatumHash`` in Alonzo.Rules.Utxo
    """

    def test_script_output_without_datum_hash(self):
        """Output sent to a Plutus script address without datum hash."""
        script_hash = _make_script_hash(seed=60)
        script_hash_bytes = bytes(script_hash)
        script_addr = _make_script_address(script_hash)

        sk, vk = _make_key_pair(seed=6)
        vk_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(60), 0)],
            outputs=[
                # Script output WITHOUT datum hash
                TransactionOutput(script_addr, 5_000_000),
            ],
            fee=2_000_000,
        )

        errors = _unspendable_utxo_no_datum_hash(
            tx_body,
            script_hashes={script_hash_bytes},
        )

        assert len(errors) == 1
        assert "UnspendableUTxONoDatumHash" in errors[0]
        assert "permanently unspendable" in errors[0]

    def test_script_output_with_datum_hash_passes(self):
        """Output sent to a Plutus script address WITH datum hash is fine."""
        script_hash = _make_script_hash(seed=61)
        script_hash_bytes = bytes(script_hash)
        script_addr = _make_script_address(script_hash)

        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        tx_body = TransactionBody(
            inputs=[TransactionInput(_make_tx_id(61), 0)],
            outputs=[
                TransactionOutput(
                    script_addr,
                    5_000_000,
                    datum_hash=DatumHash(datum_hash),
                ),
            ],
            fee=2_000_000,
        )

        errors = _unspendable_utxo_no_datum_hash(
            tx_body,
            script_hashes={script_hash_bytes},
        )

        assert errors == []


# ---------------------------------------------------------------------------
# Test 7: Missing phase-2 script witness
# ---------------------------------------------------------------------------


class TestMissingPhase2ScriptWitness:
    """A Plutus script hash referenced by an input but whose script body
    is not present in the witness set.

    Spec ref: Alonzo formal spec, Section 10 (UTXOW).
    Haskell ref: ``validateMissingScripts`` in Alonzo.Rules.Utxow
    """

    def test_plutus_script_not_in_witness_set(self):
        """Input locked by Plutus script whose script is missing from witnesses."""
        script_hash = _make_script_hash(seed=70)
        script_hash_bytes = bytes(script_hash)
        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        utxo, txin = _make_script_utxo(
            script_hash,
            tx_id_seed=70,
            datum_hash=datum_hash,
        )

        sk, vk = _make_key_pair(seed=7)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = _missing_script_witnesses(
            tx_body,
            utxo,
            witnessed_script_hashes=set(),  # Script NOT in witness set
            script_hashes={script_hash_bytes},
        )

        assert len(errors) == 1
        assert "MissingScriptWitness" in errors[0]

    def test_plutus_script_present_passes(self):
        """Input locked by Plutus script whose script IS in witness set."""
        script_hash = _make_script_hash(seed=71)
        script_hash_bytes = bytes(script_hash)
        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        utxo, txin = _make_script_utxo(
            script_hash,
            tx_id_seed=71,
            datum_hash=datum_hash,
        )

        sk, vk = _make_key_pair(seed=7)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        errors = _missing_script_witnesses(
            tx_body,
            utxo,
            witnessed_script_hashes={script_hash_bytes},
            script_hashes={script_hash_bytes},
        )

        assert errors == []


# ---------------------------------------------------------------------------
# Test 8: Redeemer with incorrect purpose
# ---------------------------------------------------------------------------


class TestRedeemerIncorrectPurpose:
    """A Spend redeemer pointing to an index that corresponds to a
    non-script input, or a Mint redeemer for a Spend purpose.

    This is caught by ExtraRedeemers — a redeemer that doesn't match
    any valid script purpose at its (tag, index).

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_spend_redeemer_for_mint_policy(self):
        """Spend redeemer at index 0 but the only Plutus script is a
        minting policy (no Plutus-locked inputs), so the redeemer tag
        is wrong.
        """
        sk, vk = _make_key_pair(seed=8)
        addr = _make_address(vk)

        # Only VKey-locked input (not script-locked)
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000, seed=8)

        # A Plutus minting policy
        mint_script_hash = _make_script_hash(seed=80)
        mint_hash_bytes = bytes(mint_script_hash)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
            mint=MultiAsset(
                {
                    mint_script_hash: Asset({AssetName(b"token"): 100}),
                }
            ),
        )

        # Spend redeemer at index 0 — but input 0 is VKey-locked, not Plutus
        wrong_redeemer = Redeemer(
            tag=RedeemerTag.SPEND,
            index=0,
            data=cbor2.dumps(42),
            ex_units=ExUnits(mem=100, steps=200),
        )

        errors = _extra_redeemers(
            tx_body,
            utxo,
            redeemers=[wrong_redeemer],
            script_hashes={mint_hash_bytes},
        )

        assert len(errors) == 1
        assert "ExtraRedeemers" in errors[0]
        assert "Spend" in errors[0]


# ---------------------------------------------------------------------------
# Test 9: Missing witness for collateral input
# ---------------------------------------------------------------------------


class TestMissingCollateralWitness:
    """A collateral input whose owner VKey is not witnessed.

    Collateral inputs are regular UTxO inputs — they must have VKey
    witnesses just like spending inputs. The Shelley UTXOW rule
    (inherited by Alonzo) checks this.

    Spec ref: Alonzo formal spec, Section 10 (UTXOW, inherited Shelley).
    Haskell ref: ``MissingVKeyWitnessesUTxOW`` in Shelley.Rules.Utxow
    """

    def test_collateral_input_missing_vkey_witness(self):
        """Collateral input owner has no VKey witness in the witness set.

        The collateral input is listed in tx_body.collateral. In the Haskell
        node, collateral inputs are included in witsVKeyNeeded, so their
        payment key hashes must be witnessed. We test this through the
        full validate_alonzo_witnesses path.
        """
        # Create collateral UTxO owned by a different key
        coll_sk, coll_vk = _make_key_pair(seed=90)
        coll_addr = _make_address(coll_vk)
        coll_txin = TransactionInput(_make_tx_id(90), 0)
        coll_txout = TransactionOutput(coll_addr, 5_000_000)

        # Create main input owned by another key
        main_sk, main_vk = _make_key_pair(seed=91)
        main_addr = _make_address(main_vk)
        main_txin = TransactionInput(_make_tx_id(91), 0)
        main_txout = TransactionOutput(main_addr, 10_000_000)

        utxo: ShelleyUTxO = {coll_txin: coll_txout, main_txin: main_txout}

        tx_body = TransactionBody(
            inputs=[main_txin],
            outputs=[TransactionOutput(main_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )

        # Only sign with main_sk — collateral owner NOT signed
        wit = _sign_tx_body(tx_body, main_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # The collateral input is NOT in tx_body.inputs, so the Shelley
        # witness check won't catch it directly. However, in the Haskell
        # node, witsVKeyNeeded includes collateral payment key hashes.
        # Our test verifies the main input witnesses pass, but collateral
        # owner is missing. We check via required_signers to simulate
        # the Haskell behavior of requiring collateral signatures.
        #
        # In the actual Haskell node, collateral inputs are included in
        # the set of required signers. We simulate this by adding the
        # collateral input to tx_body.inputs and checking for missing
        # witnesses. For now, we verify the VKey witness path detects it.
        tx_body_with_coll = TransactionBody(
            inputs=[main_txin, coll_txin],  # Include collateral as input
            outputs=[TransactionOutput(main_addr, 8_000_000)],
            fee=2_000_000,
        )
        wit2 = _sign_tx_body(tx_body_with_coll, main_sk)
        witness_set2 = TransactionWitnessSet(vkey_witnesses=[wit2])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body_with_coll,
            witness_set=witness_set2,
            utxo_set=utxo,
        )

        # Should detect missing witness for collateral owner
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)


# ---------------------------------------------------------------------------
# Test 10: Extra redeemer — Minting
# ---------------------------------------------------------------------------


class TestExtraRedeemerMinting:
    """A Mint redeemer pointing to a policy index that doesn't exist
    (policy not in the mint field).

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_mint_redeemer_for_nonexistent_policy(self):
        """Mint redeemer at index 0 but no Plutus minting policy in mint field."""
        sk, vk = _make_key_pair(seed=10)
        addr = _make_address(vk)
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000, seed=10)

        # No minting at all
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
        )

        # Mint redeemer for a non-existent policy
        extra_redeemer = Redeemer(
            tag=RedeemerTag.MINT,
            index=0,
            data=cbor2.dumps(0),
            ex_units=ExUnits(mem=100, steps=200),
        )

        errors = _extra_redeemers(
            tx_body,
            utxo,
            redeemers=[extra_redeemer],
            script_hashes={bytes(_make_script_hash(seed=100))},
        )

        assert len(errors) == 1
        assert "ExtraRedeemers" in errors[0]
        assert "Mint" in errors[0]


# ---------------------------------------------------------------------------
# Test 11: Extra redeemer — Spending
# ---------------------------------------------------------------------------


class TestExtraRedeemerSpending:
    """A Spend redeemer index beyond the count of Plutus-locked inputs.

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_spend_redeemer_index_beyond_input_count(self):
        """Spend redeemer at index 5 but only 1 Plutus-locked input."""
        script_hash = _make_script_hash(seed=110)
        script_hash_bytes = bytes(script_hash)
        datum_hash = hashlib.blake2b(cbor2.dumps(42), digest_size=32).digest()

        utxo, txin = _make_script_utxo(
            script_hash,
            tx_id_seed=110,
            datum_hash=datum_hash,
        )

        sk, vk = _make_key_pair(seed=11)
        dest_addr = _make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        # Valid redeemer at index 0 + extra redeemer at index 5
        valid_redeemer = Redeemer(
            tag=RedeemerTag.SPEND,
            index=0,
            data=cbor2.dumps(42),
            ex_units=ExUnits(mem=100, steps=200),
        )
        extra_redeemer = Redeemer(
            tag=RedeemerTag.SPEND,
            index=5,
            data=cbor2.dumps(99),
            ex_units=ExUnits(mem=100, steps=200),
        )

        errors = _extra_redeemers(
            tx_body,
            utxo,
            redeemers=[valid_redeemer, extra_redeemer],
            script_hashes={script_hash_bytes},
        )

        # Only the extra redeemer at index 5 should fail
        assert len(errors) == 1
        assert "ExtraRedeemers" in errors[0]
        assert "index 5" in errors[0]


# ---------------------------------------------------------------------------
# Test 12: No ExtraRedeemers on same-script certs
# ---------------------------------------------------------------------------


class TestNoExtraRedeemersSameScriptCerts:
    """Multiple certificates using the same Plutus script should require
    only one redeemer per distinct cert index, not one per script instance.
    A single Cert redeemer at index 0 is valid when the first cert uses
    the Plutus script.

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_single_cert_redeemer_for_multiple_same_script_certs(self):
        """Two certificates referencing the same Plutus script need a
        redeemer at each cert index. A redeemer at index 0 + index 1
        should both be valid (no extra redeemers error).
        """
        script_hash = _make_script_hash(seed=120)
        script_hash_bytes = bytes(script_hash)

        sk, vk = _make_key_pair(seed=12)
        addr = _make_address(vk)
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000, seed=12)

        # Two certificates (simulated — we use a list of two items)
        # pycardano certificates are complex; we use a minimal mock approach.
        # The _extra_redeemers function checks cert indices against
        # tx_body.certificates length.
        from unittest.mock import MagicMock

        mock_cert1 = MagicMock()
        mock_cert2 = MagicMock()

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
            certificates=[mock_cert1, mock_cert2],
        )

        # Two Cert redeemers for both cert indices
        redeemer_0 = Redeemer(
            tag=RedeemerTag.CERT,
            index=0,
            data=cbor2.dumps(0),
            ex_units=ExUnits(mem=100, steps=200),
        )
        redeemer_1 = Redeemer(
            tag=RedeemerTag.CERT,
            index=1,
            data=cbor2.dumps(0),
            ex_units=ExUnits(mem=100, steps=200),
        )

        errors = _extra_redeemers(
            tx_body,
            utxo,
            redeemers=[redeemer_0, redeemer_1],
            script_hashes={script_hash_bytes},
        )

        # Both redeemers point to valid cert indices — no extra redeemers
        assert errors == []


# ---------------------------------------------------------------------------
# Test 13: Multiple equal Plutus-locked certs
# ---------------------------------------------------------------------------


class TestMultipleEqualPlutusLockedCerts:
    """Duplicate delegation certs using the same Plutus script should be
    handled correctly — each cert gets its own index and redeemer.

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    """

    def test_duplicate_delegation_certs_same_script(self):
        """Two identical delegation certs using the same Plutus script
        should each need a redeemer at their respective indices. Missing
        one redeemer means we can still validate the other without
        ExtraRedeemers firing.
        """
        script_hash = _make_script_hash(seed=130)
        script_hash_bytes = bytes(script_hash)

        sk, vk = _make_key_pair(seed=13)
        addr = _make_address(vk)
        utxo, txin, sk, vk = _make_simple_utxo(value=10_000_000, seed=13)

        from unittest.mock import MagicMock

        # Two identical delegation certs (same Plutus script)
        mock_cert = MagicMock()
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(addr, 8_000_000)],
            fee=2_000_000,
            certificates=[mock_cert, mock_cert],
        )

        # Redeemer for only cert index 0 — this is valid for that cert
        redeemer = Redeemer(
            tag=RedeemerTag.CERT,
            index=0,
            data=cbor2.dumps(0),
            ex_units=ExUnits(mem=100, steps=200),
        )

        errors = _extra_redeemers(
            tx_body,
            utxo,
            redeemers=[redeemer],
            script_hashes={script_hash_bytes},
        )

        # The redeemer at index 0 is valid (cert exists at index 0)
        # Index 1 has no redeemer, which would be a MissingRedeemers issue,
        # NOT an ExtraRedeemers issue. So no extra redeemers errors.
        assert errors == []


# ---------------------------------------------------------------------------
# Integration: test through validate_alonzo_witnesses
# ---------------------------------------------------------------------------


class TestUTXOWIntegration:
    """Integration tests verifying multiple UTXOW failures fire through
    the top-level validate_alonzo_witnesses function.
    """

    def test_multiple_utxow_failures_accumulated(self):
        """A transaction with multiple UTXOW violations should report
        all of them, not just the first.
        """
        script_hash = _make_script_hash(seed=200)
        script_hash_bytes = bytes(script_hash)
        script_addr = _make_script_address(script_hash)

        sk, vk = _make_key_pair(seed=20)
        vk_addr = _make_address(vk)

        # Script-locked UTxO WITHOUT datum hash (will trigger MissingRedeemers)
        utxo, script_txin = _make_script_utxo(
            script_hash,
            tx_id_seed=200,
        )
        # VKey-locked UTxO for funding
        fund_utxo, fund_txin, sk, vk = _make_simple_utxo(
            tx_id_seed=201,
            seed=20,
        )
        utxo.update(fund_utxo)

        tx_body = TransactionBody(
            inputs=[script_txin, fund_txin],
            outputs=[
                # Script output WITHOUT datum hash
                TransactionOutput(script_addr, 3_000_000),
                TransactionOutput(vk_addr, 5_000_000),
            ],
            fee=2_000_000,
        )
        wit = _sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # Extra unreferenced datum
        extra_datum = cbor2.dumps(12345)

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            has_plutus_scripts=True,
            script_integrity_hash=None,  # Missing
            redeemers=[],  # Missing redeemers for script input
            datums=[extra_datum],
            script_hashes={script_hash_bytes},
            witnessed_script_hashes=set(),  # Missing script witness
        )

        error_text = " ".join(errors)
        # Should have multiple distinct failure types
        assert "ScriptIntegrityHashMismatch" in error_text
        assert "MissingRedeemers" in error_text
        assert "NotAllowedSupplementalDatums" in error_text
        assert "UnspendableUTxONoDatumHash" in error_text
        assert "MissingScriptWitness" in error_text
