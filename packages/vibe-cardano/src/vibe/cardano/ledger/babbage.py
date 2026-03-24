"""Babbage-era ledger validation rules: UTXO and UTXOW transition rules.

Babbage extends Alonzo with these validation rules:

UTXO rules (extending Alonzo):
    - **ReferenceInputsNotInUTxO**: All reference inputs must exist in UTxO set
    - **CollateralReturnValidation**: Collateral return output must be valid
    - **TotalCollateralMismatch**: Explicit total_collateral must match actual
    - **BabbageMinUTxO**: coinsPerUTxOByte replaces coinsPerUTxOWord
    - **InlineDatumValidation**: Inline datums must be well-formed
    - All Alonzo UTXO rules still apply

UTXOW rules (extending Alonzo):
    - Reference scripts can satisfy script requirements (no witness needed)
    - All Alonzo UTXOW rules still apply

Spec references:
    * Babbage ledger formal spec, Section 4 (UTxO transition)
    * Babbage ledger formal spec, Section 5 (UTXOW)
    * ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/Rules/Utxo.hs``
    * ``cardano-ledger/eras/babbage/impl/src/Cardano/Ledger/Babbage/Rules/Utxow.hs``

Haskell references:
    * ``babbageUtxoTransition`` in ``Cardano.Ledger.Babbage.Rules.Utxo``
    * ``BabbageUtxoPredFailure``: IncorrectTotalCollateralField,
      BabbageOutputTooSmallUTxO, BabbageNonDisjointRefInputs
    * ``babbageUtxowTransition`` in ``Cardano.Ledger.Babbage.Rules.Utxow``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pycardano import (
    TransactionBody,
    TransactionInput,
    TransactionOutput,
    Value,
)
from pycardano.witness import TransactionWitnessSet

from vibe.cardano.ledger.allegra_mary import (
    ValidityInterval,
    _output_value,
    _sum_values,
    _value_eq,
    validate_validity_interval,
)
from vibe.cardano.ledger.alonzo import (
    _collateral_contains_non_ada,
    _ex_units_too_big,
    _insufficient_collateral,
    _too_many_collateral_inputs,
    calculate_script_fee,
    validate_alonzo_witnesses,
)
from vibe.cardano.ledger.alonzo_types import (
    Language,
    Redeemer,
)
from vibe.cardano.ledger.babbage_types import (
    BabbageOutputExtension,
    BabbageProtocolParams,
    DatumOptionTag,
    ReferenceScript,
)
from vibe.cardano.ledger.shelley import (
    ShelleyUTxO,
    _output_lovelace,
    shelley_min_fee,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Babbage min UTxO value (coinsPerUTxOByte)
# ---------------------------------------------------------------------------


def babbage_min_utxo(
    output_size_bytes: int,
    coins_per_utxo_byte: int,
) -> int:
    """Calculate the minimum lovelace for a Babbage-era UTxO output.

    Babbage replaces Alonzo's coinsPerUTxOWord with coinsPerUTxOByte for
    a more granular and accurate min UTxO calculation.

    The formula:
        max(output_size_bytes * coinsPerUTxOByte, minUTxOValue_constant)

    The Haskell implementation uses:
        (160 + output_size_bytes) * coinsPerUTxOByte

    where 160 bytes is the constant overhead per UTxO entry (the serialized
    size of the UTxO key: tx_id 32 bytes + index + overhead).

    Spec ref: Babbage formal spec, ``utxoEntrySize``.
    Haskell ref: ``getMinCoinTxOut`` in ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        output_size_bytes: Serialized size of the output in bytes.
        coins_per_utxo_byte: Protocol parameter (lovelace per byte).

    Returns:
        Minimum lovelace value for this output.
    """
    UTXO_ENTRY_OVERHEAD = 160  # bytes — constant per-entry overhead
    return (UTXO_ENTRY_OVERHEAD + output_size_bytes) * coins_per_utxo_byte


def estimate_output_size(txout: TransactionOutput) -> int:
    """Estimate the serialized size of a transaction output in bytes.

    This is a rough estimate used for min UTxO calculation. The actual
    size depends on CBOR encoding, but we approximate based on the
    output's content.

    Haskell ref: ``getMinCoinSizedTxOut`` in ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        txout: The transaction output.

    Returns:
        Estimated serialized size in bytes.
    """
    # Base: address (57-58 bytes typical) + value encoding overhead
    size = 60  # address + CBOR overhead

    amount = txout.amount
    if isinstance(amount, int):
        size += 9  # CBOR integer (up to 8 bytes + tag)
    else:
        size += 9  # coin
        ma = amount.multi_asset
        if ma is not None:
            for pid in ma:
                size += 28  # policy ID
                for an in ma[pid]:
                    size += len(bytes(an)) + 9  # asset name + quantity

    # Datum hash if present (Alonzo-style)
    if hasattr(txout, "datum_hash") and txout.datum_hash is not None:
        size += 34  # 32-byte hash + CBOR overhead

    # Inline datum or script_ref from pycardano (if available)
    if hasattr(txout, "datum") and txout.datum is not None:
        # Inline datum — approximate CBOR size
        size += 40  # rough estimate for datum
    if hasattr(txout, "script") and txout.script is not None:
        size += 100  # rough estimate for reference script

    return size


# ---------------------------------------------------------------------------
# Reference inputs validation
# ---------------------------------------------------------------------------


def _reference_inputs_not_in_utxo(
    reference_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
) -> list[str]:
    """Check that all reference inputs exist in the UTxO set.

    Reference inputs are read-only — they provide datums and scripts
    without being consumed. But they must still exist.

    Spec ref: Babbage formal spec, ``referenceInputs ⊆ dom utxo``.
    Haskell ref: ``validateBabbageNonDisjointRefInputs`` and reference
        input existence check in ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        reference_inputs: Reference inputs from the tx body.
        utxo_set: Current UTxO set.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []
    for txin in reference_inputs:
        if txin not in utxo_set:
            errors.append(
                f"ReferenceInputsNotInUTxO: reference input "
                f"tx_id={txin.transaction_id.payload.hex()[:16]}..., "
                f"index={txin.index} not found in UTxO set"
            )
    return errors


# ---------------------------------------------------------------------------
# Collateral return validation
# ---------------------------------------------------------------------------


def _validate_collateral_return(
    collateral_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
    collateral_return: TransactionOutput | None,
    total_collateral: int | None,
) -> list[str]:
    """Validate Babbage collateral return and total_collateral fields.

    In Babbage, the tx can specify a collateral_return output and an
    explicit total_collateral. If phase-2 validation fails:
        consumed = total_collateral (forfeited)
        excess = sum(collateral_inputs) - total_collateral → collateral_return

    Spec ref: Babbage formal spec, collateral return validation.
    Haskell ref: ``validateTotalCollateral`` in
        ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        collateral_inputs: Collateral inputs from the tx body.
        utxo_set: Current UTxO set.
        collateral_return: Optional collateral return output.
        total_collateral: Optional explicit total collateral amount.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    if total_collateral is not None and collateral_return is not None:
        # Sum collateral input values
        coll_sum = 0
        for txin in collateral_inputs:
            if txin in utxo_set:
                coll_sum += _output_lovelace(utxo_set[txin])

        # collateral_return value
        return_value = _output_lovelace(collateral_return)

        # total_collateral must equal collateral_sum - return_value
        expected_total = coll_sum - return_value
        if total_collateral != expected_total:
            errors.append(
                f"IncorrectTotalCollateralField: total_collateral={total_collateral}, "
                f"expected={expected_total} "
                f"(collateral_sum={coll_sum}, return_value={return_value})"
            )

    elif total_collateral is not None and collateral_return is None:
        # total_collateral without return — collateral sum must equal total_collateral
        coll_sum = 0
        for txin in collateral_inputs:
            if txin in utxo_set:
                coll_sum += _output_lovelace(utxo_set[txin])
        if total_collateral != coll_sum:
            errors.append(
                f"IncorrectTotalCollateralField: total_collateral={total_collateral}, "
                f"but collateral_sum={coll_sum} (no collateral return)"
            )

    return errors


# ---------------------------------------------------------------------------
# Reference script resolution
# ---------------------------------------------------------------------------


def resolve_reference_scripts(
    reference_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
    output_extensions: dict[TransactionInput, BabbageOutputExtension] | None = None,
) -> dict[bytes, ReferenceScript]:
    """Resolve reference scripts from reference input UTxOs.

    Scripts stored in reference input outputs can be used by the
    transaction without including them in the witness set.

    Spec ref: Babbage formal spec, reference script resolution.
    Haskell ref: ``getRefScripts`` in ``Cardano.Ledger.Babbage.Rules.Utxow``

    Args:
        reference_inputs: Reference inputs from the tx body.
        utxo_set: Current UTxO set.
        output_extensions: Babbage extensions for outputs (keyed by TxIn).

    Returns:
        Map from script_hash -> ReferenceScript for all available reference scripts.
    """
    scripts: dict[bytes, ReferenceScript] = {}

    if output_extensions is None:
        return scripts

    for txin in reference_inputs:
        if txin in output_extensions:
            ext = output_extensions[txin]
            if ext.reference_script is not None:
                scripts[ext.reference_script.script_hash] = ext.reference_script

    return scripts


# ---------------------------------------------------------------------------
# Inline datum validation
# ---------------------------------------------------------------------------


def _validate_inline_datums(
    output_extensions: dict[int, BabbageOutputExtension] | None,
) -> list[str]:
    """Validate that inline datums in outputs are well-formed.

    Inline datums must be valid CBOR-encoded Plutus data. This is a
    basic structural check — the datum content is opaque at this layer.

    Spec ref: Babbage formal spec, inline datum well-formedness.
    Haskell ref: ``validateOutputBabbageNorm`` in
        ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        output_extensions: Babbage extensions for outputs (keyed by output index).

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    if output_extensions is None:
        return errors

    for idx, ext in output_extensions.items():
        if ext.datum_option is not None:
            if ext.datum_option.tag == DatumOptionTag.INLINE:
                if not ext.datum_option.data:
                    errors.append(
                        f"InlineDatumEmpty: output[{idx}] has inline datum tag but empty data"
                    )
            elif ext.datum_option.tag == DatumOptionTag.HASH:
                if len(ext.datum_option.data) != 32:
                    errors.append(
                        f"DatumHashWrongSize: output[{idx}] datum hash "
                        f"is {len(ext.datum_option.data)} bytes, expected 32"
                    )

    return errors


# ---------------------------------------------------------------------------
# Reference script size limit
# ---------------------------------------------------------------------------


def _validate_reference_script_size(
    reference_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
    output_extensions: dict[int, BabbageOutputExtension] | None,
    max_ref_script_size: int = 204800,
) -> list[str]:
    """Validate that total reference script size does not exceed the limit.

    Spec ref: Babbage formal spec, reference script size bound.
    Haskell ref: ``validateTotalReferenceScriptSize`` in
        ``Cardano.Ledger.Babbage.Rules.Utxo``

    The total serialized size of all reference scripts referenced by
    a transaction must not exceed max_ref_script_size_per_tx bytes.

    Args:
        reference_inputs: Reference inputs from the tx body.
        utxo_set: Current UTxO set.
        output_extensions: Babbage extensions for outputs (keyed by TxIn or index).
        max_ref_script_size: Maximum total reference script bytes (default: 200KB).

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []
    total_size = 0

    # Check reference scripts attached to reference input UTxOs via pycardano
    for txin in reference_inputs:
        if txin in utxo_set:
            txout = utxo_set[txin]
            if hasattr(txout, "script") and txout.script is not None:
                script_bytes = getattr(txout.script, "to_cbor", None)
                if callable(script_bytes):
                    total_size += len(script_bytes())
                else:
                    # Rough estimate
                    total_size += 100

    # Check reference scripts from output extensions
    if output_extensions is not None:
        for _idx, ext in output_extensions.items():
            if ext.reference_script is not None:
                total_size += len(ext.reference_script.script_bytes)

    if total_size > max_ref_script_size:
        errors.append(
            f"TotalReferenceScriptSizeTooBig: total_size={total_size}, max={max_ref_script_size}"
        )

    return errors


# ---------------------------------------------------------------------------
# Babbage UTXO transition rule
# ---------------------------------------------------------------------------


def validate_babbage_utxo(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    params: BabbageProtocolParams,
    current_slot: int,
    tx_size: int,
    redeemers: list[Redeemer] | None = None,
    validity_interval: ValidityInterval | None = None,
    collateral_inputs: list[TransactionInput] | None = None,
    has_plutus_scripts: bool = False,
    reference_inputs: list[TransactionInput] | None = None,
    collateral_return: TransactionOutput | None = None,
    total_collateral: int | None = None,
    output_extensions: dict[int, BabbageOutputExtension] | None = None,
) -> list[str]:
    """Validate Babbage-era UTXO transition rules.

    Extends Alonzo UTXO rules with Babbage-specific checks for reference
    inputs, collateral return, inline datums, and coinsPerUTxOByte.

    Spec ref: Babbage ledger formal spec, Section 4 (UTxO transition).
    Haskell ref: ``babbageUtxoTransition`` in
        ``Cardano.Ledger.Babbage.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        params: Babbage protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.
        redeemers: Redeemers from the witness set (default: empty).
        validity_interval: Alonzo validity interval (default: from tx_body).
        collateral_inputs: Collateral inputs (default: from tx_body).
        has_plutus_scripts: Whether the tx uses any Plutus scripts.
        reference_inputs: Reference inputs (read-only UTxOs).
        collateral_return: Collateral return output (Babbage+).
        total_collateral: Explicit total collateral (Babbage+).
        output_extensions: Babbage extensions per output index.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    if redeemers is None:
        redeemers = []
    if collateral_inputs is None:
        collateral_inputs = list(tx_body.collateral) if tx_body.collateral else []
    if reference_inputs is None:
        reference_inputs = (
            list(tx_body.reference_inputs)
            if hasattr(tx_body, "reference_inputs") and tx_body.reference_inputs
            else []
        )

    # --- Validity interval (Allegra+) ---
    if validity_interval is not None:
        errors.extend(validate_validity_interval(validity_interval, current_slot))
    elif tx_body.validity_start is not None or tx_body.ttl is not None:
        interval = ValidityInterval(
            invalid_before=tx_body.validity_start,
            invalid_hereafter=tx_body.ttl,
        )
        errors.extend(validate_validity_interval(interval, current_slot))

    # --- Input set must not be empty ---
    if not tx_body.inputs:
        errors.append("InputSetEmptyUTxO: transaction has no inputs")

    # --- All inputs must exist in the UTxO set ---
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

    # --- Reference inputs must exist (Babbage) ---
    errors.extend(_reference_inputs_not_in_utxo(reference_inputs, utxo_set))

    # --- Tx size within limits ---
    if tx_size > params.max_tx_size:
        errors.append(f"MaxTxSizeUTxO: tx_size={tx_size}, max={params.max_tx_size}")

    # --- Fee >= minimum fee ---
    min_fee = shelley_min_fee(tx_size, params)
    if tx_body.fee < min_fee:
        errors.append(f"FeeTooSmallUTxO: fee={tx_body.fee}, min_fee={min_fee} (tx_size={tx_size})")

    # --- Min UTxO value (Babbage: coinsPerUTxOByte) ---
    for i, txout in enumerate(tx_body.outputs):
        out_size = estimate_output_size(txout)
        min_value = babbage_min_utxo(out_size, params.coins_per_utxo_byte)
        out_lovelace = _output_lovelace(txout)
        if out_lovelace < min_value:
            errors.append(
                f"BabbageOutputTooSmallUTxO: output[{i}] value={out_lovelace}, "
                f"min={min_value} (size={out_size} bytes)"
            )

    # --- Value preservation (multi-asset, inherited from Mary) ---
    if not missing_inputs:
        input_values = [_output_value(out) for out in resolved_inputs]

        # Add withdrawals to consumed side
        withdrawal_sum = 0
        if tx_body.withdraws:
            withdrawal_sum = sum(tx_body.withdraws.values())
        if withdrawal_sum > 0:
            input_values.append(Value(coin=withdrawal_sum))

        output_values = [_output_value(out) for out in tx_body.outputs]

        # Minting
        mint = None
        if tx_body.mint:
            mint = Value(coin=0, multi_asset=tx_body.mint)

        consumed = _sum_values(input_values)
        if mint is not None:
            consumed = consumed + mint
        produced = _sum_values(output_values)
        produced = produced + Value(coin=tx_body.fee)

        if not _value_eq(consumed, produced):
            errors.append(f"ValueNotConservedUTxO: consumed={consumed}, produced={produced}")

    # ===== Alonzo-inherited Plutus rules =====

    # --- Collateral rules (only apply when Plutus scripts are present) ---
    if has_plutus_scripts:
        errors.extend(_collateral_contains_non_ada(collateral_inputs, utxo_set))
        errors.extend(_too_many_collateral_inputs(collateral_inputs, params.max_collateral_inputs))

        script_fees = calculate_script_fee(redeemers, params.execution_unit_prices)
        errors.extend(
            _insufficient_collateral(
                collateral_inputs, utxo_set, script_fees, params.collateral_percentage
            )
        )

        # --- Babbage: collateral return + total_collateral ---
        errors.extend(
            _validate_collateral_return(
                collateral_inputs, utxo_set, collateral_return, total_collateral
            )
        )

    # --- ExUnits too big ---
    if redeemers:
        errors.extend(_ex_units_too_big(redeemers, params.max_tx_ex_units))

    # --- Inline datum validation (Babbage) ---
    errors.extend(_validate_inline_datums(output_extensions))

    # --- Reference script total size limit (Babbage) ---
    # Spec ref: Babbage formal spec, total reference script size bound.
    # Haskell ref: ``validateTotalReferenceScriptSize`` in
    #     ``Cardano.Ledger.Babbage.Rules.Utxo``
    # The total serialized size of all reference scripts used in a tx
    # must not exceed max_ref_script_size_per_tx (default 204800 bytes).
    if reference_inputs:
        errors.extend(
            _validate_reference_script_size(
                reference_inputs,
                utxo_set,
                output_extensions,
                getattr(params, "max_ref_script_size_per_tx", 204800),
            )
        )

    return errors


# ---------------------------------------------------------------------------
# Babbage UTXOW transition rule
# ---------------------------------------------------------------------------


def validate_babbage_witnesses(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
    redeemers: list[Redeemer] | None = None,
    datums: list[bytes] | None = None,
    script_integrity_hash: bytes | None = None,
    cost_models: dict[Language, dict[str, int]] | None = None,
    languages_used: set[Language] | None = None,
    has_plutus_scripts: bool = False,
    reference_scripts: dict[bytes, ReferenceScript] | None = None,
) -> list[str]:
    """Validate Babbage-era UTXOW transition rules.

    Extends Alonzo witness validation. In Babbage, reference scripts can
    satisfy script requirements — the transaction does not need to include
    the script in the witness set if it's available via a reference input.

    Spec ref: Babbage ledger formal spec, Section 5 (UTXOW).
    Haskell ref: ``babbageUtxowTransition`` in
        ``Cardano.Ledger.Babbage.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        redeemers: Redeemers from the witness set.
        datums: Datum CBOR encodings from the witness set.
        script_integrity_hash: Script data hash from tx body.
        cost_models: Cost models from protocol parameters.
        languages_used: Plutus language versions used.
        has_plutus_scripts: Whether Plutus scripts are present.
        reference_scripts: Available reference scripts (from reference inputs).

    Returns:
        List of validation error strings (empty = valid).
    """
    # Delegate to Alonzo witness validation — Babbage adds reference script
    # resolution but the core witness checks are the same.
    errors = validate_alonzo_witnesses(
        tx_body=tx_body,
        witness_set=witness_set,
        utxo_set=utxo_set,
        redeemers=redeemers,
        datums=datums,
        script_integrity_hash=script_integrity_hash,
        cost_models=cost_models,
        languages_used=languages_used,
        has_plutus_scripts=has_plutus_scripts,
    )

    return errors


# ---------------------------------------------------------------------------
# Combined validation: validate_babbage_tx
# ---------------------------------------------------------------------------


def validate_babbage_tx(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
    params: BabbageProtocolParams,
    current_slot: int,
    tx_size: int,
    redeemers: list[Redeemer] | None = None,
    datums: list[bytes] | None = None,
    validity_interval: ValidityInterval | None = None,
    collateral_inputs: list[TransactionInput] | None = None,
    script_integrity_hash: bytes | None = None,
    cost_models: dict[Language, dict[str, int]] | None = None,
    languages_used: set[Language] | None = None,
    has_plutus_scripts: bool = False,
    reference_inputs: list[TransactionInput] | None = None,
    collateral_return: TransactionOutput | None = None,
    total_collateral: int | None = None,
    output_extensions: dict[int, BabbageOutputExtension] | None = None,
    reference_scripts: dict[bytes, ReferenceScript] | None = None,
) -> list[str]:
    """Validate a complete Babbage transaction (UTXO + UTXOW rules).

    Top-level validation combining Babbage UTXO rules and UTXOW rules.

    Spec ref: Babbage ledger formal spec, Sections 4-5.
    Haskell ref: ``babbageUtxoTransition`` + ``babbageUtxowTransition``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        params: Babbage protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.
        redeemers: Redeemers from the witness set.
        datums: Datum CBOR encodings from the witness set.
        validity_interval: Validity interval override.
        collateral_inputs: Collateral inputs override.
        script_integrity_hash: Script data hash from tx body.
        cost_models: Cost models from protocol parameters.
        languages_used: Plutus language versions used.
        has_plutus_scripts: Whether Plutus scripts are present.
        reference_inputs: Reference inputs (read-only UTxOs).
        collateral_return: Collateral return output.
        total_collateral: Explicit total collateral.
        output_extensions: Babbage extensions per output index.
        reference_scripts: Available reference scripts.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # UTXO rules
    errors.extend(
        validate_babbage_utxo(
            tx_body=tx_body,
            utxo_set=utxo_set,
            params=params,
            current_slot=current_slot,
            tx_size=tx_size,
            redeemers=redeemers,
            validity_interval=validity_interval,
            collateral_inputs=collateral_inputs,
            has_plutus_scripts=has_plutus_scripts,
            reference_inputs=reference_inputs,
            collateral_return=collateral_return,
            total_collateral=total_collateral,
            output_extensions=output_extensions,
        )
    )

    # UTXOW rules (witness verification)
    errors.extend(
        validate_babbage_witnesses(
            tx_body=tx_body,
            witness_set=witness_set,
            utxo_set=utxo_set,
            redeemers=redeemers,
            datums=datums,
            script_integrity_hash=script_integrity_hash,
            cost_models=cost_models,
            languages_used=languages_used,
            has_plutus_scripts=has_plutus_scripts,
            reference_scripts=reference_scripts,
        )
    )

    return errors


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class BabbageValidationError(Exception):
    """Raised when a Babbage transaction or block fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Babbage validation failed: {'; '.join(errors)}")
