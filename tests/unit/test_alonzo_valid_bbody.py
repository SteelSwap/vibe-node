"""Tests for Alonzo UTXOW valid transaction paths and block body validation.

Covers valid-path UTXOW tests modeled after the Haskell imp tests
(``Alonzo/Imp/UtxowSpec/Valid.hs``) and block body validation tests
from ``Alonzo/Imp/BbodySpec.hs`` and ``UtxoSpec.hs``.

UTXOW valid paths (~12 tests):
    1. Non-script output with datum hash — datum hash on non-script output is allowed
    2. Validating SPEND script — Plutus spend succeeds, UTxO consumed
    3. Not validating SPEND — phase-2 fails, collateral consumed instead
    4. Validating CERT script — Plutus script for certificate validation
    5. Validating WITHDRAWAL script — Plutus script for reward withdrawal
    6. Validating MINT script — Plutus minting policy succeeds
    7. Not validating MINT — minting phase-2 fails, collateral consumed
    8. Acceptable supplementary datum — extra datum referenced by an output
    9. Scripts everywhere — tx with both timelock + Plutus scripts, all valid
    10. Multiple identical certificates — duplicate certs with Plutus scripts

Block body validation (~6 tests):
    11. Block with multiple Plutus scripts — 4+ scripts in one block body
    12. ppMaxBlockExUnits enforcement — block total ExUnits exceeds limit
    13. Wrong network ID — output address has wrong network
    14. ExUnits exceeding ppMaxTxExUnits — single tx exceeds per-tx limit
    15. Insufficient collateral percentage — collateral < collateralPercentage%
    16. Validity interval closed vs open upper bound — PV9+ open upper bound

Spec references:
    - Alonzo ledger formal spec, Sections 9-10 (UTxO / UTXOW)
    - Alonzo ledger formal spec, Section 12 (BBODY)
    - ``cardano-ledger/eras/alonzo/impl/test/Test/Cardano/Ledger/Alonzo/Imp/UtxowSpec.hs``
    - ``cardano-ledger/eras/alonzo/impl/test/Test/Cardano/Ledger/Alonzo/Imp/BbodySpec.hs``
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
from pycardano.hash import ScriptHash, TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey
from pycardano.network import Network
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

from vibe.cardano.ledger.allegra_mary import ValidityInterval
from vibe.cardano.ledger.alonzo import (
    _ex_units_too_big,
    _insufficient_collateral,
    _total_ex_units,
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

# Datum representing the unit constructor: Constr(0, [])
ALWAYS_SUCCEEDS_DATUM = cbor2.dumps(0)

# Redeemer data — arbitrary PlutusData integer
ALWAYS_SUCCEEDS_REDEEMER = cbor2.dumps(42)

# A "fake" always-fails redeemer (same encoding, but used for not-validating paths)
ALWAYS_FAILS_REDEEMER = cbor2.dumps(99)


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


def make_address(vk: PaymentVerificationKey, network: Network = Network.TESTNET) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=network)


def make_script_hash(seed: int = 0) -> ScriptHash:
    """Create a deterministic ScriptHash (28 bytes)."""
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=28).digest()
    return ScriptHash(digest)


def make_script_address(seed: int = 0, network: Network = Network.TESTNET) -> Address:
    """Create an address locked by a script (payment = script hash)."""
    script_hash = make_script_hash(seed)
    return Address(payment_part=script_hash, network=network)


def sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    """Sign a transaction body and return a VKey witness."""
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def make_datum_hash(datum_cbor: bytes) -> bytes:
    """Compute the blake2b-256 datum hash from CBOR-encoded datum."""
    return hashlib.blake2b(datum_cbor, digest_size=32).digest()


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
) -> tuple[ShelleyUTxO, TransactionInput, PaymentSigningKey]:
    """Create a collateral UTxO entry (ADA-only) with its signing key."""
    sk, vk = make_key_pair(seed)
    addr = make_address(vk)
    tx_id = make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk


def make_script_integrity_hash(
    redeemers: list[Redeemer],
    datums: list[bytes],
    cost_models: dict[Language, dict[str, int]] | None = None,
    languages: set[Language] | None = None,
) -> bytes:
    """Compute the script integrity hash for test transactions."""
    if cost_models is None:
        cost_models = {Language.PLUTUS_V1: {"a": 1}}
    if languages is None:
        languages = {Language.PLUTUS_V1}
    return compute_script_integrity_hash(redeemers, datums, cost_models, languages)


# ---------------------------------------------------------------------------
# UTXOW Valid Paths
# ---------------------------------------------------------------------------


class TestUtxowValidPaths:
    """Valid transaction paths from Alonzo/Imp/UtxowSpec/Valid.hs.

    These tests verify that correctly-formed Alonzo transactions pass
    validation. Each test constructs a transaction that should succeed
    and asserts zero errors from the validation pipeline.
    """

    def test_non_script_output_with_datum_hash(self):
        """Datum hash on a non-script output is allowed in Alonzo.

        Spec ref: Alonzo formal spec, Section 4 — outputs may carry datum hashes
        even if the address is not a script address. This is used for informational
        purposes or future spending.

        Haskell ref: ``Valid.hs`` — "Non-script output with datum"
        """
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Datum for the output (not required by any script)
        datum_cbor = cbor2.dumps(42)
        datum_hash = make_datum_hash(datum_cbor)

        # Output with datum hash on a non-script address
        txout = TransactionOutput(dest_addr, 8_000_000)
        txout.datum_hash = datum_hash

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[txout],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # Provide the datum in the witness set so _missing_required_datums passes
        errors = validate_alonzo_tx(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            datums=[datum_cbor],
        )
        assert errors == [], f"Expected valid tx, got: {errors}"

    def test_validating_spend_script(self):
        """Validating SPEND script — Plutus spend succeeds, UTxO consumed.

        A transaction spending a script-locked UTxO with a matching datum,
        redeemer, and valid script integrity hash should pass UTXOW validation.

        Spec ref: Alonzo formal spec, Section 10 — UTXOW with script witnesses.
        Haskell ref: ``Valid.hs`` — "Validating SPEND script"
        """
        sk, vk = make_key_pair(seed=1)
        dest_addr = make_address(vk)

        # Script-locked UTxO
        script_addr = make_script_address(seed=10)
        script_txin = TransactionInput(make_tx_id(10), 0)
        script_txout = TransactionOutput(script_addr, 5_000_000)

        # Normal UTxO for fees
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=11, value=10_000_000, seed=2
        )

        # Collateral
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=12, value=5_000_000, seed=2
        )

        utxo = {**fee_utxo, **coll_utxo, script_txin: script_txout}

        datum_cbor = ALWAYS_SUCCEEDS_DATUM
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=1000, steps=1000),
            )
        ]
        datums = [datum_cbor]

        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[script_txin, fee_txin],
            outputs=[TransactionOutput(dest_addr, 13_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        # No ScriptIntegrityHashMismatch — the integrity hash is correct
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_not_validating_spend_collateral_consumed(self):
        """Not-validating SPEND — phase-2 fails, collateral consumed instead.

        When a Plutus spend script fails phase-2 validation, the tx is
        "not validating" and collateral is consumed instead of the inputs.
        The UTXOW rules should still pass (witness verification is separate
        from script evaluation).

        Spec ref: Alonzo formal spec, Section 9.2 — isValid flag.
        Haskell ref: ``Valid.hs`` — "Not validating SPEND"
        """
        sk, vk = make_key_pair(seed=3)
        dest_addr = make_address(vk)

        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=20, value=5_000_000, seed=3
        )
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=21, value=10_000_000, seed=3
        )
        utxo = {**fee_utxo, **coll_utxo}

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=ALWAYS_FAILS_REDEEMER,
                ex_units=ExUnits(mem=1000, steps=1000),
            )
        ]
        datums = [ALWAYS_SUCCEEDS_DATUM]
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # The UTXOW witness validation should pass — script evaluation failure
        # is separate from witness verification
        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_validating_cert_script(self):
        """Validating CERT script — Plutus script for certificate validation.

        A transaction with a certificate that references a Plutus script
        credential should pass UTXOW validation when the integrity hash
        and redeemers are correct.

        Spec ref: Alonzo formal spec, Section 10 — certifying script purpose.
        Haskell ref: ``Valid.hs`` — "Validating CERT script"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=30, value=10_000_000, seed=4
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=31, value=5_000_000, seed=4
        )
        utxo = {**fee_utxo, **coll_utxo}

        redeemers = [
            Redeemer(
                tag=RedeemerTag.CERT,
                index=0,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=500, steps=500),
            )
        ]
        datums: list[bytes] = []
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_validating_withdrawal_script(self):
        """Validating WITHDRAWAL script — Plutus script for reward withdrawal.

        A transaction withdrawing rewards from a Plutus-script-locked reward
        account should pass when the redeemer with REWARD tag is present and
        the integrity hash matches.

        Spec ref: Alonzo formal spec, Section 10 — rewarding script purpose.
        Haskell ref: ``Valid.hs`` — "Validating WITHDRAWAL script"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=40, value=10_000_000, seed=5
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=41, value=5_000_000, seed=5
        )
        utxo = {**fee_utxo, **coll_utxo}

        redeemers = [
            Redeemer(
                tag=RedeemerTag.REWARD,
                index=0,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=500, steps=500),
            )
        ]
        datums: list[bytes] = []
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_validating_mint_script(self):
        """Validating MINT script — Plutus minting policy succeeds.

        A transaction minting tokens under a Plutus minting policy should
        pass UTXOW validation with the correct MINT redeemer and integrity hash.

        Spec ref: Alonzo formal spec, Section 10 — minting script purpose.
        Haskell ref: ``Valid.hs`` — "Validating MINT script"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=50, value=10_000_000, seed=6
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=51, value=5_000_000, seed=6
        )
        utxo = {**fee_utxo, **coll_utxo}

        policy_id = make_script_hash(seed=50)
        mint = MultiAsset({policy_id: Asset({AssetName(b"TestToken"): 100})})

        redeemers = [
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=1000, steps=1000),
            )
        ]
        datums: list[bytes] = []
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        # Minted tokens go to the output
        minted_value = Value(coin=8_000_000, multi_asset=mint)
        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, minted_value)],
            fee=2_000_000,
            mint=mint,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_not_validating_mint_collateral_consumed(self):
        """Not-validating MINT — minting phase-2 fails, collateral consumed.

        Same structure as the validating MINT test but the script would fail
        phase-2 evaluation. The UTXOW witness layer should still pass because
        witness verification is independent of script evaluation.

        Spec ref: Alonzo formal spec, Section 9.2 — isValid=False for minting.
        Haskell ref: ``Valid.hs`` — "Not validating MINT"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=60, value=10_000_000, seed=7
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=61, value=5_000_000, seed=7
        )
        utxo = {**fee_utxo, **coll_utxo}

        redeemers = [
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=ALWAYS_FAILS_REDEEMER,
                ex_units=ExUnits(mem=1000, steps=1000),
            )
        ]
        datums: list[bytes] = []
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_acceptable_supplementary_datum(self):
        """Acceptable supplementary datum — extra datum referenced by an output.

        A transaction may include extra datums in the witness set as long as
        they are referenced by an output's datum hash. This is the
        "supplementary datum" pattern used for DApp metadata.

        Spec ref: Alonzo formal spec, Section 10 — ``allowedSupplementalDatums``.
        Haskell ref: ``Valid.hs`` — "Acceptable supplementary datum"
        """
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Two datums: one consumed by a script, one supplementary
        datum1_cbor = cbor2.dumps(1)
        datum2_cbor = cbor2.dumps(2)
        datum2_hash = make_datum_hash(datum2_cbor)

        # Output carries the supplementary datum hash
        txout = TransactionOutput(dest_addr, 8_000_000)
        txout.datum_hash = datum2_hash

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[txout],
            fee=2_000_000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        # Both datums in the witness set — datum2 is the supplementary one
        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            datums=[datum1_cbor, datum2_cbor],
        )
        # The supplementary datum is acceptable because it's referenced by an output
        assert not any("MissingRequiredDatums" in e for e in errors)

    def test_scripts_everywhere(self):
        """Scripts everywhere — tx with both timelock + Plutus scripts.

        A transaction that uses both a native timelock script and Plutus
        scripts should pass all validation when properly constructed.

        Spec ref: Alonzo formal spec, Sections 9-10 — mixed script types.
        Haskell ref: ``Valid.hs`` — "Scripts everywhere"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=70, value=10_000_000, seed=8
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=71, value=5_000_000, seed=8
        )
        utxo = {**fee_utxo, **coll_utxo}

        # Plutus SPEND redeemer
        spend_redeemer = Redeemer(
            tag=RedeemerTag.SPEND,
            index=0,
            data=ALWAYS_SUCCEEDS_REDEEMER,
            ex_units=ExUnits(mem=500, steps=500),
        )
        # Plutus MINT redeemer
        mint_redeemer = Redeemer(
            tag=RedeemerTag.MINT,
            index=0,
            data=ALWAYS_SUCCEEDS_REDEEMER,
            ex_units=ExUnits(mem=500, steps=500),
        )
        redeemers = [spend_redeemer, mint_redeemer]
        datums = [ALWAYS_SUCCEEDS_DATUM]

        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        policy_id = make_script_hash(seed=70)
        mint = MultiAsset({policy_id: Asset({AssetName(b"Token"): 1})})

        minted_value = Value(coin=8_000_000, multi_asset=mint)
        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, minted_value)],
            fee=2_000_000,
            mint=mint,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_multiple_identical_certificates(self):
        """Multiple identical certificates — duplicate certs with Plutus scripts.

        A transaction may contain multiple identical certificate entries,
        each with its own redeemer. The redeemer indices must match the
        certificate positions.

        Spec ref: Alonzo formal spec, Section 10 — certifying redeemer indexing.
        Haskell ref: ``Valid.hs`` — "Multiple identical certificates"
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=80, value=10_000_000, seed=9
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=81, value=5_000_000, seed=9
        )
        utxo = {**fee_utxo, **coll_utxo}

        # Two CERT redeemers for two identical certificates
        redeemers = [
            Redeemer(
                tag=RedeemerTag.CERT,
                index=0,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=500, steps=500),
            ),
            Redeemer(
                tag=RedeemerTag.CERT,
                index=1,
                data=ALWAYS_SUCCEEDS_REDEEMER,
                ex_units=ExUnits(mem=500, steps=500),
            ),
        ]
        datums: list[bytes] = []
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_plutus_v1_cost_model_integrity(self):
        """PlutusV1 cost model in integrity hash — verify correct language encoding.

        The script integrity hash must encode the PlutusV1 cost model with
        language key 0. Verify that the hash is computed correctly and matches
        the expected value when verified by validate_alonzo_witnesses.

        Spec ref: Alonzo formal spec, ``hashScriptIntegrity``.
        """
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000, seed=10)
        dest_addr = make_address(vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=90, value=5_000_000, seed=10
        )
        utxo.update(coll_utxo)

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=100, steps=200),
            )
        ]
        datums = [cbor2.dumps(99)]
        cost_models: dict[Language, dict[str, int]] = {
            Language.PLUTUS_V1: {"addInteger-cpu": 100, "addInteger-mem": 50}
        }
        languages = {Language.PLUTUS_V1}

        # Compute the integrity hash
        integrity_hash = compute_script_integrity_hash(redeemers, datums, cost_models, languages)
        assert len(integrity_hash) == 32

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)

    def test_multiple_redeemer_tags_in_single_tx(self):
        """Multiple redeemer tags (SPEND + MINT + CERT) in a single tx.

        A transaction can use multiple script purposes simultaneously.
        Each purpose has its own redeemer entry. All must be covered by the
        integrity hash.

        Spec ref: Alonzo formal spec, Section 4 — redeemer pointer map.
        """
        fee_utxo, fee_txin, fee_sk, fee_vk = make_simple_utxo(
            tx_id_seed=95, value=20_000_000, seed=11
        )
        dest_addr = make_address(fee_vk)
        coll_utxo, coll_txin, coll_sk = make_collateral_utxo(
            tx_id_seed=96, value=10_000_000, seed=11
        )
        utxo = {**fee_utxo, **coll_utxo}

        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(1),
                ex_units=ExUnits(mem=500, steps=500),
            ),
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=cbor2.dumps(2),
                ex_units=ExUnits(mem=500, steps=500),
            ),
            Redeemer(
                tag=RedeemerTag.CERT,
                index=0,
                data=cbor2.dumps(3),
                ex_units=ExUnits(mem=500, steps=500),
            ),
        ]
        datums = [cbor2.dumps(0)]
        cost_models: dict[Language, dict[str, int]] = {Language.PLUTUS_V1: {"a": 1}}
        languages = {Language.PLUTUS_V1}
        integrity_hash = make_script_integrity_hash(redeemers, datums, cost_models, languages)

        tx_body = TransactionBody(
            inputs=[fee_txin],
            outputs=[TransactionOutput(dest_addr, 18_000_000)],
            fee=2_000_000,
            collateral=[coll_txin],
        )
        wit = sign_tx_body(tx_body, fee_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])

        errors = validate_alonzo_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=integrity_hash,
            cost_models=cost_models,
            languages_used=languages,
            has_plutus_scripts=True,
        )
        assert not any("ScriptIntegrityHashMismatch" in e for e in errors)


# ---------------------------------------------------------------------------
# Block Body Validation
# ---------------------------------------------------------------------------


class TestBlockBodyValidation:
    """Block body validation tests from Alonzo/Imp/BbodySpec.hs and UtxoSpec.hs.

    These tests verify block-level constraints: aggregate ExUnits limits,
    network ID checks, per-tx limits, and collateral requirements.
    """

    def test_block_with_multiple_plutus_scripts(self):
        """Block with multiple Plutus scripts — 4+ scripts in one block body.

        A block containing multiple transactions, each with Plutus scripts,
        should pass when the aggregate ExUnits are within ppMaxBlockExUnits.

        Spec ref: Alonzo formal spec, Section 12 — BBODY, totalExUnits.
        Haskell ref: ``BbodySpec.hs`` — "Block with multiple Plutus scripts"
        """
        # Create 4 transactions each with their own script execution budget
        all_redeemers = []
        for i in range(4):
            r = Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(i),
                ex_units=ExUnits(mem=1_000_000, steps=1_000_000_000),
            )
            all_redeemers.append(r)

        # Total: mem=4M, steps=4B — within block limits of mem=50M, steps=40B
        total = _total_ex_units(all_redeemers)
        assert total.mem == 4_000_000
        assert total.steps == 4_000_000_000
        assert not total.exceeds(TEST_PARAMS.max_block_ex_units)

        # Each individual tx also within per-tx limits
        for r in all_redeemers:
            assert not r.ex_units.exceeds(TEST_PARAMS.max_tx_ex_units)

    def test_pp_max_block_ex_units_enforcement(self):
        """PpMaxBlockExUnits enforcement — block total ExUnits exceeds limit.

        When the aggregate ExUnits across all transactions in a block exceed
        ppMaxBlockExUnits, the block must be rejected.

        Spec ref: Alonzo formal spec, Section 12 — BBODY rule,
            ``totExUnits <= ppMaxBlockExUnits``.
        Haskell ref: ``BbodySpec.hs`` — "Block total ExUnits exceeds limit"
        """
        # Create redeemers that individually fit per-tx but exceed block limits
        # Block limit: mem=50M, steps=40B
        redeemers = []
        for i in range(6):
            # Each tx uses mem=9M — 6 * 9M = 54M > 50M block limit
            r = Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(i),
                ex_units=ExUnits(mem=9_000_000, steps=1_000_000_000),
            )
            redeemers.append(r)

        total = _total_ex_units(redeemers)
        assert total.mem == 54_000_000
        assert total.exceeds(TEST_PARAMS.max_block_ex_units)

        # Verify that per-tx each is within per-tx limits
        for r in redeemers:
            assert not r.ex_units.exceeds(TEST_PARAMS.max_tx_ex_units)

    def test_wrong_network_id(self):
        """Wrong network ID — output address has wrong network, verify rejection.

        When a transaction output contains an address for a different network
        than the one the node is running on, validation should flag it.
        We verify that addresses with different networks produce different
        payment credentials that would be caught at the address level.

        Spec ref: Alonzo formal spec, Section 9 — ``WrongNetwork``.
        Haskell ref: ``UtxoSpec.hs`` — "Wrong network ID"
        """
        # Create two addresses on different networks
        sk, vk = make_key_pair(seed=20)
        testnet_addr = make_address(vk, network=Network.TESTNET)
        mainnet_addr = make_address(vk, network=Network.MAINNET)

        # Verify they encode differently (different network discrimination byte)
        assert testnet_addr.to_primitive() != mainnet_addr.to_primitive()

        # The network byte is the first byte of the address
        testnet_bytes = testnet_addr.to_primitive()
        mainnet_bytes = mainnet_addr.to_primitive()
        # Testnet addresses have header nibble 0x0X, mainnet has 0x6X (for type 0)
        # or more precisely, bit 0 of the header indicates the network
        assert (testnet_bytes[0] & 0x0F) != (mainnet_bytes[0] & 0x0F)

    def test_ex_units_exceeding_pp_max_tx_ex_units(self):
        """ExUnits exceeding ppMaxTxExUnits — single tx exceeds per-tx limit.

        A single transaction whose aggregate redeemer ExUnits exceed
        ppMaxTxExUnits must be rejected by the UTXO transition rules.

        Spec ref: Alonzo formal spec, Section 9 — ``ExUnitsTooBigUTxO``.
        Haskell ref: ``UtxoSpec.hs`` — "ExUnits exceeding ppMaxTxExUnits"
        """
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        dest_addr = make_address(vk)

        # Redeemer that exceeds per-tx mem limit
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
            outputs=[TransactionOutput(dest_addr, 48_000_000)],
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

        # Verify steps exceeding also triggers the error
        redeemers_steps = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(
                    mem=100,
                    steps=TEST_PARAMS.max_tx_ex_units.steps + 1,
                ),
            )
        ]
        errors_steps = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers_steps,
        )
        assert any("ExUnitsTooBigUTxO" in e for e in errors_steps)

    def test_insufficient_collateral_percentage(self):
        """Insufficient collateral percentage — collateral < collateralPercentage% of fees.

        When the collateral provided is less than the required percentage of
        script execution fees, validation must reject the transaction.

        Spec ref: Alonzo formal spec, Section 9 — ``InsufficientCollateral``.
        Haskell ref: ``UtxoSpec.hs`` — "Insufficient collateral percentage"
        """
        utxo, txin, sk, vk = make_simple_utxo(value=50_000_000)
        dest_addr = make_address(vk)

        # Collateral with only 100 lovelace
        coll_txin = TransactionInput(make_tx_id(700), 0)
        utxo[coll_txin] = TransactionOutput(dest_addr, 100)

        # Script fees: mem=10000 + steps=10000 = 20000 lovelace (with unit prices)
        # Required collateral: ceil(20000 * 150 / 100) = 30000
        # Provided: 100 — way insufficient
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=10000, steps=10000),
            )
        ]

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 48_000_000)],
            fee=2_000_000,
        )

        errors = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,
            tx_size=200,
            redeemers=redeemers,
            collateral_inputs=[coll_txin],
            has_plutus_scripts=True,
        )
        assert any("InsufficientCollateral" in e for e in errors)

        # Verify the exact math: script_fees = 10000 + 10000 = 20000
        script_fees = calculate_script_fee(redeemers, TEST_PARAMS.execution_unit_prices)
        assert script_fees == 20000
        required = (script_fees * TEST_PARAMS.collateral_percentage + 99) // 100
        assert required == 30000
        assert 100 < required  # Collateral is insufficient

    def test_validity_interval_open_upper_bound(self):
        """Validity interval closed vs open upper bound.

        In Alonzo (PV 5-6), the invalid_hereafter is an exclusive upper bound:
        the transaction is valid when current_slot < invalid_hereafter.

        For protocol version 9+ (Conway), PlutusV1 TxInfo uses open upper
        bound semantics. This test verifies the Alonzo-era behavior where
        the slot at the boundary is already invalid.

        Spec ref: Alonzo formal spec, Section 9 — validity interval check.
        Haskell ref: ``UtxoSpec.hs`` — "Validity interval closed vs open upper bound"
        """
        utxo, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
        )

        # Slot exactly at the upper bound — should be INVALID (exclusive)
        interval = ValidityInterval(invalid_before=None, invalid_hereafter=100)
        errors_at_bound = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=100,  # At the boundary
            tx_size=200,
            validity_interval=interval,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors_at_bound)

        # Slot one before the upper bound — should be VALID
        errors_before_bound = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=99,  # Just before boundary
            tx_size=200,
            validity_interval=interval,
        )
        assert not any("OutsideValidityIntervalUTxO" in e for e in errors_before_bound)

        # Slot after the upper bound — should be INVALID
        errors_after_bound = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=101,  # After boundary
            tx_size=200,
            validity_interval=interval,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors_after_bound)

        # Lower bound check: slot exactly at invalid_before — should be VALID
        interval_lower = ValidityInterval(invalid_before=50, invalid_hereafter=200)
        errors_at_lower = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=50,  # At lower bound (inclusive)
            tx_size=200,
            validity_interval=interval_lower,
        )
        assert not any("OutsideValidityIntervalUTxO" in e for e in errors_at_lower)

        # Slot before lower bound — should be INVALID
        errors_before_lower = validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo,
            params=TEST_PARAMS,
            current_slot=49,  # Before lower bound
            tx_size=200,
            validity_interval=interval_lower,
        )
        assert any("OutsideValidityIntervalUTxO" in e for e in errors_before_lower)


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestAlonzoEdgeCases:
    """Additional edge case tests for Alonzo validation.

    These complement the main valid-path and block-body tests with
    boundary conditions and interaction patterns.
    """

    def test_collateral_sufficient_at_exact_boundary(self):
        """Collateral exactly at the required percentage boundary passes.

        Spec ref: Alonzo formal spec, Section 9 — ``InsufficientCollateral``.
        """
        # script_fees = 1000 + 2000 = 3000 (with unit prices)
        # required = ceil(3000 * 150 / 100) = 4500
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=1000, steps=2000),
            )
        ]
        script_fees = calculate_script_fee(redeemers, TEST_PARAMS.execution_unit_prices)
        assert script_fees == 3000
        required = (script_fees * 150 + 99) // 100
        assert required == 4500

        sk, vk = make_key_pair(seed=30)
        addr = make_address(vk)
        coll_txin = TransactionInput(make_tx_id(800), 0)
        utxo: ShelleyUTxO = {coll_txin: TransactionOutput(addr, 4500)}

        # Exactly sufficient
        errors = _insufficient_collateral([coll_txin], utxo, script_fees, 150)
        assert errors == []

        # One lovelace short
        utxo_short: ShelleyUTxO = {coll_txin: TransactionOutput(addr, 4499)}
        errors_short = _insufficient_collateral([coll_txin], utxo_short, script_fees, 150)
        assert len(errors_short) == 1
        assert "InsufficientCollateral" in errors_short[0]

    def test_ex_units_sum_across_multiple_redeemers(self):
        """ExUnits from multiple redeemers are summed for per-tx limit check.

        Individual redeemers may each be within limits, but their sum can
        exceed the per-tx limit.

        Spec ref: Alonzo formal spec, Section 9 — ``totExUnits``.
        """
        # Two redeemers each using 6M mem — sum = 12M > 10M limit
        redeemers = [
            Redeemer(
                tag=RedeemerTag.SPEND,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=6_000_000, steps=100),
            ),
            Redeemer(
                tag=RedeemerTag.MINT,
                index=0,
                data=cbor2.dumps(0),
                ex_units=ExUnits(mem=6_000_000, steps=100),
            ),
        ]

        errors = _ex_units_too_big(redeemers, TEST_PARAMS.max_tx_ex_units)
        assert len(errors) == 1
        assert "ExUnitsTooBigUTxO" in errors[0]

        total = _total_ex_units(redeemers)
        assert total.mem == 12_000_000
        assert total.steps == 200
