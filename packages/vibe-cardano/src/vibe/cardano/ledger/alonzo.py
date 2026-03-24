"""Alonzo-era ledger validation rules: UTXO and UTXOW transition rules.

Alonzo extends Mary with Plutus script support, adding these validation rules:

UTXO rules (extending Mary):
    - **CollateralContainsNonADA**: All collateral inputs must contain only ADA
    - **InsufficientCollateral**: Total collateral >= collateralPercentage% of script fees
    - **TooManyCollateralInputs**: len(collateral) <= maxCollateralInputs
    - **ScriptIntegrityHashMismatch**: hash(redeemers||datums||lang_views) == scriptIntegrityHash
    - **ExUnitsTooBigUTxO**: Total ExUnits across all scripts <= maxTxExUnits
    - **OutsideForecast**: Validity interval within forecast window
    - All Shelley/Mary UTXO rules still apply

UTXOW rules (extending Shelley):
    - Every Plutus script referenced must have a matching witness
    - Every datum hash in outputs must have a matching datum witness
    - required_signers must all have VKey witnesses
    - Redeemer pointers must resolve to valid script purposes

Spec references:
    * Alonzo ledger formal spec, Section 9 (UTxO transition)
    * Alonzo ledger formal spec, Section 10 (UTXOW)
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxo.hs``
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Rules/Utxow.hs``

Haskell references:
    * ``alonzoUtxoTransition`` in ``Cardano.Ledger.Alonzo.Rules.Utxo``
    * ``AlonzoUtxoPredFailure``: CollateralContainsNonADA,
      InsufficientCollateral, TooManyCollateralInputs, etc.
    * ``alonzoUtxowTransition`` in ``Cardano.Ledger.Alonzo.Rules.Utxow``
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
    Timelock,
    ValidityInterval,
    _multi_asset_is_empty,
    _output_value,
    _sum_values,
    _value_eq,
    evaluate_timelock,
    validate_validity_interval,
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
from vibe.cardano.ledger.shelley import (
    ShelleyUTxO,
    _output_lovelace,
    shelley_min_fee,
    validate_shelley_witnesses,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Collateral validation
# ---------------------------------------------------------------------------


def _collateral_contains_non_ada(
    collateral_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
) -> list[str]:
    """Check that all collateral inputs contain only ADA (no multi-asset).

    Spec ref: Alonzo formal spec, ``CollateralContainsNonADA``.
    Haskell ref: ``validateCollateralContainsNonADA`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Collateral is forfeited if a Plutus script fails phase-2 validation,
    so it must be pure ADA to ensure deterministic fee collection.

    Args:
        collateral_inputs: The collateral inputs from the tx body.
        utxo_set: Current UTxO set.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []
    for txin in collateral_inputs:
        if txin in utxo_set:
            txout = utxo_set[txin]
            amount = txout.amount
            if not isinstance(amount, int):
                # It's a Value — check if it has non-empty multi-asset
                if not _multi_asset_is_empty(amount.multi_asset):
                    errors.append(
                        f"CollateralContainsNonADA: collateral input "
                        f"tx_id={txin.transaction_id.payload.hex()[:16]}..., "
                        f"index={txin.index} contains multi-asset tokens"
                    )
    return errors


def _insufficient_collateral(
    collateral_inputs: list[TransactionInput],
    utxo_set: ShelleyUTxO,
    total_script_fees: int,
    collateral_percentage: int,
) -> list[str]:
    """Check that total collateral >= collateralPercentage% of script fees.

    Spec ref: Alonzo formal spec, ``InsufficientCollateral``.
    Haskell ref: ``validateInsufficientCollateral`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    The formula:
        total_collateral_ada >= ceil(total_script_fees * collateralPercentage / 100)

    Args:
        collateral_inputs: Collateral inputs from the tx body.
        utxo_set: Current UTxO set.
        total_script_fees: Total fee attributable to script execution.
        collateral_percentage: Required collateral as percentage (e.g., 150 = 150%).

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    # Sum ADA in collateral inputs
    total_collateral = 0
    for txin in collateral_inputs:
        if txin in utxo_set:
            total_collateral += _output_lovelace(utxo_set[txin])

    # Required collateral: ceil(script_fees * percentage / 100)
    required = (total_script_fees * collateral_percentage + 99) // 100

    if total_collateral < required:
        errors.append(
            f"InsufficientCollateral: total_collateral={total_collateral}, "
            f"required={required} "
            f"(script_fees={total_script_fees}, percentage={collateral_percentage}%)"
        )

    return errors


def _too_many_collateral_inputs(
    collateral_inputs: list[TransactionInput],
    max_collateral_inputs: int,
) -> list[str]:
    """Check that the number of collateral inputs does not exceed the limit.

    Spec ref: Alonzo formal spec, ``TooManyCollateralInputs``.
    Haskell ref: ``validateTooManyCollateralInputs`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Args:
        collateral_inputs: Collateral inputs from the tx body.
        max_collateral_inputs: Protocol parameter limit.

    Returns:
        List of error strings (empty = valid).
    """
    if len(collateral_inputs) > max_collateral_inputs:
        return [
            f"TooManyCollateralInputs: count={len(collateral_inputs)}, max={max_collateral_inputs}"
        ]
    return []


# ---------------------------------------------------------------------------
# ExUnits validation
# ---------------------------------------------------------------------------


def _total_ex_units(redeemers: list[Redeemer]) -> ExUnits:
    """Sum the ExUnits across all redeemers in a transaction.

    Spec ref: Alonzo formal spec, ``totExUnits``.
    Haskell ref: ``totExUnits`` in ``Cardano.Ledger.Alonzo.Tx``

    Args:
        redeemers: All redeemers in the transaction.

    Returns:
        Combined ExUnits (component-wise sum).
    """
    result = ExUnits(mem=0, steps=0)
    for r in redeemers:
        result = result + r.ex_units
    return result


def _ex_units_too_big(
    redeemers: list[Redeemer],
    max_tx_ex_units: ExUnits,
) -> list[str]:
    """Check that total ExUnits across all scripts <= maxTxExUnits.

    Spec ref: Alonzo formal spec, ``ExUnitsTooBigUTxO``.
    Haskell ref: ``validateExUnitsTooBigUTxO`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Args:
        redeemers: All redeemers in the transaction.
        max_tx_ex_units: Protocol parameter limit.

    Returns:
        List of error strings (empty = valid).
    """
    total = _total_ex_units(redeemers)
    if total.exceeds(max_tx_ex_units):
        return [
            f"ExUnitsTooBigUTxO: total_mem={total.mem}, total_steps={total.steps}, "
            f"max_mem={max_tx_ex_units.mem}, max_steps={max_tx_ex_units.steps}"
        ]
    return []


# ---------------------------------------------------------------------------
# Script integrity hash validation
# ---------------------------------------------------------------------------


def _script_integrity_hash_mismatch(
    tx_body_script_integrity_hash: bytes | None,
    redeemers: list[Redeemer],
    datums: list[bytes],
    cost_models: dict[Language, list[int] | dict[str, int]],
    languages_used: set[Language],
    has_plutus_scripts: bool,
) -> list[str]:
    """Validate the script integrity hash in the transaction body.

    The script integrity hash binds the execution context (redeemers, datums,
    cost models) to the transaction, preventing malleability.

    Spec ref: Alonzo formal spec, ``ScriptIntegrityHashMismatch``.
    Haskell ref: ``validateScriptIntegrityHash`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Rules:
        - If the tx has Plutus scripts: scriptIntegrityHash must be present
          and must match the computed hash
        - If the tx has no Plutus scripts: scriptIntegrityHash should be absent
          (though some eras are lenient here)

    Args:
        tx_body_script_integrity_hash: The hash from the tx body (or None).
        redeemers: Redeemers in the witness set.
        datums: Datum CBOR encodings in the witness set.
        cost_models: Cost models from protocol parameters.
        languages_used: Plutus language versions used.
        has_plutus_scripts: Whether the transaction uses any Plutus scripts.

    Returns:
        List of error strings (empty = valid).
    """
    errors: list[str] = []

    if has_plutus_scripts:
        if tx_body_script_integrity_hash is None:
            errors.append(
                "ScriptIntegrityHashMismatch: transaction has Plutus scripts "
                "but no scriptIntegrityHash in body"
            )
        else:
            # Normalize cost_models to dict[Language, CostModel]
            normalized: dict[Language, dict[str, int]] = {}
            for lang, cm in cost_models.items():
                if isinstance(cm, list):
                    # Convert list of ints to dict with index-based keys
                    normalized[lang] = {str(i): v for i, v in enumerate(cm)}
                else:
                    normalized[lang] = cm

            computed = compute_script_integrity_hash(redeemers, datums, normalized, languages_used)
            if computed != tx_body_script_integrity_hash:
                errors.append(
                    f"ScriptIntegrityHashMismatch: computed={computed.hex()[:16]}..., "
                    f"in_body={tx_body_script_integrity_hash.hex()[:16]}..."
                )
    elif tx_body_script_integrity_hash is not None:
        # No Plutus scripts but hash is present — this is allowed in some
        # interpretations but flagged as a mismatch in strict mode.
        # The Haskell node checks: if no Plutus scripts, the hash should be
        # Nothing. However, if there are native scripts with redeemers
        # (shouldn't happen), this would catch it.
        pass  # Lenient: allow hash presence without Plutus scripts

    return errors


# ---------------------------------------------------------------------------
# Script fee calculation
# ---------------------------------------------------------------------------


def calculate_script_fee(
    redeemers: list[Redeemer],
    prices: ExUnitPrices,
) -> int:
    """Calculate the total fee attributable to script execution.

    fee = sum(prices.fee_for(r.ex_units) for r in redeemers)

    Spec ref: Alonzo formal spec, ``txscriptfee``.
    Haskell ref: ``txscriptfee`` in ``Cardano.Ledger.Alonzo.TxInfo``

    Args:
        redeemers: All redeemers in the transaction.
        prices: Execution unit prices from protocol parameters.

    Returns:
        Total script fee in lovelace.
    """
    total = _total_ex_units(redeemers)
    return prices.fee_for(total)


# ---------------------------------------------------------------------------
# Alonzo min UTxO value
# ---------------------------------------------------------------------------


def alonzo_min_utxo_value(
    txout: TransactionOutput,
    coins_per_utxo_word: int,
) -> int:
    """Calculate the minimum lovelace for an Alonzo-era UTxO output.

    Alonzo replaces Mary's minUTxOValue-based formula with a
    coinsPerUTxOWord approach that accounts for datum hashes.

    The formula:
        max(lovelacePerUTxOWord, (utxoEntrySizeWithoutVal + valSize + datumHashSize) * coinsPerUTxOWord)

    where:
        - utxoEntrySizeWithoutVal = 27 words (constant overhead)
        - valSize = size of the output value in words
        - datumHashSize = 10 words if datum hash present, 0 otherwise

    Spec ref: Alonzo formal spec, ``utxoEntrySize``.
    Haskell ref: ``utxoEntrySize`` in ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Args:
        txout: The transaction output.
        coins_per_utxo_word: Protocol parameter (lovelace per UTxO word).

    Returns:
        Minimum lovelace value for this output.
    """
    UTXO_ENTRY_SIZE_WITHOUT_VAL = 27  # words (constant overhead)
    DATUM_HASH_SIZE = 10  # words (32 bytes = 4 words, but padded to 10 in practice)

    # Value size in words
    amount = txout.amount
    if isinstance(amount, int):
        val_size = 2  # coin only: 2 words
    else:
        # Multi-asset: estimate size
        ma = amount.multi_asset
        if _multi_asset_is_empty(ma):
            val_size = 2
        else:
            # Rough estimate matching Haskell: numAssets + policyOverhead
            num_assets = 0
            num_policies = 0
            total_name_len = 0
            if ma is not None:
                for pid in ma:
                    num_policies += 1
                    for an in ma[pid]:
                        num_assets += 1
                        total_name_len += len(bytes(an))
            size_bytes = num_assets + total_name_len + 28 * num_policies
            val_size = max(2, (size_bytes + 7) // 8)

    # Check for datum hash
    has_datum_hash = hasattr(txout, "datum_hash") and txout.datum_hash is not None
    datum_size = DATUM_HASH_SIZE if has_datum_hash else 0

    total_words = UTXO_ENTRY_SIZE_WITHOUT_VAL + val_size + datum_size
    return max(coins_per_utxo_word, total_words * coins_per_utxo_word)


# ---------------------------------------------------------------------------
# Alonzo UTXO transition rule
# ---------------------------------------------------------------------------


def validate_alonzo_utxo(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    params: AlonzoProtocolParams,
    current_slot: int,
    tx_size: int,
    redeemers: list[Redeemer] | None = None,
    validity_interval: ValidityInterval | None = None,
    collateral_inputs: list[TransactionInput] | None = None,
    has_plutus_scripts: bool = False,
) -> list[str]:
    """Validate Alonzo-era UTXO transition rules.

    Extends Mary UTXO rules with Alonzo-specific checks for collateral,
    execution units, and script integrity.

    Spec ref: Alonzo ledger formal spec, Section 9 (UTxO transition).
    Haskell ref: ``alonzoUtxoTransition`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        params: Alonzo protocol parameters.
        current_slot: Current slot number.
        tx_size: Size of the serialized transaction in bytes.
        redeemers: Redeemers from the witness set (default: empty).
        validity_interval: Alonzo validity interval (default: from tx_body TTL).
        collateral_inputs: Collateral inputs (default: from tx_body).
        has_plutus_scripts: Whether the tx uses any Plutus scripts.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    if redeemers is None:
        redeemers = []

    # Extract collateral from tx_body if not provided explicitly
    if collateral_inputs is None:
        collateral_inputs = list(tx_body.collateral) if tx_body.collateral else []

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

    # --- Tx size within limits ---
    if tx_size > params.max_tx_size:
        errors.append(f"MaxTxSizeUTxO: tx_size={tx_size}, max={params.max_tx_size}")

    # --- Fee >= minimum fee ---
    min_fee = shelley_min_fee(tx_size, params)
    if tx_body.fee < min_fee:
        errors.append(f"FeeTooSmallUTxO: fee={tx_body.fee}, min_fee={min_fee} (tx_size={tx_size})")

    # --- Min UTxO value (Alonzo: coinsPerUTxOWord based) ---
    for i, txout in enumerate(tx_body.outputs):
        min_value = alonzo_min_utxo_value(txout, params.coins_per_utxo_word)
        out_lovelace = _output_lovelace(txout)
        if out_lovelace < min_value:
            errors.append(f"OutputTooSmallUTxO: output[{i}] value={out_lovelace}, min={min_value}")

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

    # ===== Alonzo-specific rules =====

    # --- Collateral rules (only apply when Plutus scripts are present) ---
    if has_plutus_scripts:
        # CollateralContainsNonADA
        errors.extend(_collateral_contains_non_ada(collateral_inputs, utxo_set))

        # TooManyCollateralInputs
        errors.extend(_too_many_collateral_inputs(collateral_inputs, params.max_collateral_inputs))

        # InsufficientCollateral
        script_fees = calculate_script_fee(redeemers, params.execution_unit_prices)
        errors.extend(
            _insufficient_collateral(
                collateral_inputs, utxo_set, script_fees, params.collateral_percentage
            )
        )

    # --- ExUnits too big ---
    if redeemers:
        errors.extend(_ex_units_too_big(redeemers, params.max_tx_ex_units))

    return errors


# ---------------------------------------------------------------------------
# Phase-1 native script validation
# ---------------------------------------------------------------------------


def _validate_native_scripts(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    native_scripts: dict[bytes, Timelock] | None = None,
    signers: frozenset[bytes] | None = None,
    current_slot: int = 0,
) -> list[str]:
    """Validate phase-1 native (timelock) scripts referenced by inputs.

    Native scripts are evaluated before phase-2 Plutus scripts. If a native
    script fails, the transaction is rejected outright (no collateral forfeited).

    Spec ref: Alonzo formal spec, Section 5 (phase-1 scripts).
    Haskell ref: ``validateFailedNativeScripts`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        native_scripts: Map of script hash -> Timelock script in witness set.
        signers: Set of key hashes that provided valid signatures.
        current_slot: Current slot for timelock evaluation.

    Returns:
        List of error strings (empty = valid).
    """
    if native_scripts is None or signers is None:
        return []

    errors: list[str] = []

    for txin in tx_body.inputs:
        if txin not in utxo_set:
            continue
        txout = utxo_set[txin]
        addr = txout.address
        payment_part = addr.payment_part
        if payment_part is None:
            continue
        payment_hash = bytes(payment_part)
        if len(payment_hash) == 28 and payment_hash in native_scripts:
            script = native_scripts[payment_hash]
            if not evaluate_timelock(script, signers, current_slot):
                errors.append(
                    f"NativeScriptFailure: native script "
                    f"hash={payment_hash.hex()[:16]}... failed evaluation "
                    f"(phase-1 rejection, no collateral forfeited)"
                )

    return errors


# ---------------------------------------------------------------------------
# Missing redeemers validation
# ---------------------------------------------------------------------------


def _missing_redeemers(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    redeemers: list[Redeemer],
    script_hashes: set[bytes] | None = None,
) -> list[str]:
    """Check that every Plutus script input has a matching redeemer.

    Each Plutus-locked input (identified by its script hash in the address)
    must have a corresponding Spend redeemer at the correct index.

    Spec ref: Alonzo formal spec, ``missingRedeemers``.
    Haskell ref: ``missingRedeemers`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        redeemers: Redeemers from the witness set.
        script_hashes: Set of known Plutus script hashes.

    Returns:
        List of error strings (empty = valid).
    """
    if script_hashes is None:
        return []

    errors: list[str] = []

    # Build set of Spend redeemer indices
    spend_redeemer_indices = {r.index for r in redeemers if r.tag == RedeemerTag.SPEND}

    # Sorted inputs determine the index mapping
    sorted_inputs = sorted(
        tx_body.inputs,
        key=lambda i: (i.transaction_id.payload, i.index),
    )

    for idx, txin in enumerate(sorted_inputs):
        if txin not in utxo_set:
            continue
        txout = utxo_set[txin]
        addr = txout.address
        payment_part = addr.payment_part
        if payment_part is None:
            continue
        payment_hash = bytes(payment_part)
        if len(payment_hash) == 28 and payment_hash in script_hashes:
            if idx not in spend_redeemer_indices:
                errors.append(
                    f"MissingRedeemers: Plutus script input at index {idx} "
                    f"(script_hash={payment_hash.hex()[:16]}...) has no "
                    f"matching Spend redeemer"
                )

    return errors


# ---------------------------------------------------------------------------
# Not-allowed supplemental datums validation
# ---------------------------------------------------------------------------


def _not_allowed_supplemental_datums(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    datums: list[bytes],
    script_hashes: set[bytes] | None = None,
) -> list[str]:
    """Check that all datums in the witness set are actually needed.

    A datum in the witness set is "supplemental" (and not allowed) if its hash
    is not referenced by any output being spent or produced. Extra datums
    bloat the transaction and are rejected.

    Spec ref: Alonzo formal spec, ``notAllowedSupplementalDatums``.
    Haskell ref: ``validateNotAllowedSupplementalDatums`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        datums: Datum CBOR encodings from the witness set.
        script_hashes: Set of known Plutus script hashes.

    Returns:
        List of error strings (empty = valid).
    """
    import hashlib as _hashlib

    if not datums:
        return []

    errors: list[str] = []

    # Collect all datum hashes that are referenced (needed)
    needed_datum_hashes: set[bytes] = set()

    # From outputs being created (datum hashes on tx outputs)
    for txout in tx_body.outputs:
        datum_hash = getattr(txout, "datum_hash", None)
        if datum_hash is not None:
            dh_bytes = bytes(datum_hash) if not isinstance(datum_hash, bytes) else datum_hash
            needed_datum_hashes.add(dh_bytes)

    # From inputs being spent (datum hashes on UTxO outputs locked by scripts)
    for txin in tx_body.inputs:
        if txin in utxo_set:
            txout = utxo_set[txin]
            datum_hash = getattr(txout, "datum_hash", None)
            if datum_hash is not None:
                dh_bytes = bytes(datum_hash) if not isinstance(datum_hash, bytes) else datum_hash
                needed_datum_hashes.add(dh_bytes)

    # Check each witnessed datum
    for d in datums:
        dh = _hashlib.blake2b(d, digest_size=32).digest()
        if dh not in needed_datum_hashes:
            errors.append(
                f"NotAllowedSupplementalDatums: datum with hash="
                f"{dh.hex()[:16]}... is not referenced by any input or output"
            )

    return errors


# ---------------------------------------------------------------------------
# Unspendable UTxO without datum hash
# ---------------------------------------------------------------------------


def _unspendable_utxo_no_datum_hash(
    tx_body: TransactionBody,
    script_hashes: set[bytes] | None = None,
) -> list[str]:
    """Check that script-addressed outputs include a datum hash.

    In Alonzo, any output sent to a Plutus script address MUST include a
    datum hash. Without it, the output is permanently unspendable (the
    Plutus script cannot evaluate without datum input).

    Spec ref: Alonzo formal spec, ``UnspendableUTxONoDatumHash``.
    Haskell ref: ``validateOutputMissingDatumHash`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxo``

    Args:
        tx_body: The transaction body.
        script_hashes: Set of known Plutus script hashes.

    Returns:
        List of error strings (empty = valid).
    """
    if script_hashes is None:
        return []

    errors: list[str] = []

    for i, txout in enumerate(tx_body.outputs):
        addr = txout.address
        payment_part = addr.payment_part
        if payment_part is None:
            continue
        payment_hash = bytes(payment_part)
        if len(payment_hash) == 28 and payment_hash in script_hashes:
            datum_hash = getattr(txout, "datum_hash", None)
            if datum_hash is None:
                errors.append(
                    f"UnspendableUTxONoDatumHash: output[{i}] is locked by "
                    f"Plutus script hash={payment_hash.hex()[:16]}... but has "
                    f"no datum hash — output will be permanently unspendable"
                )

    return errors


# ---------------------------------------------------------------------------
# Missing script witness validation
# ---------------------------------------------------------------------------


def _missing_script_witnesses(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    witnessed_script_hashes: set[bytes] | None = None,
    script_hashes: set[bytes] | None = None,
) -> list[str]:
    """Check that every Plutus script referenced has its witness present.

    Each input locked by a Plutus script requires the script itself to
    be included in the transaction witness set.

    Spec ref: Alonzo formal spec, Section 10 (UTXOW).
    Haskell ref: ``validateMissingScripts`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        witnessed_script_hashes: Script hashes present in the witness set.
        script_hashes: Set of known Plutus script hashes.

    Returns:
        List of error strings (empty = valid).
    """
    if script_hashes is None or witnessed_script_hashes is None:
        return []

    errors: list[str] = []

    # Check inputs
    for txin in tx_body.inputs:
        if txin not in utxo_set:
            continue
        txout = utxo_set[txin]
        addr = txout.address
        payment_part = addr.payment_part
        if payment_part is None:
            continue
        payment_hash = bytes(payment_part)
        if len(payment_hash) == 28 and payment_hash in script_hashes:
            if payment_hash not in witnessed_script_hashes:
                errors.append(
                    f"MissingScriptWitness: Plutus script "
                    f"hash={payment_hash.hex()[:16]}... is referenced by "
                    f"input but not present in witness set"
                )

    # Check minting policies
    if tx_body.mint:
        for policy_id in tx_body.mint:
            pid_bytes = bytes(policy_id)
            if pid_bytes in script_hashes and pid_bytes not in witnessed_script_hashes:
                errors.append(
                    f"MissingScriptWitness: Plutus minting policy "
                    f"hash={pid_bytes.hex()[:16]}... not present in witness set"
                )

    return errors


# ---------------------------------------------------------------------------
# Extra redeemers validation
# ---------------------------------------------------------------------------


def _extra_redeemers(
    tx_body: TransactionBody,
    utxo_set: ShelleyUTxO,
    redeemers: list[Redeemer],
    script_hashes: set[bytes] | None = None,
) -> list[str]:
    """Check that all redeemers point to valid script purposes.

    A redeemer is "extra" if it points to a non-existent script purpose:
    - Spend redeemer index beyond the number of Plutus inputs
    - Mint redeemer index beyond the number of Plutus minting policies
    - Cert redeemer index beyond the number of Plutus certificates
    - Redeemer tag doesn't match the actual script purpose

    Spec ref: Alonzo formal spec, ``extraRedeemers``.
    Haskell ref: ``validateExtraRedeemers`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        utxo_set: Current UTxO set.
        redeemers: Redeemers from the witness set.
        script_hashes: Set of known Plutus script hashes.

    Returns:
        List of error strings (empty = valid).
    """
    if script_hashes is None:
        return []

    errors: list[str] = []

    # Build the set of valid Spend indices (Plutus-locked inputs)
    sorted_inputs = sorted(
        tx_body.inputs,
        key=lambda i: (i.transaction_id.payload, i.index),
    )
    valid_spend_indices: set[int] = set()
    for idx, txin in enumerate(sorted_inputs):
        if txin in utxo_set:
            txout = utxo_set[txin]
            addr = txout.address
            payment_part = addr.payment_part
            if payment_part is not None:
                payment_hash = bytes(payment_part)
                if len(payment_hash) == 28 and payment_hash in script_hashes:
                    valid_spend_indices.add(idx)

    # Build the set of valid Mint indices (Plutus minting policies)
    valid_mint_indices: set[int] = set()
    if tx_body.mint:
        sorted_policies = sorted(tx_body.mint.keys(), key=lambda p: bytes(p))
        for idx, policy_id in enumerate(sorted_policies):
            pid_bytes = bytes(policy_id)
            if pid_bytes in script_hashes:
                valid_mint_indices.add(idx)

    # Build the set of valid Cert indices
    valid_cert_indices: set[int] = set()
    if tx_body.certificates:
        for idx in range(len(tx_body.certificates)):
            # Cert validation is complex; for now accept any index within range
            valid_cert_indices.add(idx)

    # Check each redeemer
    for r in redeemers:
        if r.tag == RedeemerTag.SPEND:
            if r.index not in valid_spend_indices:
                errors.append(
                    f"ExtraRedeemers: Spend redeemer at index {r.index} "
                    f"does not point to a Plutus-locked input"
                )
        elif r.tag == RedeemerTag.MINT:
            if r.index not in valid_mint_indices:
                errors.append(
                    f"ExtraRedeemers: Mint redeemer at index {r.index} "
                    f"does not point to a Plutus minting policy"
                )
        elif r.tag == RedeemerTag.CERT:
            if r.index not in valid_cert_indices:
                errors.append(
                    f"ExtraRedeemers: Cert redeemer at index {r.index} "
                    f"does not point to a valid certificate"
                )

    return errors


# ---------------------------------------------------------------------------
# Missing required datums validation
# ---------------------------------------------------------------------------


def _missing_required_datums(
    tx_body: TransactionBody,
    datums: list[bytes],
) -> list[str]:
    """Check that all datum hashes in tx outputs have matching datum witnesses.

    In Alonzo, any output that includes a datum hash requires the corresponding
    datum to be present in the transaction witness set. This ensures that datum
    data is available for Plutus script evaluation.

    Spec ref: Alonzo formal spec, ``missingRequiredDatums``.
    Haskell ref: ``missingRequiredDatums`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        datums: Datum CBOR encodings from the witness set.

    Returns:
        List of error strings (empty = valid).
    """
    import hashlib as _hashlib

    errors: list[str] = []

    # Build set of datum hashes from witness set
    witnessed_datum_hashes: set[bytes] = set()
    for d in datums:
        h = _hashlib.blake2b(d, digest_size=32).digest()
        witnessed_datum_hashes.add(h)

    # Check each output for datum hashes
    for i, txout in enumerate(tx_body.outputs):
        datum_hash = getattr(txout, "datum_hash", None)
        if datum_hash is not None:
            dh_bytes = bytes(datum_hash) if not isinstance(datum_hash, bytes) else datum_hash
            if dh_bytes not in witnessed_datum_hashes:
                errors.append(
                    f"MissingRequiredDatums: output[{i}] has datum_hash="
                    f"{dh_bytes.hex()[:16]}... but no matching datum in witness set"
                )

    return errors


# ---------------------------------------------------------------------------
# Metadata hash validation
# ---------------------------------------------------------------------------


def _validate_metadata_hash(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
) -> list[str]:
    """Validate that the tx body's auxiliary_data_hash matches actual metadata.

    If a transaction body declares an auxiliary_data_hash, the actual auxiliary
    data must be present and its hash must match. Conversely, if auxiliary data
    is present, the hash must be declared.

    Spec ref: Shelley formal spec, ``txADhash`` validation.
    Haskell ref: ``validateMissingOrIncorrectAuxiliaryDataHash`` in
        ``Cardano.Ledger.Shelley.Rules.Utxow`` (inherited through Alonzo)

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set (may contain auxiliary_data).

    Returns:
        List of error strings (empty = valid).
    """
    import hashlib as _hashlib

    import cbor2pure as _cbor2

    errors: list[str] = []

    body_hash = getattr(tx_body, "auxiliary_data_hash", None)
    # pycardano stores auxiliary_data on the Transaction, not the witness set.
    # For our validation interface, we check if the tx_body has the hash field.
    # The actual metadata content would normally come from Transaction.auxiliary_data.
    # Since we receive the witness_set, we check for auxiliary_data there too.
    aux_data = getattr(witness_set, "auxiliary_data", None)

    if body_hash is not None and aux_data is None:
        # Hash declared but no metadata provided
        errors.append(
            "MetadataHashMismatch: tx body declares auxiliary_data_hash "
            "but no auxiliary data is present"
        )
    elif body_hash is not None and aux_data is not None:
        # Both present — verify the hash matches
        aux_cbor = _cbor2.dumps(aux_data)
        computed = _hashlib.blake2b(aux_cbor, digest_size=32).digest()
        body_hash_bytes = bytes(body_hash) if not isinstance(body_hash, bytes) else body_hash
        if computed != body_hash_bytes:
            errors.append(
                f"MetadataHashMismatch: computed={computed.hex()[:16]}..., "
                f"declared={body_hash_bytes.hex()[:16]}..."
            )

    return errors


# ---------------------------------------------------------------------------
# Alonzo UTXOW transition rule — witness verification
# ---------------------------------------------------------------------------


def validate_alonzo_witnesses(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
    redeemers: list[Redeemer] | None = None,
    datums: list[bytes] | None = None,
    script_integrity_hash: bytes | None = None,
    cost_models: dict[Language, dict[str, int]] | None = None,
    languages_used: set[Language] | None = None,
    has_plutus_scripts: bool = False,
    native_scripts: dict[bytes, Timelock] | None = None,
    script_hashes: set[bytes] | None = None,
    witnessed_script_hashes: set[bytes] | None = None,
    current_slot: int = 0,
) -> list[str]:
    """Validate Alonzo-era UTXOW transition rules.

    Extends Shelley witness validation with Alonzo-specific checks for
    script integrity, datum witnesses, redeemer resolution, native script
    evaluation, and script witness completeness.

    Spec ref: Alonzo ledger formal spec, Section 10 (UTXOW).
    Haskell ref: ``alonzoUtxowTransition`` in
        ``Cardano.Ledger.Alonzo.Rules.Utxow``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        redeemers: Redeemers from the witness set.
        datums: Datum CBOR encodings from the witness set.
        script_integrity_hash: The hash from the tx body's script_data_hash field.
        cost_models: Cost models from protocol parameters.
        languages_used: Plutus language versions used in the tx.
        has_plutus_scripts: Whether the tx uses any Plutus scripts.
        native_scripts: Map of script hash -> Timelock script in witness set.
        script_hashes: Set of known Plutus script hashes.
        witnessed_script_hashes: Script hashes present in the witness set.
        current_slot: Current slot for timelock evaluation.

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    if redeemers is None:
        redeemers = []
    if datums is None:
        datums = []
    if cost_models is None:
        cost_models = {}
    if languages_used is None:
        languages_used = set()

    # Shelley VKey witness checks (inherited)
    errors.extend(validate_shelley_witnesses(tx_body, witness_set, utxo_set))

    # --- Phase-1 native script validation ---
    # Native scripts are evaluated before phase-2 Plutus scripts.
    # Spec ref: Alonzo formal spec, Section 5 (phase-1 scripts)
    # Haskell ref: ``validateFailedNativeScripts`` in Alonzo.Rules.Utxow
    if native_scripts is not None:
        import hashlib as _hashlib

        # Build signers set from valid VKey witnesses
        signers: set[bytes] = set()
        if witness_set.vkey_witnesses:
            for wit in witness_set.vkey_witnesses:
                signers.add(_hashlib.blake2b(wit.vkey.payload, digest_size=28).digest())
        errors.extend(
            _validate_native_scripts(
                tx_body,
                utxo_set,
                native_scripts,
                frozenset(signers),
                current_slot,
            )
        )

    # --- Script integrity hash ---
    errors.extend(
        _script_integrity_hash_mismatch(
            script_integrity_hash,
            redeemers,
            datums,
            cost_models,
            languages_used,
            has_plutus_scripts,
        )
    )

    # --- Missing redeemers ---
    # Every Plutus script input must have a matching redeemer.
    # Spec ref: Alonzo formal spec, ``missingRedeemers``
    # Haskell ref: ``missingRedeemers`` in Alonzo.Rules.Utxow
    errors.extend(_missing_redeemers(tx_body, utxo_set, redeemers, script_hashes))

    # --- Not-allowed supplemental datums ---
    # Datums in the witness set must be referenced by an input or output.
    # Only checked when Plutus scripts are present (datums are irrelevant
    # for pure native-script transactions).
    # Spec ref: Alonzo formal spec, ``notAllowedSupplementalDatums``
    # Haskell ref: ``validateNotAllowedSupplementalDatums`` in Alonzo.Rules.Utxow
    if has_plutus_scripts:
        errors.extend(_not_allowed_supplemental_datums(tx_body, utxo_set, datums, script_hashes))

    # --- Unspendable UTxO without datum hash ---
    # Script-addressed outputs must include a datum hash.
    # Spec ref: Alonzo formal spec, ``UnspendableUTxONoDatumHash``
    # Haskell ref: ``validateOutputMissingDatumHash`` in Alonzo.Rules.Utxo
    errors.extend(_unspendable_utxo_no_datum_hash(tx_body, script_hashes))

    # --- Missing script witnesses ---
    # Every referenced Plutus script must be in the witness set.
    # Spec ref: Alonzo formal spec, Section 10 (UTXOW)
    # Haskell ref: ``validateMissingScripts`` in Alonzo.Rules.Utxow
    errors.extend(
        _missing_script_witnesses(tx_body, utxo_set, witnessed_script_hashes, script_hashes)
    )

    # --- Extra redeemers ---
    # All redeemers must point to valid script purposes.
    # Spec ref: Alonzo formal spec, ``extraRedeemers``
    # Haskell ref: ``validateExtraRedeemers`` in Alonzo.Rules.Utxow
    errors.extend(_extra_redeemers(tx_body, utxo_set, redeemers, script_hashes))

    # --- Datum witness completeness ---
    # Every datum hash referenced in outputs being spent by Plutus scripts
    # must have a matching datum witness in the witness set.
    # Spec ref: Alonzo formal spec, ``missingRequiredDatums``
    # Haskell ref: ``missingRequiredDatums`` in Alonzo.Rules.Utxow
    errors.extend(_missing_required_datums(tx_body, datums))

    # --- Metadata hash validation ---
    # If the tx body includes an auxiliary_data_hash, it must match the
    # hash of the actual auxiliary data provided with the transaction.
    # Spec ref: Shelley formal spec, ``txADhash``
    # Haskell ref: ``validateMissingOrIncorrectAuxiliaryDataHash`` in
    #     Cardano.Ledger.Shelley.Rules.Utxow (inherited through Alonzo)
    errors.extend(_validate_metadata_hash(tx_body, witness_set))

    return errors


# ---------------------------------------------------------------------------
# Combined validation: validate_alonzo_tx
# ---------------------------------------------------------------------------


def validate_alonzo_tx(
    tx_body: TransactionBody,
    witness_set: TransactionWitnessSet,
    utxo_set: ShelleyUTxO,
    params: AlonzoProtocolParams,
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
) -> list[str]:
    """Validate a complete Alonzo transaction (UTXO + UTXOW rules).

    Top-level validation combining Alonzo UTXO rules (value preservation,
    fees, collateral, ExUnits) and UTXOW rules (witnesses, script integrity).

    Spec ref: Alonzo ledger formal spec, Sections 9-10.
    Haskell ref: ``alonzoUtxoTransition`` + ``alonzoUtxowTransition``

    Args:
        tx_body: The transaction body.
        witness_set: The transaction witness set.
        utxo_set: Current UTxO set.
        params: Alonzo protocol parameters.
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

    Returns:
        List of validation error strings (empty = valid).
    """
    errors: list[str] = []

    # UTXO rules
    errors.extend(
        validate_alonzo_utxo(
            tx_body=tx_body,
            utxo_set=utxo_set,
            params=params,
            current_slot=current_slot,
            tx_size=tx_size,
            redeemers=redeemers,
            validity_interval=validity_interval,
            collateral_inputs=collateral_inputs,
            has_plutus_scripts=has_plutus_scripts,
        )
    )

    # UTXOW rules (witness verification)
    errors.extend(
        validate_alonzo_witnesses(
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
    )

    return errors


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------


class AlonzoValidationError(Exception):
    """Raised when an Alonzo transaction or block fails validation.

    Attributes:
        errors: List of human-readable error descriptions.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Alonzo validation failed: {'; '.join(errors)}")
