"""Plutus script evaluation bridge to the uplc CEK machine.

This module provides the interface between vibe-node's ledger validation
and the uplc package for evaluating Plutus scripts. It handles:

1. Deserializing on-chain script bytes into uplc AST (flat decoding)
2. Converting PlutusData arguments to uplc AST representations
3. Running the CEK machine with proper budgets and cost models
4. Returning structured results with consumed ExUnits

Spec references:
    * Alonzo ledger formal spec, Section 4.1 (Script evaluation)
    * Alonzo ledger formal spec, Section 4.4 (Evaluating scripts)
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Plutus/Evaluate.hs``

Haskell references:
    * ``evalPlutusScript`` in ``Cardano.Ledger.Alonzo.Plutus.Evaluate``
    * ``evaluateScriptCounting`` / ``evaluateScriptRestricting``
      in ``PlutusLedgerApi``
    * ``deserialiseScript`` in ``Cardano.Ledger.Plutus.Language``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusData,
    PlutusInteger,
    PlutusList,
    PlutusMap,
    Program,
)
from uplc.cost_model import (
    Budget,
    BuiltinCostModel,
    CekMachineCostModel,
    default_budget,
    default_builtin_cost_model_plutus_v1,
    default_builtin_cost_model_plutus_v2,
    default_builtin_cost_model_plutus_v3,
    default_cek_machine_cost_model_plutus_v1,
    default_cek_machine_cost_model_plutus_v2,
    default_cek_machine_cost_model_plutus_v3,
)
from uplc.machine import ComputationResult, Machine
from uplc.tools import unflatten

from vibe.cardano.plutus.cost_model import CostModel, ExUnits, PlutusVersion

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evaluation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvalResult:
    """Result of evaluating a Plutus script.

    Spec ref: Alonzo ledger formal spec, script evaluation outcome.
    Haskell ref: ``ScriptResult`` in ``Cardano.Ledger.Alonzo.Plutus.Evaluate``

    Attributes:
        success: True if script evaluated successfully (returned without error).
        ex_units_consumed: Actual execution units consumed by the script.
        logs: Trace messages emitted by the script (via ``trace`` builtin).
        error: Error message if evaluation failed; None on success.
    """

    success: bool
    ex_units_consumed: ExUnits
    logs: list[str]
    error: str | None = None


# ---------------------------------------------------------------------------
# uplc cost model resolution
# ---------------------------------------------------------------------------


def _get_uplc_cost_models(
    version: PlutusVersion,
) -> tuple[CekMachineCostModel, BuiltinCostModel]:
    """Get the default uplc cost models for a given Plutus version.

    When we have actual on-chain cost model parameters (CostModel), we would
    apply them here. For now, we use uplc's built-in defaults which track
    the current mainnet parameters.

    TODO(VNODE-XXX): Apply CostModel parameter vector to override uplc defaults
    when the ledger provides specific cost model params from protocol parameters.
    """
    match version:
        case PlutusVersion.V1:
            return (
                default_cek_machine_cost_model_plutus_v1(),
                default_builtin_cost_model_plutus_v1(),
            )
        case PlutusVersion.V2:
            return (
                default_cek_machine_cost_model_plutus_v2(),
                default_builtin_cost_model_plutus_v2(),
            )
        case PlutusVersion.V3:
            return (
                default_cek_machine_cost_model_plutus_v3(),
                default_builtin_cost_model_plutus_v3(),
            )


# ---------------------------------------------------------------------------
# Script deserialization
# ---------------------------------------------------------------------------


def deserialize_script(
    script_bytes: bytes,
    *,
    version: PlutusVersion | None = None,
) -> Program:
    """Deserialize a Plutus script from its on-chain byte representation.

    On-chain Plutus scripts are double-CBOR-wrapped flat-encoded UPLC programs.
    The outer CBOR wrapping is a bytestring containing the inner CBOR+flat data.

    PlutusV3 uses strict deserialization: trailing bytes after the flat-encoded
    program cause rejection. PlutusV1/V2 are lenient (trailing bytes ignored).

    Spec ref: Alonzo ledger formal spec, ``deserialiseScript``.
    Haskell ref: ``deserialiseScript`` in ``Cardano.Ledger.Plutus.Language``

    Args:
        script_bytes: The raw script bytes (outer CBOR bytestring wrapping
            a flat-encoded UPLC program).
        version: Plutus version. If V3, strict mode rejects trailing bytes.

    Returns:
        Parsed uplc Program AST.

    Raises:
        ValueError: If deserialization fails or V3 has trailing bytes.
    """
    import cbor2pure as cbor2

    strict = version == PlutusVersion.V3

    try:
        # On-chain scripts are double-CBOR-wrapped:
        # outer CBOR decode yields a bytestring, which is the flat-encoded program.
        inner_bytes = cbor2.loads(script_bytes)
        if isinstance(inner_bytes, bytes):
            return unflatten(inner_bytes, strict=strict)
        else:
            # Single-wrapped -- try direct unflatten
            return unflatten(script_bytes, strict=strict)
    except Exception as e:
        raise ValueError(f"Failed to deserialize Plutus script: {e}") from e


# ---------------------------------------------------------------------------
# PlutusData conversion: pycardano -> uplc
# ---------------------------------------------------------------------------


def pycardano_to_uplc_data(data: object) -> PlutusData:
    """Convert a pycardano PlutusData object to an uplc PlutusData AST node.

    pycardano represents Plutus data using its own type hierarchy. This
    function maps those types to the corresponding uplc AST types.

    Mapping:
        pycardano.plutus.RawPlutusData(CBORTag) -> PlutusConstr
        pycardano.plutus.PlutusData (dataclass) -> PlutusConstr
        int -> PlutusInteger
        bytes -> PlutusByteString
        list -> PlutusList
        dict -> PlutusMap
        pycardano.plutus.Datum variants -> recursive conversion

    Haskell ref: ``Data`` type in ``PlutusCore.Data``

    Args:
        data: A pycardano PlutusData object, or a raw Python type
            (int, bytes, list, dict) that maps directly.

    Returns:
        uplc PlutusData AST node.

    Raises:
        TypeError: If the input type cannot be converted.
    """
    # Handle None (used for missing datum in spending validators)
    if data is None:
        raise TypeError("Cannot convert None to PlutusData")

    # Already an uplc type -- pass through
    if isinstance(data, PlutusData):
        return data

    # Python int -> PlutusInteger
    if isinstance(data, int) and not isinstance(data, bool):
        return PlutusInteger(data)

    # Python bytes -> PlutusByteString
    if isinstance(data, bytes):
        return PlutusByteString(data)

    # Python list/tuple -> PlutusList
    if isinstance(data, (list, tuple)):
        return PlutusList([pycardano_to_uplc_data(item) for item in data])

    # Python dict -> PlutusMap
    if isinstance(data, dict):
        return PlutusMap(
            {pycardano_to_uplc_data(k): pycardano_to_uplc_data(v) for k, v in data.items()}
        )

    # pycardano RawPlutusData (wraps a CBORTag)
    try:
        from pycardano.plutus import RawPlutusData
    except ImportError:
        RawPlutusData = None

    if RawPlutusData is not None and isinstance(data, RawPlutusData):
        return _convert_raw_plutus_data(data)

    # pycardano PlutusData (user-defined dataclass subclass)
    try:
        from pycardano.plutus import PlutusData as PyCardanoPlutusData
    except ImportError:
        PyCardanoPlutusData = None

    if PyCardanoPlutusData is not None and isinstance(data, PyCardanoPlutusData):
        # pycardano PlutusData serializes to CBOR -- we can round-trip through that
        return _convert_pycardano_plutus_data(data)

    raise TypeError(
        f"Cannot convert {type(data).__name__} to uplc PlutusData. "
        f"Expected int, bytes, list, dict, or pycardano PlutusData."
    )


def _convert_raw_plutus_data(data: object) -> PlutusData:
    """Convert a pycardano RawPlutusData to uplc PlutusData.

    RawPlutusData wraps a cbor2.CBORTag. We decode the tag structure
    to determine if it's a Constr, and recursively convert fields.
    """
    import cbor2pure as cbor2

    raw_data = data.data  # type: ignore[attr-defined] -- CBORTag or primitive

    if isinstance(raw_data, cbor2.CBORTag):
        return _cbor_tag_to_plutus_data(raw_data)

    # Primitive value (int, bytes, list, dict)
    return _cbor_value_to_plutus_data(raw_data)


def _convert_pycardano_plutus_data(data: object) -> PlutusData:
    """Convert a pycardano PlutusData dataclass to uplc PlutusData.

    We serialize to CBOR and then re-decode into uplc types. This is the
    most robust approach since pycardano's PlutusData can have complex
    nested structures.
    """
    import cbor2pure as cbor2

    cbor_bytes = data.to_cbor()  # type: ignore[attr-defined]
    raw = cbor2.loads(cbor_bytes)
    return _cbor_value_to_plutus_data(raw)


def _cbor_tag_to_plutus_data(tag: object) -> PlutusData:
    """Convert a cbor2.CBORTag to a PlutusConstr.

    Cardano's CBOR encoding for constructors:
        - Tags 121-127: constructors 0-6, value is the fields list
        - Tags 1280-1400: constructors 7-127
        - Tag 102: general constructor [constr_id, fields]

    This matches the Haskell ``Data`` CBOR encoding.
    """
    import cbor2pure as cbor2

    assert isinstance(tag, cbor2.CBORTag)

    if 121 <= tag.tag <= 127:
        constructor = tag.tag - 121
        fields = tag.value if isinstance(tag.value, list) else []
    elif 1280 <= tag.tag <= 1400:
        constructor = tag.tag - 1280 + 7
        fields = tag.value if isinstance(tag.value, list) else []
    elif tag.tag == 102:
        constructor, fields = tag.value[0], tag.value[1]
    else:
        raise ValueError(f"Unknown CBOR tag {tag.tag} for Plutus constructor")

    converted_fields = [_cbor_value_to_plutus_data(f) for f in fields]
    return PlutusConstr(constructor, converted_fields)


def _cbor_value_to_plutus_data(value: object) -> PlutusData:
    """Convert a raw CBOR-decoded value to uplc PlutusData."""
    import cbor2pure as cbor2

    if isinstance(value, int) and not isinstance(value, bool):
        return PlutusInteger(value)

    if isinstance(value, bytes):
        return PlutusByteString(value)

    if isinstance(value, list):
        return PlutusList([_cbor_value_to_plutus_data(item) for item in value])

    if isinstance(value, dict):
        return PlutusMap(
            {
                _cbor_value_to_plutus_data(k): _cbor_value_to_plutus_data(v)
                for k, v in value.items()
            }
        )

    if isinstance(value, cbor2.CBORTag):
        return _cbor_tag_to_plutus_data(value)

    raise TypeError(f"Cannot convert CBOR value of type {type(value).__name__} to PlutusData")


# ---------------------------------------------------------------------------
# Script evaluation
# ---------------------------------------------------------------------------


def evaluate_script(
    script_bytes: bytes,
    datum: PlutusData | None,
    redeemer: PlutusData,
    script_context: PlutusData,
    ex_units: ExUnits,
    cost_model: CostModel | None = None,
    version: PlutusVersion = PlutusVersion.V2,
) -> EvalResult:
    """Evaluate a Plutus script with the given arguments.

    This is the main entry point for script evaluation in the ledger.
    It deserializes the script, applies arguments (datum, redeemer,
    script context), runs the CEK machine, and checks the result
    against the provided execution budget.

    For PlutusV1/V2 spending validators, the script takes 3 arguments:
        datum, redeemer, script_context

    For PlutusV1/V2 minting/rewarding/certifying validators:
        redeemer, script_context (datum is None)

    For PlutusV3, all scripts take a single merged argument:
        script_context (which includes redeemer inline)

    Spec ref: Alonzo ledger formal spec, Section 4.4.
    Haskell ref: ``evalPlutusScript`` in
        ``Cardano.Ledger.Alonzo.Plutus.Evaluate``

    Args:
        script_bytes: Raw on-chain script bytes (double-CBOR-wrapped flat).
        datum: Datum for spending validators; None for minting/rewarding/certifying
            or for PlutusV3 (where datum is embedded in context).
        redeemer: The redeemer provided by the transaction.
        script_context: The ScriptContext constructed from the transaction.
        ex_units: The execution budget (from the transaction's redeemers).
        cost_model: Optional cost model from protocol parameters. If None,
            uses uplc's built-in defaults for the given version.
        version: Plutus language version of the script.

    Returns:
        EvalResult with success/failure, consumed units, logs, and error.
    """
    # --- 1. Deserialize the script ---
    try:
        program = deserialize_script(script_bytes, version=version)
    except (ValueError, Exception) as e:
        _LOGGER.warning("Script deserialization failed: %s", e)
        return EvalResult(
            success=False,
            ex_units_consumed=ExUnits(mem=0, steps=0),
            logs=[],
            error=f"Script deserialization failed: {e}",
        )

    # --- 2. Build arguments list ---
    # PlutusV3 uses a single merged context argument.
    # PlutusV1/V2 spending validators get (datum, redeemer, context).
    # PlutusV1/V2 non-spending validators get (redeemer, context).
    if version == PlutusVersion.V3:
        args = [script_context]
    elif datum is not None:
        args = [datum, redeemer, script_context]
    else:
        args = [redeemer, script_context]

    # --- 3. Set up the CEK machine budget and cost models ---
    budget = Budget(cpu=ex_units.steps, memory=ex_units.mem)
    cek_cost_model, builtin_cost_model = _get_uplc_cost_models(version)

    # TODO(VNODE-XXX): When cost_model is provided, apply its parameter
    # vector to override the default builtin cost model. The uplc package
    # supports updated_builtin_cost_model_from_network_config() for this.

    # --- 4. Run the CEK machine ---
    try:
        machine = Machine(budget, cek_cost_model, builtin_cost_model)

        # Apply arguments to the program
        from uplc.tools import apply as uplc_apply

        applied_program = uplc_apply(program, *args)

        result: ComputationResult = machine.eval(applied_program)
    except Exception as e:
        _LOGGER.warning("CEK machine setup/execution failed: %s", e)
        return EvalResult(
            success=False,
            ex_units_consumed=ExUnits(mem=0, steps=0),
            logs=[],
            error=f"CEK machine error: {e}",
        )

    # --- 5. Interpret the result ---
    consumed = ExUnits(mem=result.cost.memory, steps=result.cost.cpu)
    logs = result.logs if result.logs else []

    # Check if the computation itself failed
    if isinstance(result.result, Exception):
        error_msg = str(result.result)

        # Check if it was a budget exhaustion
        if "Exhausted budget" in error_msg:
            return EvalResult(
                success=False,
                ex_units_consumed=consumed,
                logs=logs,
                error=f"ExUnits budget exceeded: {error_msg}",
            )

        return EvalResult(
            success=False,
            ex_units_consumed=consumed,
            logs=logs,
            error=f"Script evaluation error: {error_msg}",
        )

    # --- 6. Check budget compliance ---
    # Even if the script succeeded, if it consumed more than the budget
    # allows, that's a validation failure. (The Machine should already
    # have thrown "Exhausted budget", but we double-check.)
    if not consumed.fits_within(ex_units):
        return EvalResult(
            success=False,
            ex_units_consumed=consumed,
            logs=logs,
            error=(
                f"ExUnits exceeded: consumed mem={consumed.mem}, steps={consumed.steps}, "
                f"budget mem={ex_units.mem}, steps={ex_units.steps}"
            ),
        )

    return EvalResult(
        success=True,
        ex_units_consumed=consumed,
        logs=logs,
        error=None,
    )
