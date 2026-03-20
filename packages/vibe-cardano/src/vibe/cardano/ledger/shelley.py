"""Shelley-era ledger validation rules: UTXO and UTXOW transition rules.

Implements the Shelley UTXO transition system from the Shelley ledger formal spec.
The key validation rules:

1. **UTXO transition** -- for each transaction in a block:
   - All inputs must reference existing UTxO entries
   - No double-spending (implicit: set-based inputs in pycardano)
   - Value preservation: sum(inputs) = sum(outputs) + fee
   - Fee >= minimum fee (linear fee model: a * txSize + b)
   - All output values >= min_utxo_value
   - TTL not expired (current_slot < ttl)

2. **UTXOW transition** -- witness verification:
   - Required signers present in VKey witnesses
   - VKey witness signatures verify against tx body hash

3. **Block application** -- validates all transactions in sequence,
   threading the UTxO set through each one.

Spec references:
    * Shelley ledger formal spec, Section 9 (UTxO)
    * Shelley ledger formal spec, Section 10 (UTXOW)
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Utxo.hs``
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Utxow.hs``

Haskell references:
    * ``shelleyUtxoTransition`` in ``Cardano.Ledger.Shelley.Rules.Utxo``
    * ``ShelleyUtxoPredFailure``: InputsNotInUTxO, ExpiredUTxO,
      MaxTxSizeUTxO, ValueNotConservedUTxO, etc.
    * ``shelleyWitsVKeyNeeded`` in ``Cardano.Ledger.Shelley.Rules.Utxow``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nacl.signing import VerifyKey

from pycardano import (
    Transaction,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
)
from pycardano.hash import TransactionId, VerificationKeyHash
from pycardano.key import VerificationKey
from pycardano.witness import TransactionWitnessSet, VerificationKeyWitness

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Lovelace
# ---------------------------------------------------------------------------

Lovelace = int
"""Shelley lovelace is just an integer."""

# ---------------------------------------------------------------------------
# UTxO type alias
# ---------------------------------------------------------------------------

# UTxO set: maps TransactionInput -> TransactionOutput
# Using pycardano types directly for Shelley+ eras.
ShelleyUTxO = dict[TransactionInput, TransactionOutput]

# ---------------------------------------------------------------------------
# Shelley protocol parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShelleyProtocolParams:
    """Shelley-era protocol parameters relevant to UTXO validation.

    Spec ref: Shelley ledger formal spec, Figure 6 (Protocol parameters).
    Haskell ref: ``Cardano.Ledger.Shelley.PParams.ShelleyPParams``

    Only the parameters needed for UTXO/UTXOW validation are included here.
    Additional parameters (e.g., d, nOpt, rho, tau) belong to other
    transition rules (EPOCH, POOLREAP, etc.).
    """

    min_fee_a: int = 44
    """Fee coefficient (lovelace per byte). Shelley mainnet genesis: 44."""

    min_fee_b: int = 155381
    """Fee constant (lovelace). Shelley mainnet genesis: 155381."""

    max_tx_size: int = 16384
    """Maximum transaction size in bytes. Shelley mainnet genesis: 16384."""

    min_utxo_value: int = 1000000
    """Minimum lovelace value per UTxO output. Shelley mainnet genesis: 1000000 (1 ADA)."""

    key_deposit: int = 2000000
    """Deposit for stake key registration in lovelace. Shelley mainnet: 2000000."""

    pool_deposit: int = 500000000
    """Deposit for pool registration in lovelace. Shelley mainnet: 500000000."""


# Shelley mainnet protocol parameters (genesis values)
SHELLEY_MAINNET_PARAMS = ShelleyProtocolParams()


# ---------------------------------------------------------------------------
# Minimum fee calculation
# ---------------------------------------------------------------------------


def shelley_min_fee(tx_size: int, params: ShelleyProtocolParams) -> int:
    """Calculate the minimum fee for a Shelley transaction.

    fee = min_fee_a * txSize + min_fee_b

    This is a simple linear fee model. Unlike Byron which uses ceiling
    division for the variable component, Shelley uses integer multiplication.

    Spec ref: Shelley ledger formal spec, Section 9, Equation ``minfee``.
    Haskell ref: ``shelleyMinFeeTx`` in
        ``Cardano.Ledger.Shelley.Rules.Utxo``

    Args:
        tx_size: Size of the serialized transaction in bytes.
        params: Protocol parameters containing fee coefficients.

    Returns:
        Minimum fee in lovelace.

    Raises:
        ValueError: If tx_size is negative.
    """
    if tx_size < 0:
        raise ValueError(f"Transaction size must be non-negative, got {tx_size}")

    return params.min_fee_a * tx_size + params.min_fee_b


# ---------------------------------------------------------------------------
# UTxO value extraction helpers
# ---------------------------------------------------------------------------


def _output_lovelace(txout: TransactionOutput) -> int:
    """Extract the lovelace value from a TransactionOutput.

    pycardano's TransactionOutput.amount can be either an int (lovelace only)
    or a Value (lovelace + multi-asset). In Shelley era, it's always just
    lovelace (int), but we handle both for forward compatibility.
    """
    amount = txout.amount
    if isinstance(amount, int):
        return amount
    # pycardano Value object — .coin is the lovelace component
    return amount.coin


# ---------------------------------------------------------------------------
# UTXO transition rule — validate_shelley_utxo
# ---------------------------------------------------------------------------


def validate_shelley_utxo(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    params: ShelleyProtocolParams,
    current_slot: int,
    tx_size: int,
) -> list[str]:
    """Validate the UTXO transition rules for a Shelley transaction.

    Returns a list of error strings. An empty list means the transaction
    passes all UTXO checks. Multiple errors are reported (fail-accumulating
    semantics matching the Haskell ``Validation`` applicative).

    Validation rules (Shelley UTXO transition, spec Section 9):
        1. All inputs must exist in the UTxO set (InputsNotInUTxO)
        2. TTL not expired: current_slot < ttl (ExpiredUTxO)
        3. Tx size <= max_tx_size (MaxTxSizeUTxO)
        4. Fee >= minimum fee (FeeTooSmallUTxO)
        5. All output values >= min_utxo_value (OutputTooSmallUTxO)
        6. Value preservation: sum(inputs) = sum(outputs) + fee
           (ValueNotConservedUTxO)

    Haskell ref: ``shelleyUtxoTransition`` in
        ``Cardano.Ledger.Shelley.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        params: Protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # --- Rule 1: All inputs must exist in the UTxO set ---
    # Spec: txins txb ⊆ dom utxo
    # Haskell: InputsNotInUTxO
    missing_inputs: list[TransactionInput] = []
    resolved_inputs: list[TransactionOutput] = []
    for txin in tx_body.inputs:
        if txin not in utxo_set:
            missing_inputs.append(txin)
        else:
            resolved_inputs.append(utxo_set[txin])

    if missing_inputs:
        for txin in missing_inputs:
            errors.append(
                f"InputsNotInUTxO: tx_id={txin.transaction_id.payload.hex()[:16]}..., "
                f"index={txin.index}"
            )

    # --- Rule 2: TTL not expired ---
    # Spec: slot < txttl txb
    # Haskell: ExpiredUTxO
    if tx_body.ttl is not None and current_slot >= tx_body.ttl:
        errors.append(
            f"ExpiredUTxO: current_slot={current_slot}, ttl={tx_body.ttl}"
        )

    # --- Rule 3: Tx size within limits ---
    # Spec: txsize txb ≤ maxTxSize pp
    # Haskell: MaxTxSizeUTxO
    if tx_size > params.max_tx_size:
        errors.append(
            f"MaxTxSizeUTxO: tx_size={tx_size}, max={params.max_tx_size}"
        )

    # --- Rule 4: Fee >= minimum fee ---
    # Spec: minfee pp tx ≤ txfee txb
    # Haskell: FeeTooSmallUTxO
    min_fee = shelley_min_fee(tx_size, params)
    if tx_body.fee < min_fee:
        errors.append(
            f"FeeTooSmallUTxO: fee={tx_body.fee}, min_fee={min_fee} "
            f"(tx_size={tx_size})"
        )

    # --- Rule 5: All output values >= min_utxo_value ---
    # Spec: ∀ txout ∈ txouts txb, coin txout ≥ minUTxOValue pp
    # Haskell: OutputTooSmallUTxO
    for i, txout in enumerate(tx_body.outputs):
        out_value = _output_lovelace(txout)
        if out_value < params.min_utxo_value:
            errors.append(
                f"OutputTooSmallUTxO: output[{i}] value={out_value}, "
                f"min={params.min_utxo_value}"
            )

    # --- Rule 6: Value preservation ---
    # Spec: consumed pp utxo txb = produced pp stakePools txb
    # In Shelley (without certificates): sum(inputs) = sum(outputs) + fee
    # Haskell: ValueNotConservedUTxO
    #
    # Only check if all inputs were resolved (otherwise the check is
    # meaningless and we already reported InputsNotInUTxO).
    if not missing_inputs:
        input_sum = sum(_output_lovelace(out) for out in resolved_inputs)

        # Add withdrawals to consumed side (reward withdrawals are consumed)
        withdrawal_sum = 0
        if tx_body.withdraws:
            withdrawal_sum = sum(tx_body.withdraws.values())

        consumed = input_sum + withdrawal_sum

        output_sum = sum(_output_lovelace(out) for out in tx_body.outputs)

        # Deposits from certificates go to produced side
        # Deposit refunds go to consumed side
        # For now, we handle the simple case without certificates
        # TODO(VNODE-XXX): Add certificate deposit/refund handling
        produced = output_sum + tx_body.fee

        if consumed != produced:
            errors.append(
                f"ValueNotConservedUTxO: consumed={consumed}, "
                f"produced={produced}"
            )

    return errors


# ---------------------------------------------------------------------------
# UTXOW transition rule — witness verification
# ---------------------------------------------------------------------------


def _vkey_hash(vkey: VerificationKey) -> bytes:
    """Compute the Blake2b-224 hash of a verification key.

    This is used to match VKey witnesses to required signers (the key hash
    in the UTxO address must match the hash of the witness VKey).

    Spec ref: Shelley formal spec, ``hashKey`` function.
    Haskell ref: ``hashKey`` in ``Cardano.Ledger.Keys``
    """
    return hashlib.blake2b(vkey.payload, digest_size=28).digest()


def _verify_vkey_signature(
    vkey_payload: bytes,
    signature: bytes,
    tx_body_hash: bytes,
) -> bool:
    """Verify an Ed25519 signature using PyNaCl.

    Args:
        vkey_payload: 32-byte Ed25519 verification key.
        signature: 64-byte Ed25519 signature.
        tx_body_hash: 32-byte hash of the transaction body (the signed message).

    Returns:
        True if signature is valid, False otherwise.
    """
    try:
        verify_key = VerifyKey(vkey_payload)
        verify_key.verify(tx_body_hash, signature)
        return True
    except Exception:
        return False


def validate_shelley_witnesses(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
) -> list[str]:
    """Validate the UTXOW transition rules for a Shelley transaction.

    This checks that all required signers have provided valid VKey witnesses,
    and that all witness signatures are valid.

    Validation rules (Shelley UTXOW transition, spec Section 10):
        1. All required key hashes have a corresponding VKey witness
           (MissingVKeyWitnessesUTxOW)
        2. All VKey witness signatures verify against the tx body hash
           (InvalidWitnessesUTxOW)

    Haskell ref: ``shelleyWitsVKeyNeeded`` in
        ``Cardano.Ledger.Shelley.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set (to determine required signers from input
            addresses).

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # Compute the transaction body hash (the message that was signed)
    tx_body_hash = tx_body.hash()

    # Collect VKey witnesses
    vkey_witnesses: list[VerificationKeyWitness] = []
    if witness_set.vkey_witnesses:
        vkey_witnesses = list(witness_set.vkey_witnesses)

    # --- Check 1: All VKey signatures must be valid ---
    # Spec: ∀ (vk, σ) ∈ witsVKeyHashes, verify vk (txbodyHash tx) σ
    # Haskell: InvalidWitnessesUTxOW
    witnessed_key_hashes: set[bytes] = set()

    for wit in vkey_witnesses:
        vkey_bytes = wit.vkey.payload
        sig_bytes = wit.signature

        if not _verify_vkey_signature(vkey_bytes, sig_bytes, tx_body_hash):
            errors.append(
                f"InvalidWitnessesUTxOW: invalid signature for "
                f"vkey={vkey_bytes.hex()[:16]}..."
            )
        else:
            # Only count valid witnesses toward required signers
            key_hash = _vkey_hash(wit.vkey)
            witnessed_key_hashes.add(key_hash)

    # --- Check 2: All required signers must be present ---
    # Spec: witsVKeyNeeded ⊆ witsKeyHashes
    # Haskell: MissingVKeyWitnessesUTxOW
    #
    # Required signers come from:
    # a) Payment key hashes of UTxO inputs being spent
    # b) Reward account key hashes for withdrawals
    # c) Certificate signers (TODO: implement with cert handling)
    # d) required_signers field (Alonzo+, but we check it for forward compat)

    required_key_hashes: set[bytes] = set()

    # (a) Payment key hashes from inputs
    for txin in tx_body.inputs:
        if txin in utxo_set:
            txout = utxo_set[txin]
            addr = txout.address
            # Extract payment key hash from address
            # pycardano Address.payment_part gives the payment credential
            if addr.payment_part is not None:
                payment_hash = bytes(addr.payment_part)
                if len(payment_hash) == 28:
                    required_key_hashes.add(payment_hash)

    # (b) Withdrawal key hashes
    if tx_body.withdraws:
        for reward_addr in tx_body.withdraws:
            # reward_addr is bytes — the staking credential hash
            # In pycardano, the keys are bytes of the reward address
            if hasattr(reward_addr, 'payment_part') and reward_addr.payment_part:
                required_key_hashes.add(bytes(reward_addr.payment_part))

    # (d) required_signers field (Alonzo+)
    if tx_body.required_signers:
        for signer in tx_body.required_signers:
            required_key_hashes.add(bytes(signer))

    # Check that all required key hashes are covered by witnesses
    missing = required_key_hashes - witnessed_key_hashes
    if missing:
        for key_hash in missing:
            errors.append(
                f"MissingVKeyWitnessesUTxOW: missing witness for "
                f"key_hash={key_hash.hex()[:16]}..."
            )

    return errors


# ---------------------------------------------------------------------------
# Combined validation: validate_shelley_tx
# ---------------------------------------------------------------------------


def validate_shelley_tx(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
    params: ShelleyProtocolParams,
    current_slot: int,
    tx_size: int,
) -> list[str]:
    """Validate a complete Shelley transaction (UTXO + UTXOW rules).

    This is the top-level validation function that combines both the UTXO
    transition rules (value preservation, fees, TTL, min UTxO) and the
    UTXOW rules (witness verification).

    Spec ref: Shelley ledger formal spec, Sections 9-10.
    Haskell ref: ``shelleyUtxoTransition`` + ``shelleyWitsVKeyNeeded``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        params: Protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # UTXO rules
    errors.extend(validate_shelley_utxo(tx_body, utxo_set, params, current_slot, tx_size))

    # UTXOW rules (witness verification)
    errors.extend(validate_shelley_witnesses(tx_body, witness_set, utxo_set))

    return errors


# ---------------------------------------------------------------------------
# UTxO set operations
# ---------------------------------------------------------------------------


def _consumed_utxos(tx_body: TransactionBody) -> set[TransactionInput]:
    """Return the set of UTxO keys consumed by a transaction."""
    return set(tx_body.inputs)


def _produced_utxos(
    tx_body: TransactionBody,
) -> dict[TransactionInput, TransactionOutput]:
    """Return the UTxO entries produced by a transaction.

    Each output is keyed by (tx_id, output_index).
    """
    tx_id = tx_body.id
    return {
        TransactionInput(tx_id, i): txout
        for i, txout in enumerate(tx_body.outputs)
    }


def apply_shelley_tx(
    tx: Transaction,
    utxo_set: ShelleyUTxO,
    params: ShelleyProtocolParams,
    current_slot: int,
) -> ShelleyUTxO:
    """Validate and apply a single Shelley transaction to the UTxO set.

    If the transaction is valid, returns a new UTxO set with consumed
    inputs removed and new outputs added. Raises ``ShelleyValidationError``
    if the transaction fails validation.

    Haskell ref: ``applyTx`` in ``Cardano.Ledger.Shelley.LedgerState``

    Args:
        tx: The full transaction (body + witnesses).
        utxo_set: Current UTxO set (not modified in place).
        params: Protocol parameters.
        current_slot: Current slot number.

    Returns:
        New UTxO set after applying the transaction.

    Raises:
        ShelleyValidationError: If the transaction fails any validation rule.
    """
    tx_body = tx.transaction_body
    witness_set = tx.transaction_witness_set

    # Calculate tx size from CBOR encoding
    tx_size = len(tx.to_cbor())

    errors = validate_shelley_tx(
        tx_body, witness_set, utxo_set, params, current_slot, tx_size
    )
    if errors:
        raise ShelleyValidationError(errors)

    # Build new UTxO: remove consumed, add produced
    consumed = _consumed_utxos(tx_body)
    produced = _produced_utxos(tx_body)

    new_utxo = {k: v for k, v in utxo_set.items() if k not in consumed}
    new_utxo.update(produced)
    return new_utxo


# ---------------------------------------------------------------------------
# Block-level validation
# ---------------------------------------------------------------------------


def apply_shelley_block(
    block_txs: list[Transaction],
    utxo_set: ShelleyUTxO,
    params: ShelleyProtocolParams,
    current_slot: int,
) -> ShelleyUTxO:
    """Validate and apply all transactions in a Shelley block.

    Transactions are applied sequentially -- each transaction sees the
    UTxO set as modified by all preceding transactions in the block.
    This matches the Haskell ``foldl' applyTx`` pattern.

    Spec ref: Shelley ledger formal spec, BBODY rule.
    Haskell ref: ``applyTxsTransition`` in
        ``Cardano.Ledger.Shelley.LedgerState``

    Args:
        block_txs: List of transactions from the block body.
        utxo_set: UTxO set at the start of the block.
        params: Protocol parameters.
        current_slot: Slot number of the block.

    Returns:
        New UTxO set after applying all transactions.

    Raises:
        ShelleyValidationError: If any transaction fails validation.
            The error includes the transaction index within the block.
    """
    current_utxo = utxo_set

    for i, tx in enumerate(block_txs):
        try:
            current_utxo = apply_shelley_tx(tx, current_utxo, params, current_slot)
        except ShelleyValidationError as e:
            raise ShelleyValidationError(
                [f"Transaction {i}: {err}" for err in e.errors]
            ) from e

    return current_utxo


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class ShelleyValidationError(Exception):
    """Raised when a Shelley transaction or block fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Shelley validation failed: {'; '.join(errors)}")
