"""Plutus cost model types and parameter vectors.

The cost model defines the resource costs for each Plutus builtin function
and CEK machine operation. Protocol parameters include a per-language cost
model as a flat vector of integers.

Parameter counts per Plutus version:
    - PlutusV1: 166 parameters
    - PlutusV2: 175 parameters
    - PlutusV3: 233 parameters

These parameter vectors are applied to the uplc evaluator's cost model
to constrain script execution budgets.

Spec references:
    * Alonzo ledger formal spec, Section 4.2 (Cost models)
    * CIP-0055 (PlutusV3 cost model parameters)
    * ``cardano-ledger/eras/alonzo/impl/src/Cardano/Ledger/Alonzo/Scripts.hs``

Haskell references:
    * ``CostModel`` in ``Cardano.Ledger.Alonzo.Scripts``
    * ``CostModelApplyError`` in ``Cardano.Ledger.Alonzo.Scripts``
    * ``mkCostModel`` / ``getCostModelParams`` in same module
    * ``ExUnits`` in ``Cardano.Ledger.Alonzo.Scripts``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Plutus language version
# ---------------------------------------------------------------------------


class PlutusVersion(Enum):
    """Plutus language version.

    Each version corresponds to a different set of available builtins,
    a different ScriptContext shape, and a different cost model parameter count.

    Spec ref: Alonzo ledger formal spec, ``Language`` type.
    Haskell ref: ``Language`` in ``Cardano.Ledger.Plutus.Language``
    """

    V1 = 1
    V2 = 2
    V3 = 3


# Expected parameter counts per Plutus version.
# These must match the Haskell implementation exactly.
# Haskell ref: ``costModelParamsCount`` in ``Cardano.Ledger.Plutus.CostModels``
COST_MODEL_PARAM_COUNTS: dict[PlutusVersion, int] = {
    PlutusVersion.V1: 166,
    PlutusVersion.V2: 175,
    PlutusVersion.V3: 233,
}


# ---------------------------------------------------------------------------
# Plutus version availability per protocol version
# ---------------------------------------------------------------------------

# Minimum protocol major version required for each Plutus version.
# Haskell ref: ``ledgerLanguages`` in ``Cardano.Ledger.Plutus.Language``
#   - PlutusV1: introduced in Alonzo (protocol version 5)
#   - PlutusV2: introduced in Babbage (protocol version 7)
#   - PlutusV3: introduced in Conway (protocol version 9)
PLUTUS_VERSION_INTRODUCED_AT: dict[PlutusVersion, int] = {
    PlutusVersion.V1: 5,  # Alonzo: PV 5/6
    PlutusVersion.V2: 7,  # Babbage: PV 7/8
    PlutusVersion.V3: 9,  # Conway: PV 9/10
}


def is_plutus_version_available(
    plutus_version: PlutusVersion,
    protocol_version: int,
) -> bool:
    """Check if a Plutus language version is available at a given protocol version.

    Each Plutus version is introduced at a specific protocol version (era):
        - PlutusV1: Alonzo (PV >= 5)
        - PlutusV2: Babbage (PV >= 7)
        - PlutusV3: Conway (PV >= 9)

    Spec ref: Alonzo ledger formal spec, ``Language`` availability.
    Haskell ref: ``ledgerLanguages`` in ``Cardano.Ledger.Plutus.Language``

    Args:
        plutus_version: The Plutus language version to check.
        protocol_version: The major protocol version number.

    Returns:
        True if the Plutus version is available at this protocol version.
    """
    min_pv = PLUTUS_VERSION_INTRODUCED_AT.get(plutus_version)
    if min_pv is None:
        return False
    return protocol_version >= min_pv


# ---------------------------------------------------------------------------
# Builtin availability per Plutus version
# ---------------------------------------------------------------------------

# Builtins introduced in each Plutus version (not available in earlier versions).
# This maps each version to the set of builtin names added in that version.
#
# Haskell ref: ``builtinsIntroducedIn`` in ``PlutusLedgerApi.Common.Versions``
# Spec ref: CIP-0035 (PlutusV2), CIP-0055 (PlutusV3)
#
# Note: V1 builtins are the "base" set. V2 adds a small number, V3 adds many.
# We use string names matching the uplc BuiltInFun enum names.

BUILTINS_INTRODUCED_IN: dict[PlutusVersion, frozenset[str]] = {
    PlutusVersion.V1: frozenset({
        # All base builtins (0-50) — the original Alonzo set
        "AddInteger", "SubtractInteger", "MultiplyInteger", "DivideInteger",
        "QuotientInteger", "RemainderInteger", "ModInteger",
        "EqualsInteger", "LessThanInteger", "LessThanEqualsInteger",
        "AppendByteString", "ConsByteString", "SliceByteString",
        "LengthOfByteString", "IndexByteString", "EqualsByteString",
        "LessThanByteString", "LessThanEqualsByteString",
        "Sha2_256", "Sha3_256", "Blake2b_256", "VerifyEd25519Signature",
        "AppendString", "EqualsString", "EncodeUtf8", "DecodeUtf8",
        "IfThenElse", "ChooseUnit", "Trace",
        "FstPair", "SndPair",
        "ChooseList", "MkCons", "HeadList", "TailList", "NullList",
        "ChooseData", "ConstrData", "MapData", "ListData",
        "IData", "BData", "UnConstrData", "UnMapData", "UnListData",
        "UnIData", "UnBData", "EqualsData",
        "MkPairData", "MkNilData", "MkNilPairData",
    }),
    PlutusVersion.V2: frozenset({
        # V2 additions (Babbage): serialiseData and secp256k1 builtins
        "SerialiseData",
        "VerifyEcdsaSecp256k1Signature",
        "VerifySchnorrSecp256k1Signature",
    }),
    PlutusVersion.V3: frozenset({
        # V3 additions (Conway): BLS12-381, bitwise operations, new hashes
        "Bls12_381_G1_Add", "Bls12_381_G1_Neg", "Bls12_381_G1_ScalarMul",
        "Bls12_381_G1_Equal", "Bls12_381_G1_Compress", "Bls12_381_G1_Uncompress",
        "Bls12_381_G1_HashToGroup",
        "Bls12_381_G2_Add", "Bls12_381_G2_Neg", "Bls12_381_G2_ScalarMul",
        "Bls12_381_G2_Equal", "Bls12_381_G2_Compress", "Bls12_381_G2_Uncompress",
        "Bls12_381_G2_HashToGroup",
        "Bls12_381_MillerLoop", "Bls12_381_MulMlResult", "Bls12_381_FinalVerify",
        "Keccak_256", "Blake2b_224",
        "IntegerToByteString", "ByteStringToInteger",
        "AndByteString", "OrByteString", "XorByteString", "ComplementByteString",
        "ReadBit", "WriteBits", "ReplicateByte",
        "ShiftByteString", "RotateByteString",
        "CountSetBits", "FindFirstSetBit",
        "Ripemd_160",
    }),
}


def builtins_available_at(plutus_version: PlutusVersion) -> frozenset[str]:
    """Return the set of all builtin names available at a given Plutus version.

    V2 includes all V1 builtins plus V2 additions.
    V3 includes all V1+V2 builtins plus V3 additions.

    Haskell ref: ``builtinsAvailableIn`` in ``PlutusLedgerApi.Common.Versions``

    Args:
        plutus_version: The Plutus language version.

    Returns:
        Frozenset of builtin name strings available at this version.
    """
    result: set[str] = set()
    for version in PlutusVersion:
        result |= BUILTINS_INTRODUCED_IN.get(version, frozenset())
        if version == plutus_version:
            break
    return frozenset(result)


# ---------------------------------------------------------------------------
# Cost model parameter names
# ---------------------------------------------------------------------------

# Ordered parameter names for each Plutus version's cost model.
# These are the canonical names used in protocol parameter updates and
# on-chain governance proposals. The order defines the index mapping.
#
# Haskell ref: ``costModelParamNames`` in ``Cardano.Ledger.Plutus.CostModels``
#
# NOTE: These are loaded lazily from the uplc package's network config files,
# which contain the canonical parameter names as JSON keys sorted alphabetically.
# We cache them on first access.

_COST_MODEL_PARAM_NAMES_CACHE: dict[PlutusVersion, tuple[str, ...]] = {}


def cost_model_param_names(version: PlutusVersion) -> tuple[str, ...]:
    """Get the ordered parameter names for a Plutus version's cost model.

    Parameter names follow the convention from the Haskell implementation,
    e.g., "addInteger-cpu-arguments-intercept", "addInteger-cpu-arguments-slope".

    The names are extracted from the uplc package's network config files,
    which mirror the on-chain cost model parameter ordering.

    Haskell ref: ``costModelParamNames`` in ``Cardano.Ledger.Plutus.CostModels``

    Args:
        version: The Plutus language version.

    Returns:
        Tuple of parameter name strings in canonical order.
    """
    if version not in _COST_MODEL_PARAM_NAMES_CACHE:
        _COST_MODEL_PARAM_NAMES_CACHE[version] = _load_param_names(version)
    return _COST_MODEL_PARAM_NAMES_CACHE[version]


def _load_param_names(version: PlutusVersion) -> tuple[str, ...]:
    """Load parameter names from the uplc network config.

    The network config JSON has parameter names as keys, sorted alphabetically.
    We filter out CEK machine cost keys (cek*) since those are separate.
    """
    import json
    from pathlib import Path

    # Use the latest uplc network config
    config_dir = Path(__file__).parent
    # Walk up to find the uplc package's config
    try:
        import uplc.cost_model as uplc_cm
        config_dir = Path(uplc_cm.__file__).parent / "cost_model_files"
    except ImportError:
        return ()

    # Find the latest dated directory
    latest_dir = None
    for d in sorted(config_dir.iterdir()):
        if d.is_dir() and d.name != "base":
            latest_dir = d

    if latest_dir is None:
        return ()

    config_file = latest_dir / "cost-model-merged.json"
    if not config_file.exists():
        return ()

    with open(config_file) as f:
        data = json.load(f)

    version_key = f"PlutusV{version.value}"
    if version_key not in data:
        return ()

    # Include ALL parameters (both builtin and CEK machine costs).
    # The on-chain cost model parameter vector is a flat array that
    # includes both builtin cost params and CEK machine cost params.
    # The sorted alphabetical order defines the canonical index mapping.
    # Haskell ref: ``costModelParamsForScriptHash`` which includes all params.
    all_keys = sorted(data[version_key].keys())
    return tuple(all_keys)


def param_name_to_index(version: PlutusVersion, name: str) -> int:
    """Convert a cost model parameter name to its index.

    Args:
        version: The Plutus language version.
        name: The parameter name string.

    Returns:
        The integer index of this parameter in the cost model vector.

    Raises:
        KeyError: If the name is not a valid parameter for this version.
    """
    names = cost_model_param_names(version)
    try:
        return names.index(name)
    except ValueError:
        raise KeyError(
            f"Parameter '{name}' not found in {version.name} cost model"
        ) from None


def param_index_to_name(version: PlutusVersion, index: int) -> str:
    """Convert a cost model parameter index to its name.

    Args:
        version: The Plutus language version.
        index: The parameter index.

    Returns:
        The parameter name string.

    Raises:
        IndexError: If the index is out of range.
    """
    names = cost_model_param_names(version)
    if index < 0 or index >= len(names):
        raise IndexError(
            f"Parameter index {index} out of range for {version.name} "
            f"(has {len(names)} parameters)"
        )
    return names[index]


# ---------------------------------------------------------------------------
# ExUnits -- execution budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExUnits:
    """Execution units budget for a Plutus script.

    Spec ref: Alonzo ledger formal spec, ``ExUnits = (Natural, Natural)``.
    Haskell ref: ``ExUnits`` in ``Cardano.Ledger.Alonzo.Scripts``

    Attributes:
        mem: Memory units budget.
        steps: CPU steps budget.
    """

    mem: int
    steps: int

    def __post_init__(self) -> None:
        if self.mem < 0:
            raise ValueError(f"Memory budget must be non-negative, got {self.mem}")
        if self.steps < 0:
            raise ValueError(f"Steps budget must be non-negative, got {self.steps}")

    def fits_within(self, budget: ExUnits) -> bool:
        """Check if these units fit within a given budget.

        Both mem and steps must be <= the budget's respective values.
        """
        return self.mem <= budget.mem and self.steps <= budget.steps


# ---------------------------------------------------------------------------
# CostModel -- per-language parameter vector
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostModel:
    """Plutus cost model: a versioned parameter vector.

    The cost model is a flat list of integers that parameterizes the cost
    functions for each Plutus builtin. The parameter order is defined by the
    Haskell implementation and must match exactly.

    Spec ref: Alonzo ledger formal spec, Section 4.2 (Cost models).
    Haskell ref: ``CostModel`` in ``Cardano.Ledger.Alonzo.Scripts``

    Attributes:
        version: Which Plutus language version this cost model is for.
        params: Flat parameter vector (integers).
    """

    version: PlutusVersion
    params: tuple[int, ...]

    def __post_init__(self) -> None:
        expected = COST_MODEL_PARAM_COUNTS.get(self.version)
        if expected is not None and len(self.params) != expected:
            raise ValueError(
                f"CostModel for {self.version.name} requires {expected} "
                f"parameters, got {len(self.params)}"
            )

    @classmethod
    def from_list(cls, version: PlutusVersion, params: list[int]) -> CostModel:
        """Construct a CostModel from a list of parameter values.

        Haskell ref: ``mkCostModel`` in ``Cardano.Ledger.Alonzo.Scripts``
        """
        return cls(version=version, params=tuple(params))

    def serialize_for_integrity_hash(self) -> bytes:
        """Serialize the cost model for script integrity hash computation.

        The script integrity hash (scriptDataHash in Alonzo) includes the
        cost models. For each language present, the cost model parameters
        are CBOR-encoded as a definite-length list of integers, keyed by
        the language version (0=PlutusV1, 1=PlutusV2, 2=PlutusV3).

        Spec ref: Alonzo ledger formal spec, ``hashScriptIntegrity``.
        Haskell ref: ``encodeCostModel`` in ``Cardano.Ledger.Alonzo.Scripts``

        Returns:
            CBOR-encoded parameter list (without the language key).
        """
        import cbor2

        # The cost model is serialized as a CBOR array of integers.
        # This is the "flat" encoding used in hashScriptIntegrity.
        return cbor2.dumps(list(self.params))

    @property
    def language_id(self) -> int:
        """Language identifier for CBOR map key in scriptDataHash.

        PlutusV1 = 0, PlutusV2 = 1, PlutusV3 = 2.
        Haskell ref: ``Language`` Enum instance.
        """
        return self.version.value - 1


# ---------------------------------------------------------------------------
# Cost model maps (for use in protocol parameters)
# ---------------------------------------------------------------------------


CostModels = dict[PlutusVersion, CostModel]
"""Protocol parameter cost models: one CostModel per Plutus version."""


def serialize_cost_models_for_integrity(cost_models: CostModels) -> bytes:
    """Serialize a set of cost models for script integrity hash.

    The cost models map is CBOR-encoded as::

        { language_id => [param1, param2, ...], ... }

    sorted by language_id. This is the encoding used in the
    ``scriptDataHash`` field of the transaction body.

    Spec ref: Alonzo ledger formal spec, ``hashScriptIntegrity``.
    Haskell ref: ``getLanguageView`` / ``encodeCostModel``

    Args:
        cost_models: Mapping from PlutusVersion to CostModel.

    Returns:
        CBOR-encoded cost models map.
    """
    import cbor2

    # Build CBOR map: { language_id (int) => [params] }
    # Must be sorted by key for deterministic encoding.
    cbor_map: dict[int, list[int]] = {}
    for version in sorted(cost_models.keys(), key=lambda v: v.value):
        cm = cost_models[version]
        cbor_map[cm.language_id] = list(cm.params)

    return cbor2.dumps(cbor_map)


def hash_script_integrity(
    redeemers_cbor: bytes,
    cost_models: CostModels,
    datums_cbor: bytes,
) -> bytes:
    """Compute the script integrity hash (scriptDataHash).

    scriptDataHash = blake2b-256(redeemers || cost_models || datums)

    where:
        - redeemers is the CBOR encoding of the redeemers
        - cost_models is the CBOR encoding of the cost model map
        - datums is the CBOR encoding of the datums

    Spec ref: Alonzo ledger formal spec, Section 4.5, ``hashScriptIntegrity``.
    Haskell ref: ``hashScriptIntegrity`` in
        ``Cardano.Ledger.Alonzo.TxBody``

    Args:
        redeemers_cbor: CBOR-encoded redeemers.
        cost_models: Cost models for all languages used in the transaction.
        datums_cbor: CBOR-encoded datums (plutus data witnesses).

    Returns:
        32-byte Blake2b-256 hash.
    """
    cm_cbor = serialize_cost_models_for_integrity(cost_models)
    preimage = redeemers_cbor + cm_cbor + datums_cbor
    return hashlib.blake2b(preimage, digest_size=32).digest()
