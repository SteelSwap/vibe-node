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
