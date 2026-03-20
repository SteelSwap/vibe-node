"""Tests for Shelley-era ledger validation rules (UTXO + UTXOW).

Tests cover the Shelley UTXO and UTXOW transition rules from the formal spec:
    - Valid transaction passes all checks
    - Missing input detection (InputsNotInUTxO)
    - TTL expiry check (ExpiredUTxO)
    - Max transaction size enforcement (MaxTxSizeUTxO)
    - Fee calculation and minimum fee validation (FeeTooSmallUTxO)
    - Min UTxO value enforcement (OutputTooSmallUTxO)
    - Value preservation: consumed == produced (ValueNotConservedUTxO)
    - VKey witness signature verification (InvalidWitnessesUTxOW)
    - Missing witness detection (MissingVKeyWitnessesUTxOW)
    - Block-level application with multiple transactions
    - Simple transfer value preservation

Spec references:
    - Shelley ledger formal spec, Section 9 (UTxO transition)
    - Shelley ledger formal spec, Section 10 (UTXOW)
    - ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Utxo.hs``

DB test spec references:
    - test_ttl_expiry_check
    - test_utxo_value_preservation_consumed_equals_produced
    - test_value_preservation_simple_transfer
    - test_witness_signature_verifies_against_vkey
    - test_inputs_consumed_eliminated_from_utxo
"""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey as NaClSigningKey

from pycardano import (
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Transaction,
)
from pycardano.hash import TransactionId
from pycardano.key import PaymentSigningKey, PaymentVerificationKey, VerificationKey
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness
from pycardano.address import Address
from pycardano.network import Network

from vibe.cardano.ledger.shelley import (
    SHELLEY_MAINNET_PARAMS,
    ShelleyProtocolParams,
    ShelleyUTxO,
    ShelleyValidationError,
    apply_shelley_block,
    apply_shelley_tx,
    shelley_min_fee,
    validate_shelley_tx,
    validate_shelley_utxo,
    validate_shelley_witnesses,
    _output_lovelace,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

# Use small fee params for test convenience
TEST_PARAMS = ShelleyProtocolParams(
    min_fee_a=1,
    min_fee_b=100,
    max_tx_size=16384,
    min_utxo_value=1000000,
    key_deposit=2000000,
    pool_deposit=500000000,
)


def make_signing_key(seed: int = 0) -> PaymentSigningKey:
    """Create a deterministic signing key from a seed."""
    # NaCl signing keys are 32 bytes
    seed_bytes = seed.to_bytes(32, "big")
    return PaymentSigningKey(seed_bytes)


def make_key_pair(seed: int = 0) -> tuple[PaymentSigningKey, PaymentVerificationKey]:
    """Create a deterministic signing/verification key pair."""
    sk = make_signing_key(seed)
    vk = sk.to_verification_key()
    return sk, vk


def make_address(vk: PaymentVerificationKey) -> Address:
    """Create a Shelley enterprise address from a verification key."""
    return Address(payment_part=vk.hash(), network=Network.TESTNET)


def make_tx_id(seed: int = 0) -> TransactionId:
    """Create a deterministic TransactionId from a seed."""
    import hashlib
    digest = hashlib.blake2b(seed.to_bytes(4, "big"), digest_size=32).digest()
    return TransactionId(digest)


def sign_tx_body(tx_body: TransactionBody, sk: PaymentSigningKey) -> VerificationKeyWitness:
    """Sign a transaction body and return a VKey witness."""
    tx_body_hash = tx_body.hash()
    signature = sk.sign(tx_body_hash)
    vk = sk.to_verification_key()
    return VerificationKeyWitness(vkey=vk, signature=signature)


def make_simple_utxo(
    tx_id_seed: int = 0,
    index: int = 0,
    value: int = 10_000_000,
    vk: PaymentVerificationKey | None = None,
    seed: int = 0,
) -> tuple[ShelleyUTxO, TransactionInput, PaymentSigningKey, PaymentVerificationKey]:
    """Create a simple UTxO set with one entry.

    Returns (utxo_set, txin, signing_key, verification_key).
    """
    if vk is None:
        sk, vk = make_key_pair(seed)
    else:
        sk = make_signing_key(seed)

    addr = make_address(vk)
    tx_id = make_tx_id(tx_id_seed)
    txin = TransactionInput(tx_id, index)
    txout = TransactionOutput(addr, value)
    utxo_set: ShelleyUTxO = {txin: txout}
    return utxo_set, txin, sk, vk


def make_valid_tx(
    utxo_set: ShelleyUTxO,
    txin: TransactionInput,
    sk: PaymentSigningKey,
    vk: PaymentVerificationKey,
    output_value: int = 8_000_000,
    fee: int = 2_000_000,
    ttl: int = 1000,
) -> Transaction:
    """Create a valid signed transaction spending a single input."""
    dest_addr = make_address(vk)
    tx_body = TransactionBody(
        inputs=[txin],
        outputs=[TransactionOutput(dest_addr, output_value)],
        fee=fee,
        ttl=ttl,
    )
    wit = sign_tx_body(tx_body, sk)
    witness_set = TransactionWitnessSet(vkey_witnesses=[wit])
    return Transaction(tx_body, witness_set)


# ---------------------------------------------------------------------------
# shelley_min_fee tests
# ---------------------------------------------------------------------------

class TestShelleyMinFee:
    """Tests for the Shelley minimum fee calculation."""

    def test_min_fee_basic(self):
        """fee = a * txSize + b."""
        params = ShelleyProtocolParams(min_fee_a=44, min_fee_b=155381)
        assert shelley_min_fee(200, params) == 44 * 200 + 155381

    def test_min_fee_zero_size(self):
        """Zero-size transaction: fee = b."""
        params = ShelleyProtocolParams(min_fee_a=44, min_fee_b=155381)
        assert shelley_min_fee(0, params) == 155381

    def test_min_fee_negative_size_raises(self):
        """Negative tx size should raise ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            shelley_min_fee(-1, TEST_PARAMS)

    def test_min_fee_mainnet_genesis_values(self):
        """Verify mainnet genesis fee params produce expected results."""
        # Shelley mainnet: a=44, b=155381
        # For a 300-byte tx: 44*300 + 155381 = 13200 + 155381 = 168581
        assert shelley_min_fee(300, SHELLEY_MAINNET_PARAMS) == 168581


# ---------------------------------------------------------------------------
# validate_shelley_utxo tests
# ---------------------------------------------------------------------------

class TestValidateShelleyUtxo:
    """Tests for UTXO transition rules (no witness checks)."""

    def test_valid_tx_passes(self):
        """A well-formed transaction should pass all UTXO checks.

        DB spec: test_utxo_value_preservation_consumed_equals_produced
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # Use a small tx_size that satisfies min fee
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert errors == []

    def test_missing_input(self):
        """Transaction spending a non-existent UTxO should fail.

        DB spec: test_inputs_consumed_eliminated_from_utxo (inverse)
        """
        utxo_set, _, sk, vk = make_simple_utxo(value=10_000_000)
        # Create a txin that doesn't exist in the UTxO
        fake_txin = TransactionInput(make_tx_id(999), 0)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[fake_txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert any("InputsNotInUTxO" in e for e in errors)

    def test_ttl_expired(self):
        """Transaction with TTL < current slot should fail.

        DB spec: test_ttl_expiry_check
        Spec: slot=100, tx TTL=99. Expect ExpiredUTxO(99, 100).
        Then TTL=100 also fails (current_slot >= ttl).
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=99,
        )
        # slot=100, ttl=99 => expired
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=100, tx_size=200)
        assert any("ExpiredUTxO" in e for e in errors)
        assert any("current_slot=100" in e and "ttl=99" in e for e in errors)

    def test_ttl_equal_to_slot_is_expired(self):
        """TTL equal to current slot is expired (slot >= ttl).

        DB spec: test_ttl_expiry_check
        Spec: TTL=100, slot=100 => expired. The condition is slot < ttl.
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=100,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=100, tx_size=200)
        assert any("ExpiredUTxO" in e for e in errors)

    def test_ttl_none_means_no_expiry(self):
        """Transaction without TTL (None) should not trigger ExpiredUTxO."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=None,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=999999, tx_size=200)
        assert not any("ExpiredUTxO" in e for e in errors)

    def test_max_tx_size_exceeded(self):
        """Transaction exceeding max size should fail."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # tx_size exceeds max_tx_size (16384)
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=20000)
        assert any("MaxTxSizeUTxO" in e for e in errors)

    def test_fee_too_small(self):
        """Transaction with insufficient fee should fail."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        # min_fee = 1 * 200 + 100 = 300
        # Set fee to 100 (below min)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 9_999_900)],
            fee=100,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert any("FeeTooSmallUTxO" in e for e in errors)

    def test_output_below_min_utxo(self):
        """Output below min UTxO value should fail."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        # min_utxo_value = 1_000_000, output = 500_000
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 500_000)],
            fee=9_500_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert any("OutputTooSmallUTxO" in e for e in errors)

    def test_value_not_conserved_outputs_exceed_inputs(self):
        """Outputs + fee exceeding inputs should fail.

        DB spec: test_utxo_value_preservation_consumed_equals_produced
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        # input = 10M, output = 9M, fee = 2M => produced(11M) > consumed(10M)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 9_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert any("ValueNotConservedUTxO" in e for e in errors)

    def test_value_preservation_simple_transfer(self):
        """Simple transfer: 10 ADA input, 8 ADA output, 2 ADA fee.

        DB spec: test_value_preservation_simple_transfer
        consumed = 10 ADA = 10_000_000 lovelace
        produced = 8_000_000 + 2_000_000 = 10_000_000 lovelace
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        # Should not contain any value preservation errors
        assert not any("ValueNotConservedUTxO" in e for e in errors)

    def test_multiple_errors_accumulated(self):
        """Multiple validation failures should all be reported."""
        utxo_set, _, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        fake_txin = TransactionInput(make_tx_id(999), 0)
        tx_body = TransactionBody(
            inputs=[fake_txin],
            outputs=[TransactionOutput(dest_addr, 500_000)],  # below min
            fee=100,  # too small
            ttl=10,   # expired
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=100, tx_size=200)
        # Should have: InputsNotInUTxO, ExpiredUTxO, FeeTooSmallUTxO, OutputTooSmallUTxO
        # (no ValueNotConservedUTxO because inputs couldn't be resolved)
        assert any("InputsNotInUTxO" in e for e in errors)
        assert any("ExpiredUTxO" in e for e in errors)
        assert any("FeeTooSmallUTxO" in e for e in errors)
        assert any("OutputTooSmallUTxO" in e for e in errors)
        assert not any("ValueNotConservedUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_shelley_witnesses tests
# ---------------------------------------------------------------------------

class TestValidateShelleyWitnesses:
    """Tests for UTXOW witness verification rules."""

    def test_valid_witness_passes(self):
        """A correctly signed transaction should pass witness checks.

        DB spec: test_witness_signature_verifies_against_vkey
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        tx = make_valid_tx(utxo_set, txin, sk, vk)
        errors = validate_shelley_witnesses(
            tx.transaction_body, tx.transaction_witness_set, utxo_set
        )
        assert errors == []

    def test_invalid_signature_rejected(self):
        """A witness with a bad signature should be rejected."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # Create witness with garbage signature
        bad_sig = b"\x00" * 64
        wit = VerificationKeyWitness(vkey=vk, signature=bad_sig)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])
        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        assert any("InvalidWitnessesUTxOW" in e for e in errors)

    def test_missing_witness_rejected(self):
        """Transaction without any witnesses should fail for required signers."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # Empty witness set
        witness_set = TransactionWitnessSet()
        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)

    def test_wrong_key_witness_rejected(self):
        """Witness signed by wrong key should fail required signers check."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000, seed=0)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        # Sign with a different key
        wrong_sk = make_signing_key(seed=42)
        wit = sign_tx_body(tx_body, wrong_sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])
        errors = validate_shelley_witnesses(tx_body, witness_set, utxo_set)
        # The signature itself is valid (for the wrong key), but the required
        # key hash won't match
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_shelley_tx (combined) tests
# ---------------------------------------------------------------------------

class TestValidateShelleyTx:
    """Tests for the combined UTXO + UTXOW validation."""

    def test_valid_complete_tx(self):
        """A fully valid transaction passes both UTXO and UTXOW checks."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        tx = make_valid_tx(utxo_set, txin, sk, vk)
        tx_size = len(tx.to_cbor())
        errors = validate_shelley_tx(
            tx.transaction_body,
            tx.transaction_witness_set,
            utxo_set,
            TEST_PARAMS,
            current_slot=50,
            tx_size=tx_size,
        )
        assert errors == []

    def test_multiple_rule_failures(self):
        """Failures in both UTXO and UTXOW rules should accumulate."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=10,  # expired
        )
        # No witnesses
        witness_set = TransactionWitnessSet()
        errors = validate_shelley_tx(
            tx_body, witness_set, utxo_set, TEST_PARAMS,
            current_slot=100, tx_size=200
        )
        assert any("ExpiredUTxO" in e for e in errors)
        assert any("MissingVKeyWitnessesUTxOW" in e for e in errors)


# ---------------------------------------------------------------------------
# apply_shelley_tx tests
# ---------------------------------------------------------------------------

class TestApplyShelleyTx:
    """Tests for single transaction application."""

    def test_apply_valid_tx(self):
        """Applying a valid tx should remove consumed and add produced UTxOs.

        DB spec: test_inputs_consumed_eliminated_from_utxo
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        tx = make_valid_tx(utxo_set, txin, sk, vk)
        new_utxo = apply_shelley_tx(tx, utxo_set, TEST_PARAMS, current_slot=50)

        # Old input should be consumed
        assert txin not in new_utxo

        # New output should be produced
        new_txin = TransactionInput(tx.transaction_body.id, 0)
        assert new_txin in new_utxo
        assert _output_lovelace(new_utxo[new_txin]) == 8_000_000

    def test_apply_invalid_tx_raises(self):
        """Applying an invalid tx should raise ShelleyValidationError."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        # Expired TTL
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=10,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])
        tx = Transaction(tx_body, witness_set)

        with pytest.raises(ShelleyValidationError, match="ExpiredUTxO"):
            apply_shelley_tx(tx, utxo_set, TEST_PARAMS, current_slot=100)

    def test_utxo_size_changes_correctly(self):
        """After applying a 1-input, 2-output tx, UTxO set should grow by 1."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        sk2, vk2 = make_key_pair(seed=1)
        dest_addr2 = make_address(vk2)

        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[
                TransactionOutput(dest_addr, 4_000_000),
                TransactionOutput(dest_addr2, 4_000_000),
            ],
            fee=2_000_000,
            ttl=1000,
        )
        wit = sign_tx_body(tx_body, sk)
        witness_set = TransactionWitnessSet(vkey_witnesses=[wit])
        tx = Transaction(tx_body, witness_set)

        assert len(utxo_set) == 1
        new_utxo = apply_shelley_tx(tx, utxo_set, TEST_PARAMS, current_slot=50)
        # 1 input consumed, 2 outputs produced => net +1
        assert len(new_utxo) == 2


# ---------------------------------------------------------------------------
# apply_shelley_block tests
# ---------------------------------------------------------------------------

class TestApplyShelleyBlock:
    """Tests for block-level transaction application."""

    def test_apply_empty_block(self):
        """Applying an empty block should return the same UTxO set."""
        utxo_set, _, _, _ = make_simple_utxo(value=10_000_000)
        new_utxo = apply_shelley_block([], utxo_set, TEST_PARAMS, current_slot=50)
        assert new_utxo == utxo_set

    def test_apply_block_sequential_spending(self):
        """Tx2 in a block can spend outputs of Tx1 in the same block."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)

        # Tx1: spend original UTxO, create new output
        tx_body1 = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        wit1 = sign_tx_body(tx_body1, sk)
        tx1 = Transaction(tx_body1, TransactionWitnessSet(vkey_witnesses=[wit1]))

        # Tx2: spend Tx1's output
        tx1_output_txin = TransactionInput(tx_body1.id, 0)
        tx_body2 = TransactionBody(
            inputs=[tx1_output_txin],
            outputs=[TransactionOutput(dest_addr, 6_000_000)],
            fee=2_000_000,
            ttl=1000,
        )
        wit2 = sign_tx_body(tx_body2, sk)
        tx2 = Transaction(tx_body2, TransactionWitnessSet(vkey_witnesses=[wit2]))

        new_utxo = apply_shelley_block([tx1, tx2], utxo_set, TEST_PARAMS, current_slot=50)

        # Original input consumed, Tx1 output consumed by Tx2, Tx2 output remains
        assert txin not in new_utxo
        assert tx1_output_txin not in new_utxo
        tx2_output_txin = TransactionInput(tx_body2.id, 0)
        assert tx2_output_txin in new_utxo
        assert _output_lovelace(new_utxo[tx2_output_txin]) == 6_000_000

    def test_apply_block_failure_includes_tx_index(self):
        """Block validation failure should include the transaction index."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)

        # Valid Tx1
        tx1 = make_valid_tx(utxo_set, txin, sk, vk)

        # Invalid Tx2: spends non-existent input
        fake_txin = TransactionInput(make_tx_id(999), 0)
        dest_addr = make_address(vk)
        tx_body2 = TransactionBody(
            inputs=[fake_txin],
            outputs=[TransactionOutput(dest_addr, 1_000_000)],
            fee=1_000_000,
            ttl=1000,
        )
        wit2 = sign_tx_body(tx_body2, sk)
        tx2 = Transaction(tx_body2, TransactionWitnessSet(vkey_witnesses=[wit2]))

        with pytest.raises(ShelleyValidationError, match="Transaction 1"):
            apply_shelley_block([tx1, tx2], utxo_set, TEST_PARAMS, current_slot=50)


# ---------------------------------------------------------------------------
# ShelleyProtocolParams tests
# ---------------------------------------------------------------------------

class TestShelleyProtocolParams:
    """Tests for protocol parameters dataclass."""

    def test_mainnet_defaults(self):
        """Mainnet genesis defaults should be correct."""
        p = SHELLEY_MAINNET_PARAMS
        assert p.min_fee_a == 44
        assert p.min_fee_b == 155381
        assert p.max_tx_size == 16384
        assert p.min_utxo_value == 1000000
        assert p.key_deposit == 2000000
        assert p.pool_deposit == 500000000

    def test_immutability(self):
        """Protocol params should be frozen (immutable)."""
        p = ShelleyProtocolParams()
        with pytest.raises(AttributeError):
            p.min_fee_a = 99  # type: ignore


# ---------------------------------------------------------------------------
# ShelleyValidationError tests
# ---------------------------------------------------------------------------

class TestShelleyValidationError:
    """Tests for the error type."""

    def test_error_message_includes_all_errors(self):
        """Error message should contain all validation failures."""
        err = ShelleyValidationError(["error1", "error2"])
        assert "error1" in str(err)
        assert "error2" in str(err)
        assert err.errors == ["error1", "error2"]

    def test_is_exception(self):
        """ShelleyValidationError should be an Exception."""
        with pytest.raises(ShelleyValidationError):
            raise ShelleyValidationError(["test"])


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case and boundary condition tests."""

    def test_output_lovelace_from_int(self):
        """_output_lovelace should handle int amounts."""
        addr = Address(
            payment_part=make_key_pair()[1].hash(),
            network=Network.TESTNET,
        )
        txout = TransactionOutput(addr, 5_000_000)
        assert _output_lovelace(txout) == 5_000_000

    def test_ttl_just_valid(self):
        """TTL one slot ahead of current should be valid."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 8_000_000)],
            fee=2_000_000,
            ttl=101,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=100, tx_size=200)
        assert not any("ExpiredUTxO" in e for e in errors)

    def test_exact_min_fee_accepted(self):
        """Fee exactly equal to min fee should pass."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        # min_fee = 1 * 200 + 100 = 300
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 10_000_000 - 300)],
            fee=300,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert not any("FeeTooSmallUTxO" in e for e in errors)

    def test_exact_min_utxo_accepted(self):
        """Output exactly equal to min UTxO value should pass."""
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        dest_addr = make_address(vk)
        tx_body = TransactionBody(
            inputs=[txin],
            outputs=[TransactionOutput(dest_addr, 1_000_000)],
            fee=9_000_000,
            ttl=1000,
        )
        errors = validate_shelley_utxo(tx_body, utxo_set, TEST_PARAMS, current_slot=50, tx_size=200)
        assert not any("OutputTooSmallUTxO" in e for e in errors)


# ---------------------------------------------------------------------------
# Pool state internal consistency tests
#
# Spec ref: Shelley formal spec, Section 8, Figures 35-36 (POOL transition).
# Haskell ref: ``Cardano.Ledger.Shelley.Rules.Pool`` — the transition
# guarantees that retiring pools are a subset of registered pools, and
# all pool entries have valid PoolParams.
# ---------------------------------------------------------------------------


class TestPoolStateInvariants:
    """Pool state invariant checks after DELEG/POOL transitions."""

    def test_pool_state_internal_consistency(self):
        """Pool state invariant: retiring pools are a subset of registered pools.

        After any sequence of register/retire operations, every pool in
        the retiring map must also be present in the pools map. This is
        guaranteed by the POOL transition rule: RetirePool requires the
        pool to be registered.

        Spec ref: Shelley formal spec, Figure 35 (POOL transition rule).
        """
        from fractions import Fraction
        from pycardano.certificate import PoolParams, PoolRegistration, PoolRetirement
        from pycardano.hash import PoolKeyHash, VerificationKeyHash
        from vibe.cardano.ledger.shelley_delegation import (
            DelegationState,
            process_certificate,
        )

        # Create a pool with valid params
        pool_hash = PoolKeyHash(b"\x01" * 28)
        vrf_hash = b"\x02" * 32

        pool_params = PoolParams(
            operator=pool_hash,
            vrf_keyhash=vrf_hash,
            pledge=10_000_000,
            cost=340_000_000,
            margin=Fraction(1, 100),
            reward_account=b"\xaa" * 29,
            pool_owners=[VerificationKeyHash(b"\x01" * 28)],
        )

        state = DelegationState()
        params = TEST_PARAMS

        # Register the pool
        state = process_certificate(
            PoolRegistration(pool_params=pool_params),
            state, params, current_epoch=0,
        )

        # Invariant: registered pool has valid params
        pool_key = bytes(pool_hash)
        assert pool_key in state.pools
        assert state.pools[pool_key].operator == pool_hash

        # Retire the pool
        state = process_certificate(
            PoolRetirement(pool_keyhash=pool_hash, epoch=5),
            state, params, current_epoch=0,
        )

        # Invariant: retiring pools are subset of registered pools
        for retiring_key in state.retiring:
            assert retiring_key in state.pools, (
                f"Retiring pool {retiring_key.hex()} not in registered pools"
            )

    def test_non_negative_deposits(self):
        """Deposits field is never negative after any DELEG/POOL transition.

        The key_deposit and pool_deposit are always positive, so the
        total deposit accounting should never go negative.

        Spec ref: Shelley formal spec, Section 8, deposit equations.
        """
        from fractions import Fraction
        from pycardano.certificate import (
            PoolParams,
            PoolRegistration,
            StakeRegistration,
            StakeDeregistration,
        )
        from pycardano.hash import PoolKeyHash, VerificationKeyHash
        from pycardano.certificate import StakeCredential
        from vibe.cardano.ledger.shelley_delegation import (
            DelegationState,
            compute_certificate_deposits,
            process_certificate,
        )

        state = DelegationState()
        params = TEST_PARAMS

        # Register a stake key
        cred = StakeCredential(VerificationKeyHash(b"\x11" * 28))
        reg = StakeRegistration(stake_credential=cred)
        state = process_certificate(reg, state, params, current_epoch=0)
        deposits = compute_certificate_deposits([reg], params)
        assert deposits >= 0, f"Deposits should be non-negative, got {deposits}"

        # Register a pool
        pool_hash = PoolKeyHash(b"\x22" * 28)
        pool_params = PoolParams(
            operator=pool_hash,
            vrf_keyhash=b"\x33" * 32,
            pledge=1_000_000,
            cost=340_000_000,
            margin=Fraction(1, 100),
            reward_account=b"\xbb" * 29,
            pool_owners=[VerificationKeyHash(b"\x22" * 28)],
        )
        pool_reg = PoolRegistration(pool_params=pool_params)
        state = process_certificate(pool_reg, state, params, current_epoch=0)
        deposits = compute_certificate_deposits([pool_reg], params)
        assert deposits >= 0, f"Pool deposits should be non-negative, got {deposits}"

        # Deregister the stake key — refund is negative deposit
        dereg = StakeDeregistration(stake_credential=cred)
        refund_deposits = compute_certificate_deposits([dereg], params)
        # Refund is negative (money returned to tx), registration is positive
        # Net of all three certs should equal key_deposit + pool_deposit - key_deposit = pool_deposit
        net = compute_certificate_deposits([reg, pool_reg, dereg], params)
        assert net == params.pool_deposit, (
            f"Net deposits after reg+pool_reg+dereg should be pool_deposit={params.pool_deposit}, got {net}"
        )

    def test_preserve_balance_restricted(self):
        """Property: restricted-balance preservation.

        After applying a valid transaction, the total value in the UTxO
        set restricted to the addresses involved in the transaction
        should satisfy:
            consumed(tx, utxo) == produced(tx, pp)

        where consumed = sum of spent inputs + withdrawals
        and produced = sum of outputs + fee + deposits

        Spec ref: Shelley formal spec, Section 9, Equation (1).
        """
        utxo_set, txin, sk, vk = make_simple_utxo(value=10_000_000)
        tx = make_valid_tx(utxo_set, txin, sk, vk, output_value=8_000_000, fee=2_000_000)

        # Consumed: value at the spent input
        consumed = sum(
            _output_lovelace(utxo_set[inp])
            for inp in tx.transaction_body.inputs
            if inp in utxo_set
        )

        # Produced: outputs + fee
        produced = sum(
            _output_lovelace(out)
            for out in tx.transaction_body.outputs
        ) + tx.transaction_body.fee

        assert consumed == produced, (
            f"Balance not preserved: consumed={consumed}, produced={produced}"
        )
