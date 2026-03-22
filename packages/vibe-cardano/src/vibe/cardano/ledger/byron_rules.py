"""Byron-era ledger validation rules: UTXO transition and block application.

Implements the Byron UTXO transition system from the Byron ledger formal spec.
The key validation rules:

1. **UTXO transition** -- for each transaction in a block:
   - All inputs must reference existing UTxO entries
   - No duplicate inputs within a single transaction
   - Value preservation: sum(inputs) = sum(outputs) + fee
   - Fee >= minimum fee (linear fee model: a + b * txSize)
   - All output values must be > 0

2. **Block application** -- validates all transactions in sequence,
   threading the UTxO set through each one.

3. **Delegation** -- Byron uses heavyweight genesis key delegation.
   Stubbed for now (not required for chain-sync validation).

Spec references:
    * Byron ledger formal spec, Section 10 (UTXO transition)
    * ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/Validation.hs``
    * ``cardano-ledger/byron/ledger/impl/src/Cardano/Chain/UTxO/UTxO.hs``

Haskell references:
    * ``updateUTxO`` in ``Cardano.Chain.UTxO.Validation``
    * ``Environment`` record: protocolMagic, protocolParameters, utxoConfiguration
    * ``UTxOValidationError``: TxValidationError variants
    * ``validateTx``: per-transaction validation
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cbor2pure as cbor2

from vibe.cardano.ledger.byron import (
    ByronTx,
    ByronTxAux,
    ByronTxId,
    ByronTxIn,
    ByronTxOut,
)

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# UTxO type alias
# ---------------------------------------------------------------------------

# UTxO set: maps (tx_id_bytes, output_index) -> ByronTxOut
# Using a tuple key for efficiency -- frozen ByronTxIn would also work
# but tuple hashing is faster.
ByronUTxO = dict[tuple[bytes, int], ByronTxOut]


# ---------------------------------------------------------------------------
# Byron protocol parameters (fee model)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ByronFeeParams:
    """Linear fee parameters for Byron era.

    fee = a + b * txSize (in bytes)

    Byron mainnet values:
        a = 155381 lovelace (constant term)
        b = 43.946 lovelace/byte (coefficient, stored as microlovelace
            ratio to avoid floating point)

    Haskell ref: ``Cardano.Chain.Common.TxFeePolicy``
        ``TxFeePolicyTxSizeLinear (TxSizeLinear (Lovelace a) (Lovelace b))``
        where b is a Rational (multiplier * 1000000 for precision).

    The Haskell node stores b as a Rational 43946/1000 = 43.946.
    We store the numerator and denominator to avoid float imprecision.
    """

    a: int = 155381
    """Constant fee component in lovelace."""

    b_numerator: int = 43946
    """Fee-per-byte numerator (lovelace * 1000)."""

    b_denominator: int = 1000
    """Fee-per-byte denominator."""


# Byron mainnet fee parameters
BYRON_MAINNET_FEE_PARAMS = ByronFeeParams()


# ---------------------------------------------------------------------------
# Minimum fee calculation
# ---------------------------------------------------------------------------


def byron_min_fee(
    tx_size: int,
    fee_params: ByronFeeParams = BYRON_MAINNET_FEE_PARAMS,
) -> int:
    """Calculate the minimum fee for a Byron transaction.

    fee = a + ceil(b * txSize)

    The ceiling is applied to the variable component to ensure the fee
    is never undercharged due to integer division.

    Spec ref: Byron ledger spec, Section 10, fee calculation.
    Haskell ref: ``calculateTxSizeLinear`` in
        ``Cardano.Chain.Common.TxFeePolicy``

    Args:
        tx_size: Size of the serialized transaction in bytes.
        fee_params: Linear fee parameters (default: Byron mainnet).

    Returns:
        Minimum fee in lovelace.
    """
    if tx_size < 0:
        raise ValueError(f"Transaction size must be non-negative, got {tx_size}")

    # a + ceil(b_num * txSize / b_den)
    variable = math.ceil(
        (fee_params.b_numerator * tx_size) / fee_params.b_denominator
    )
    return fee_params.a + variable


# ---------------------------------------------------------------------------
# Transaction validation
# ---------------------------------------------------------------------------


def _utxo_key(txin: ByronTxIn) -> tuple[bytes, int]:
    """Convert a ByronTxIn to a UTxO lookup key."""
    return (txin.tx_id.digest, txin.index)


def validate_byron_tx(
    tx_aux: ByronTxAux,
    utxo_set: ByronUTxO,
    fee_params: ByronFeeParams = BYRON_MAINNET_FEE_PARAMS,
) -> list[str]:
    """Validate a Byron transaction against the current UTxO set.

    Returns a list of error strings. An empty list means the transaction
    is valid. Multiple errors can be reported at once (fail-accumulating
    semantics matching the Haskell ``Validation`` applicative).

    Validation rules (Byron UTXO transition):
        1. All inputs must exist in the UTxO set
        2. No duplicate inputs within the transaction
        3. All output values must be strictly positive (> 0)
        4. Value preservation: sum(inputs) = sum(outputs) + fee
        5. Fee >= minimum fee based on tx size

    Haskell ref: ``validateTx`` and ``validateTxAux`` in
        ``Cardano.Chain.UTxO.Validation``

    Args:
        tx_aux: The transaction with witnesses.
        utxo_set: Current UTxO set.
        fee_params: Fee parameters for minimum fee calculation.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []
    tx = tx_aux.tx

    # --- Rule 1: All inputs must exist in the UTxO set ---
    resolved_inputs: list[ByronTxOut] = []
    for txin in tx.inputs:
        key = _utxo_key(txin)
        if key not in utxo_set:
            errors.append(
                f"Input not in UTxO: tx_id={txin.tx_id.digest.hex()[:16]}..., "
                f"index={txin.index}"
            )
        else:
            resolved_inputs.append(utxo_set[key])

    # --- Rule 2: No duplicate inputs ---
    input_keys = [_utxo_key(txin) for txin in tx.inputs]
    if len(input_keys) != len(set(input_keys)):
        seen: set[tuple[bytes, int]] = set()
        dupes: list[str] = []
        for key in input_keys:
            if key in seen:
                dupes.append(f"({key[0].hex()[:16]}..., {key[1]})")
            seen.add(key)
        errors.append(f"Duplicate inputs: {', '.join(dupes)}")

    # --- Rule 3: All output values must be > 0 ---
    for i, txout in enumerate(tx.outputs):
        if txout.value <= 0:
            errors.append(
                f"Output {i} has non-positive value: {txout.value}"
            )

    # Short-circuit if we couldn't resolve all inputs -- value
    # preservation check would be meaningless.
    if len(resolved_inputs) != len(tx.inputs):
        return errors

    # --- Rule 4: Value preservation ---
    # In Byron, fees are implicit: fee = sum(inputs) - sum(outputs)
    input_sum = sum(out.value for out in resolved_inputs)
    output_sum = sum(out.value for out in tx.outputs)

    if output_sum > input_sum:
        errors.append(
            f"Outputs exceed inputs: input_sum={input_sum}, "
            f"output_sum={output_sum}"
        )
        return errors

    implicit_fee = input_sum - output_sum

    # --- Rule 5: Fee >= minimum fee ---
    # Calculate tx size from CBOR encoding of the full TxAux
    tx_size = len(tx_aux.to_cbor())
    min_fee = byron_min_fee(tx_size, fee_params)

    if implicit_fee < min_fee:
        errors.append(
            f"Insufficient fee: implicit_fee={implicit_fee}, "
            f"min_fee={min_fee} (tx_size={tx_size})"
        )

    return errors


# ---------------------------------------------------------------------------
# UTxO set operations
# ---------------------------------------------------------------------------


def _consumed_utxos(tx: ByronTx) -> set[tuple[bytes, int]]:
    """Return the set of UTxO keys consumed by a transaction."""
    return {_utxo_key(txin) for txin in tx.inputs}


def _produced_utxos(tx: ByronTx) -> dict[tuple[bytes, int], ByronTxOut]:
    """Return the UTxO entries produced by a transaction.

    Each output is keyed by (tx_id, output_index).
    """
    tx_id = ByronTxId.from_tx(tx)
    return {
        (tx_id.digest, i): txout
        for i, txout in enumerate(tx.outputs)
    }


def apply_byron_tx(
    tx_aux: ByronTxAux,
    utxo_set: ByronUTxO,
    fee_params: ByronFeeParams = BYRON_MAINNET_FEE_PARAMS,
) -> ByronUTxO:
    """Validate and apply a single Byron transaction to the UTxO set.

    If the transaction is valid, returns a new UTxO set with consumed
    inputs removed and new outputs added. Raises ``ByronValidationError``
    if the transaction fails validation.

    Haskell ref: ``updateUTxO`` in ``Cardano.Chain.UTxO.Validation``

    Args:
        tx_aux: Transaction with witnesses.
        utxo_set: Current UTxO set (not modified in place).
        fee_params: Fee parameters.

    Returns:
        New UTxO set after applying the transaction.

    Raises:
        ByronValidationError: If the transaction fails any validation rule.
    """
    errors = validate_byron_tx(tx_aux, utxo_set, fee_params)
    if errors:
        raise ByronValidationError(errors)

    tx = tx_aux.tx

    # Build new UTxO: remove consumed, add produced
    consumed = _consumed_utxos(tx)
    produced = _produced_utxos(tx)

    new_utxo = {k: v for k, v in utxo_set.items() if k not in consumed}
    new_utxo.update(produced)
    return new_utxo


# ---------------------------------------------------------------------------
# Block-level validation
# ---------------------------------------------------------------------------


def apply_byron_block(
    block_txs: list[ByronTxAux],
    utxo_set: ByronUTxO,
    fee_params: ByronFeeParams = BYRON_MAINNET_FEE_PARAMS,
) -> ByronUTxO:
    """Validate and apply all transactions in a Byron block.

    Transactions are applied sequentially -- each transaction sees the
    UTxO set as modified by all preceding transactions in the block.
    This matches the Haskell ``foldl' updateUTxO`` pattern.

    Note: Block header hash verification is handled at a higher layer
    (block deserialization). This function focuses on the UTXO transition
    rules for the block body.

    Args:
        block_txs: List of transactions from the block body.
        utxo_set: UTxO set at the start of the block.
        fee_params: Fee parameters.

    Returns:
        New UTxO set after applying all transactions.

    Raises:
        ByronValidationError: If any transaction fails validation.
            The error includes the transaction index within the block.
    """
    current_utxo = utxo_set

    for i, tx_aux in enumerate(block_txs):
        try:
            current_utxo = apply_byron_tx(tx_aux, current_utxo, fee_params)
        except ByronValidationError as e:
            raise ByronValidationError(
                [f"Transaction {i}: {err}" for err in e.errors]
            ) from e

    return current_utxo


# ---------------------------------------------------------------------------
# Delegation (stub)
# ---------------------------------------------------------------------------


def validate_byron_delegation(
    block_cbor: bytes,  # noqa: ARG001 -- placeholder
) -> list[str]:
    """Validate Byron delegation certificates in a block.

    Byron uses heavyweight genesis key delegation where genesis keys
    delegate to operational keys via ``ProxySKHeavy`` certificates.
    These are embedded in block headers, not in transaction bodies.

    This is stubbed for initial chain-sync validation. Full delegation
    verification requires:
        - Genesis key set (from genesis block)
        - Delegation certificate chain validation
        - Epoch-based delegation scheduling (omega rule)

    Haskell ref:
        ``Cardano.Chain.Delegation.Validation``
        ``Cardano.Chain.Block.Validation.updateBody``

    TODO(VNODE-191): Implement full Byron delegation validation.

    Returns:
        Always returns empty list (no errors) for now.
    """
    return []


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class ByronValidationError(Exception):
    """Raised when a Byron transaction or block fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Byron validation failed: {'; '.join(errors)}")
