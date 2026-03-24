"""Allegra and Mary era ledger validation rules.

Allegra extends Shelley with:
    - ValidityInterval replacing TTL: ``(invalid_before, invalid_hereafter)``
    - Timelock scripts: AllOf, AnyOf, MOfN, RequireSignature, RequireTimeAfter,
      RequireTimeBefore

Mary extends Allegra with:
    - Multi-asset values: ``Value = Coin + MultiAsset``
    - Value preservation across multi-asset tokens (not just lovelace)
    - Minting/burning: transactions can create or destroy tokens
    - Min UTxO calculation accounts for multi-asset size

Spec references:
    * Allegra ledger formal spec (Allegra UTXO transition)
    * Mary ledger formal spec, Section 3 (Multi-asset)
    * ``cardano-ledger/eras/allegra/impl/src/Cardano/Ledger/Allegra/Rules/Utxo.hs``
    * ``cardano-ledger/eras/mary/impl/src/Cardano/Ledger/Mary/Rules/Utxo.hs``
    * ``cardano-ledger/eras/mary/impl/src/Cardano/Ledger/Mary/Value.hs``

Haskell references:
    * ``validateTimelock`` in ``Cardano.Ledger.Allegra.Scripts``
    * ``allegraUtxoTransition`` in ``Cardano.Ledger.Allegra.Rules.Utxo``
    * ``maryUtxoTransition`` in ``Cardano.Ledger.Mary.Rules.Utxo``
    * ``ShelleyMAUtxoPredFailure``: OutsideValidityIntervalUTxO,
      OutputTooBigUTxO, ValueNotConservedUTxO (multi-asset version)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from pycardano import (
    MultiAsset,
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)

from vibe.cardano.ledger.shelley import (
    ShelleyProtocolParams,
    ShelleyUTxO,
    _output_lovelace,
    shelley_min_fee,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# ValidityInterval (Allegra)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ValidityInterval:
    """Allegra validity interval replacing Shelley's TTL.

    Spec ref: Allegra ledger formal spec, ``ValidityInterval`` type.
    Haskell ref: ``ValidityInterval`` in ``Cardano.Ledger.Allegra.TxBody``

    Both bounds are optional:
        - ``invalid_before``: tx invalid before this slot (inclusive lower bound)
        - ``invalid_hereafter``: tx invalid at or after this slot (exclusive upper bound)

    A ``None`` bound means that side is unbounded.
    """

    invalid_before: int | None = None
    invalid_hereafter: int | None = None


def validate_validity_interval(
    interval: ValidityInterval,
    current_slot: int,
) -> list[str]:
    """Validate a transaction's validity interval against the current slot.

    A transaction is valid when:
        ``invalid_before <= current_slot < invalid_hereafter``

    Both bounds are optional. If a bound is None, that side is unconstrained.

    Spec ref: Allegra ledger formal spec, ``validateTimelock`` / validity interval check.
    Haskell ref: ``validateOutsideValidityIntervalUTxO`` in
        ``Cardano.Ledger.Allegra.Rules.Utxo``

    Haskell predicate failure: ``OutsideValidityIntervalUTxO``

    Args:
        interval: The validity interval from the transaction body.
        current_slot: The current slot number.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # Lower bound: tx invalid before this slot
    # Spec: invalid_before <= current_slot
    if interval.invalid_before is not None and current_slot < interval.invalid_before:
        errors.append(
            f"OutsideValidityIntervalUTxO: current_slot={current_slot} "
            f"< invalid_before={interval.invalid_before}"
        )

    # Upper bound: tx invalid at or after this slot
    # Spec: current_slot < invalid_hereafter
    if interval.invalid_hereafter is not None and current_slot >= interval.invalid_hereafter:
        errors.append(
            f"OutsideValidityIntervalUTxO: current_slot={current_slot} "
            f">= invalid_hereafter={interval.invalid_hereafter}"
        )

    return errors


# ---------------------------------------------------------------------------
# Timelock scripts (Allegra)
# ---------------------------------------------------------------------------


class TimelockType(Enum):
    """Types of Allegra timelock native scripts.

    Spec ref: Allegra ledger formal spec, ``Timelock`` type.
    Haskell ref: ``Timelock`` in ``Cardano.Ledger.Allegra.Scripts``
    """

    REQUIRE_SIGNATURE = auto()
    REQUIRE_ALL_OF = auto()
    REQUIRE_ANY_OF = auto()
    REQUIRE_M_OF_N = auto()
    REQUIRE_TIME_AFTER = auto()
    REQUIRE_TIME_BEFORE = auto()


@dataclass(frozen=True)
class Timelock:
    """Allegra timelock script.

    Spec ref: Allegra ledger formal spec, ``Timelock`` / native scripts.
    Haskell ref: ``Timelock`` in ``Cardano.Ledger.Allegra.Scripts``

    This extends Shelley's multisig scripts with time-based conditions.
    """

    type: TimelockType

    # RequireSignature: the key hash that must sign
    key_hash: bytes | None = None

    # AllOf, AnyOf, MOfN: sub-scripts
    scripts: tuple[Timelock, ...] = ()

    # MOfN: required count
    required: int = 0

    # RequireTimeAfter / RequireTimeBefore: slot number
    slot: int | None = None


def evaluate_timelock(
    script: Timelock,
    signers: frozenset[bytes],
    current_slot: int,
) -> bool:
    """Evaluate a timelock script.

    Spec ref: Allegra ledger formal spec, ``evalTimelock``.
    Haskell ref: ``validateTimelock`` in ``Cardano.Ledger.Allegra.Scripts``

    Args:
        script: The timelock script to evaluate.
        signers: Set of key hashes that have provided valid signatures.
        current_slot: Current slot number for time-based conditions.

    Returns:
        True if the script is satisfied, False otherwise.
    """
    match script.type:
        case TimelockType.REQUIRE_SIGNATURE:
            return script.key_hash is not None and script.key_hash in signers

        case TimelockType.REQUIRE_ALL_OF:
            return all(evaluate_timelock(sub, signers, current_slot) for sub in script.scripts)

        case TimelockType.REQUIRE_ANY_OF:
            return any(evaluate_timelock(sub, signers, current_slot) for sub in script.scripts)

        case TimelockType.REQUIRE_M_OF_N:
            satisfied = sum(
                1 for sub in script.scripts if evaluate_timelock(sub, signers, current_slot)
            )
            return satisfied >= script.required

        case TimelockType.REQUIRE_TIME_AFTER:
            # "InvalidBefore" — tx valid only after this slot
            # Spec: current_slot >= slot
            return script.slot is not None and current_slot >= script.slot

        case TimelockType.REQUIRE_TIME_BEFORE:
            # "InvalidHereafter" — tx valid only before this slot
            # Spec: current_slot < slot
            return script.slot is not None and current_slot < script.slot

    return False  # pragma: no cover


# ---------------------------------------------------------------------------
# Multi-asset Value helpers (Mary)
# ---------------------------------------------------------------------------


def _output_value(txout: TransactionOutput) -> Value:
    """Extract a Value from a TransactionOutput, normalizing int to Value.

    pycardano TransactionOutput.amount can be int (lovelace-only) or Value.
    This normalizes to Value for uniform multi-asset handling.
    """
    amount = txout.amount
    if isinstance(amount, int):
        return Value(coin=amount)
    return amount


def _sum_values(values: list[Value]) -> Value:
    """Sum a list of Values, handling the empty case.

    Returns Value(coin=0) for an empty list.
    """
    if not values:
        return Value(coin=0)
    result = values[0]
    for v in values[1:]:
        result = result + v
    return result


def _multi_asset_is_empty(ma: MultiAsset | None) -> bool:
    """Check if a MultiAsset is empty or None."""
    if ma is None:
        return True
    for policy_id in ma:
        assets = ma[policy_id]
        for asset_name in assets:
            if assets[asset_name] != 0:
                return False
    return True


def _value_eq(a: Value, b: Value) -> bool:
    """Check if two Values are equal (coin + all multi-asset entries).

    pycardano's Value.__eq__ should handle this, but we provide a
    fallback that explicitly checks coin and multi-asset.
    """
    if a.coin != b.coin:
        return False

    # Compare multi-assets
    a_ma = a.multi_asset or MultiAsset()
    b_ma = b.multi_asset or MultiAsset()

    # Collect all policy_id -> asset_name -> qty from both
    a_dict: dict[bytes, dict[bytes, int]] = {}
    for pid in a_ma:
        a_dict[bytes(pid)] = {}
        for an in a_ma[pid]:
            qty = a_ma[pid][an]
            if qty != 0:
                a_dict[bytes(pid)][bytes(an)] = qty
        if not a_dict[bytes(pid)]:
            del a_dict[bytes(pid)]

    b_dict: dict[bytes, dict[bytes, int]] = {}
    for pid in b_ma:
        b_dict[bytes(pid)] = {}
        for an in b_ma[pid]:
            qty = b_ma[pid][an]
            if qty != 0:
                b_dict[bytes(pid)][bytes(an)] = qty
        if not b_dict[bytes(pid)]:
            del b_dict[bytes(pid)]

    return a_dict == b_dict


# ---------------------------------------------------------------------------
# Mary protocol parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaryProtocolParams(ShelleyProtocolParams):
    """Mary-era protocol parameters extending Shelley.

    Spec ref: Mary ledger formal spec, protocol parameters.
    Haskell ref: ``Cardano.Ledger.Mary.PParams``

    The key addition for Mary is the ``coins_per_utxo_word`` parameter
    that replaces the flat ``min_utxo_value`` for multi-asset outputs.
    In early Mary, a simpler formula based on ``min_utxo_value`` was used.
    """

    # Mary uses min_utxo_value from Shelley params with a size-based scaling.
    # The utxoEntrySizeWithoutVal constant is 27 words (bytes/8) in the
    # Haskell implementation.
    utxo_entry_size_without_val: int = 27
    """Fixed overhead per UTxO entry in words (8 bytes each).
    Haskell ref: ``utxoEntrySizeWithoutVal`` = 27 in Mary era."""


# Mary mainnet protocol parameters (genesis values)
MARY_MAINNET_PARAMS = MaryProtocolParams()


# ---------------------------------------------------------------------------
# Min UTxO calculation (Mary)
# ---------------------------------------------------------------------------


def _multi_asset_num_assets(ma: MultiAsset | None) -> int:
    """Count the total number of distinct assets in a MultiAsset."""
    if ma is None:
        return 0
    count = 0
    for pid in ma:
        for _an in ma[pid]:
            count += 1
    return count


def _multi_asset_num_policies(ma: MultiAsset | None) -> int:
    """Count the number of distinct policy IDs in a MultiAsset."""
    if ma is None:
        return 0
    return sum(1 for _ in ma)


def _multi_asset_total_asset_name_length(ma: MultiAsset | None) -> int:
    """Sum of all asset name lengths in bytes."""
    if ma is None:
        return 0
    total = 0
    for pid in ma:
        for an in ma[pid]:
            total += len(bytes(an))
    return total


def mary_min_utxo_value(
    txout: TransactionOutput,
    params: MaryProtocolParams,
) -> int:
    """Calculate the minimum lovelace for a Mary-era UTxO output.

    Mary uses a size-based formula for multi-asset outputs:

        max(minUTxOValue, (utxoEntrySizeWithoutVal + utxoEntrySize(v)) * coinsPerUTxOWord)

    where utxoEntrySize for multi-asset is:
        numAssets + \\sum(assetNameLengths) + 28 * numPolicies + 8 - 1) // 8

    For pure-ADA outputs, this simplifies to ``minUTxOValue``.

    Spec ref: Mary ledger formal spec, ``scaledMinDeposit``.
    Haskell ref: ``scaledMinDeposit`` in ``Cardano.Ledger.Mary.Rules.Utxo``

    Args:
        txout: The transaction output.
        params: Mary protocol parameters.

    Returns:
        Minimum lovelace value for this output.
    """
    amount = txout.amount
    if isinstance(amount, int):
        # Pure ADA output — just minUTxOValue
        return params.min_utxo_value

    ma = amount.multi_asset
    if _multi_asset_is_empty(ma):
        return params.min_utxo_value

    # Multi-asset size calculation
    # Haskell: numAssets * k1 + sumAssetNameLengths + numPolicies * k2
    # where k1 = 1, k2 = 28 (policy hash size)
    # Then: quotient = (total + 7) // 8  (round up to words)
    num_assets = _multi_asset_num_assets(ma)
    num_policies = _multi_asset_num_policies(ma)
    total_asset_name_len = _multi_asset_total_asset_name_length(ma)

    # Size in bytes of the multi-asset part:
    # Each quantity is 1 word (8 bytes), each policy ID is 28 bytes,
    # plus asset name bytes, plus overhead.
    # Haskell formula from Mary era:
    #   numAssets + sumAssetNameLengths + 28 * numPolicies
    size_bytes = num_assets + total_asset_name_len + 28 * num_policies

    # Convert to words (round up)
    size_words = (size_bytes + 7) // 8

    # The required value:
    # (utxoEntrySizeWithoutVal + size_words) * coinsPerUTxOWord
    # In Mary, coinsPerUTxOWord = minUTxOValue / utxoEntrySizeWithoutVal
    # So effectively: max(minUTxOValue, quotient)
    coins_per_utxo_word = params.min_utxo_value // params.utxo_entry_size_without_val
    required = max(
        params.min_utxo_value,
        (params.utxo_entry_size_without_val + size_words) * coins_per_utxo_word,
    )

    return required


# ---------------------------------------------------------------------------
# Mary value preservation
# ---------------------------------------------------------------------------


def validate_mary_value_preservation(
    input_values: list[Value],
    output_values: list[Value],
    fee: int,
    mint: Value | None = None,
) -> list[str]:
    """Validate multi-asset value preservation (Mary extension).

    Mary's value preservation rule:
        consumed = sum(inputs) + mint
        produced = sum(outputs) + fee
        consumed == produced

    where all arithmetic is over full Value (coin + multi-asset).

    Spec ref: Mary ledger formal spec, ``consumed`` / ``produced`` equations.
    Haskell ref: ``maryUtxoTransition`` in ``Cardano.Ledger.Mary.Rules.Utxo``
    Haskell failure: ``ValueNotConservedUTxO``

    Args:
        input_values: Values from all resolved input UTxOs.
        output_values: Values from all transaction outputs.
        fee: Transaction fee in lovelace.
        mint: Minted value (can include negative quantities for burns).
            None means no minting.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # Consumed side: inputs + mint
    consumed = _sum_values(input_values)
    if mint is not None:
        consumed = consumed + mint

    # Produced side: outputs + fee (fee is ADA-only)
    produced = _sum_values(output_values)
    produced = produced + Value(coin=fee)

    if not _value_eq(consumed, produced):
        errors.append(f"ValueNotConservedUTxO: consumed={consumed}, produced={produced}")

    return errors


# ---------------------------------------------------------------------------
# Allegra UTXO validation
# ---------------------------------------------------------------------------


def validate_allegra_utxo(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    params: ShelleyProtocolParams,
    current_slot: int,
    tx_size: int,
    validity_interval: ValidityInterval | None = None,
) -> list[str]:
    """Validate Allegra-era UTXO rules.

    Extends Shelley UTXO with ValidityInterval replacing TTL.

    Spec ref: Allegra ledger formal spec, UTXO transition.
    Haskell ref: ``allegraUtxoTransition`` in
        ``Cardano.Ledger.Allegra.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        params: Protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.
        validity_interval: Allegra validity interval. If None, falls back
            to TTL-based checking (Shelley compat).

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # --- Validity interval (replaces TTL in Allegra) ---
    if validity_interval is not None:
        errors.extend(validate_validity_interval(validity_interval, current_slot))
    elif tx_body.ttl is not None and current_slot >= tx_body.ttl:
        # Shelley-style TTL fallback
        errors.append(f"ExpiredUTxO: current_slot={current_slot}, ttl={tx_body.ttl}")

    # --- All inputs must exist ---
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

    # --- Tx size within limits ---
    if tx_size > params.max_tx_size:
        errors.append(f"MaxTxSizeUTxO: tx_size={tx_size}, max={params.max_tx_size}")

    # --- Fee >= minimum fee ---
    min_fee = shelley_min_fee(tx_size, params)
    if tx_body.fee < min_fee:
        errors.append(f"FeeTooSmallUTxO: fee={tx_body.fee}, min_fee={min_fee} (tx_size={tx_size})")

    # --- All output values >= min_utxo_value ---
    for i, txout in enumerate(tx_body.outputs):
        out_value = _output_lovelace(txout)
        if out_value < params.min_utxo_value:
            errors.append(
                f"OutputTooSmallUTxO: output[{i}] value={out_value}, min={params.min_utxo_value}"
            )

    # --- Value preservation (lovelace only for Allegra) ---
    if not missing_inputs:
        input_sum = sum(_output_lovelace(out) for out in resolved_inputs)
        withdrawal_sum = 0
        if tx_body.withdraws:
            withdrawal_sum = sum(tx_body.withdraws.values())
        consumed = input_sum + withdrawal_sum
        output_sum = sum(_output_lovelace(out) for out in tx_body.outputs)
        produced = output_sum + tx_body.fee
        if consumed != produced:
            errors.append(f"ValueNotConservedUTxO: consumed={consumed}, produced={produced}")

    return errors


# ---------------------------------------------------------------------------
# Mary UTXO validation
# ---------------------------------------------------------------------------


def validate_mary_tx(
    tx_body: TransactionBody,
    witness_set: object,
    utxo_set: ShelleyUTxO,
    params: MaryProtocolParams,
    current_slot: int,
    tx_size: int | None = None,
    validity_interval: ValidityInterval | None = None,
    mint: Value | None = None,
) -> list[str]:
    """Validate a Mary-era transaction (multi-asset aware).

    Extends Allegra UTXO rules with:
        - Multi-asset value preservation (including minting)
        - Size-based min UTxO for multi-asset outputs

    Spec ref: Mary ledger formal spec, UTXO transition.
    Haskell ref: ``maryUtxoTransition`` in ``Cardano.Ledger.Mary.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        params: Mary protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.
            If None, uses a default for testing.
        validity_interval: Allegra validity interval. Falls back to TTL if None.
        mint: Minted/burned multi-asset value. None means no minting.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # Default tx_size for testing convenience
    if tx_size is None:
        tx_size = 200

    # --- Validity interval ---
    if validity_interval is not None:
        errors.extend(validate_validity_interval(validity_interval, current_slot))
    elif tx_body.ttl is not None and current_slot >= tx_body.ttl:
        errors.append(f"ExpiredUTxO: current_slot={current_slot}, ttl={tx_body.ttl}")

    # --- All inputs must exist ---
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

    # --- Tx size within limits ---
    if tx_size > params.max_tx_size:
        errors.append(f"MaxTxSizeUTxO: tx_size={tx_size}, max={params.max_tx_size}")

    # --- Fee >= minimum fee ---
    min_fee = shelley_min_fee(tx_size, params)
    if tx_body.fee < min_fee:
        errors.append(f"FeeTooSmallUTxO: fee={tx_body.fee}, min_fee={min_fee} (tx_size={tx_size})")

    # --- Min UTxO value (Mary: size-based for multi-asset) ---
    for i, txout in enumerate(tx_body.outputs):
        min_value = mary_min_utxo_value(txout, params)
        out_lovelace = _output_lovelace(txout)
        if out_lovelace < min_value:
            errors.append(f"OutputTooSmallUTxO: output[{i}] value={out_lovelace}, min={min_value}")

    # --- Multi-asset value preservation ---
    if not missing_inputs:
        input_values = [_output_value(out) for out in resolved_inputs]

        # Add withdrawals to consumed side
        withdrawal_sum = 0
        if tx_body.withdraws:
            withdrawal_sum = sum(tx_body.withdraws.values())
        if withdrawal_sum > 0:
            input_values.append(Value(coin=withdrawal_sum))

        output_values = [_output_value(out) for out in tx_body.outputs]

        preservation_errors = validate_mary_value_preservation(
            input_values, output_values, tx_body.fee, mint
        )
        errors.extend(preservation_errors)

    return errors


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class AllegraValidationError(Exception):
    """Raised when an Allegra/Mary transaction fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Allegra/Mary validation failed: {'; '.join(errors)}")
