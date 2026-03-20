"""Tests for Plutus cost model types and serialization.

Tests cover:
    - ExUnits construction and validation
    - CostModel construction with correct parameter counts
    - CostModel parameter count enforcement per Plutus version
    - Cost model serialization for script integrity hash
    - Script integrity hash computation
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.plutus.cost_model import (
    COST_MODEL_PARAM_COUNTS,
    CostModel,
    CostModels,
    ExUnits,
    PlutusVersion,
    hash_script_integrity,
    serialize_cost_models_for_integrity,
)


# ---------------------------------------------------------------------------
# ExUnits
# ---------------------------------------------------------------------------


class TestExUnits:
    """Tests for ExUnits budget type."""

    def test_construction(self) -> None:
        ex = ExUnits(mem=14_000_000, steps=10_000_000_000)
        assert ex.mem == 14_000_000
        assert ex.steps == 10_000_000_000

    def test_negative_mem_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=-1, steps=100)

    def test_negative_steps_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=100, steps=-1)

    def test_zero_budget(self) -> None:
        ex = ExUnits(mem=0, steps=0)
        assert ex.mem == 0
        assert ex.steps == 0

    def test_fits_within_both_fit(self) -> None:
        consumed = ExUnits(mem=100, steps=200)
        budget = ExUnits(mem=200, steps=300)
        assert consumed.fits_within(budget)

    def test_fits_within_exact(self) -> None:
        ex = ExUnits(mem=100, steps=200)
        assert ex.fits_within(ex)

    def test_fits_within_mem_exceeds(self) -> None:
        consumed = ExUnits(mem=300, steps=200)
        budget = ExUnits(mem=200, steps=300)
        assert not consumed.fits_within(budget)

    def test_fits_within_steps_exceeds(self) -> None:
        consumed = ExUnits(mem=100, steps=400)
        budget = ExUnits(mem=200, steps=300)
        assert not consumed.fits_within(budget)

    def test_immutable(self) -> None:
        ex = ExUnits(mem=100, steps=200)
        with pytest.raises(AttributeError):
            ex.mem = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PlutusVersion
# ---------------------------------------------------------------------------


class TestPlutusVersion:
    """Tests for PlutusVersion enum."""

    def test_values(self) -> None:
        assert PlutusVersion.V1.value == 1
        assert PlutusVersion.V2.value == 2
        assert PlutusVersion.V3.value == 3

    def test_all_versions_have_param_counts(self) -> None:
        for version in PlutusVersion:
            assert version in COST_MODEL_PARAM_COUNTS


# ---------------------------------------------------------------------------
# CostModel
# ---------------------------------------------------------------------------


class TestCostModel:
    """Tests for CostModel construction and validation."""

    def _make_params(self, version: PlutusVersion) -> tuple[int, ...]:
        """Create a dummy parameter vector of the correct length."""
        count = COST_MODEL_PARAM_COUNTS[version]
        return tuple(range(count))

    def test_v1_correct_count(self) -> None:
        params = self._make_params(PlutusVersion.V1)
        cm = CostModel(version=PlutusVersion.V1, params=params)
        assert len(cm.params) == 166

    def test_v2_correct_count(self) -> None:
        params = self._make_params(PlutusVersion.V2)
        cm = CostModel(version=PlutusVersion.V2, params=params)
        assert len(cm.params) == 175

    def test_v3_correct_count(self) -> None:
        params = self._make_params(PlutusVersion.V3)
        cm = CostModel(version=PlutusVersion.V3, params=params)
        assert len(cm.params) == 233

    def test_wrong_count_rejected(self) -> None:
        with pytest.raises(ValueError, match="requires 166 parameters"):
            CostModel(version=PlutusVersion.V1, params=(1, 2, 3))

    def test_from_list(self) -> None:
        params_list = list(range(175))
        cm = CostModel.from_list(PlutusVersion.V2, params_list)
        assert cm.params == tuple(params_list)

    def test_language_id(self) -> None:
        params_v1 = self._make_params(PlutusVersion.V1)
        cm_v1 = CostModel(version=PlutusVersion.V1, params=params_v1)
        assert cm_v1.language_id == 0

        params_v2 = self._make_params(PlutusVersion.V2)
        cm_v2 = CostModel(version=PlutusVersion.V2, params=params_v2)
        assert cm_v2.language_id == 1

        params_v3 = self._make_params(PlutusVersion.V3)
        cm_v3 = CostModel(version=PlutusVersion.V3, params=params_v3)
        assert cm_v3.language_id == 2

    def test_immutable(self) -> None:
        params = self._make_params(PlutusVersion.V1)
        cm = CostModel(version=PlutusVersion.V1, params=params)
        with pytest.raises(AttributeError):
            cm.version = PlutusVersion.V2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestCostModelSerialization:
    """Tests for cost model CBOR serialization."""

    def _make_cost_model(self, version: PlutusVersion) -> CostModel:
        count = COST_MODEL_PARAM_COUNTS[version]
        return CostModel(version=version, params=tuple(range(count)))

    def test_serialize_for_integrity_hash_returns_bytes(self) -> None:
        cm = self._make_cost_model(PlutusVersion.V1)
        result = cm.serialize_for_integrity_hash()
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_serialize_for_integrity_hash_deterministic(self) -> None:
        cm = self._make_cost_model(PlutusVersion.V2)
        a = cm.serialize_for_integrity_hash()
        b = cm.serialize_for_integrity_hash()
        assert a == b

    def test_serialize_cost_models_map(self) -> None:
        cm_v1 = self._make_cost_model(PlutusVersion.V1)
        cm_v2 = self._make_cost_model(PlutusVersion.V2)
        cost_models: CostModels = {PlutusVersion.V1: cm_v1, PlutusVersion.V2: cm_v2}
        result = serialize_cost_models_for_integrity(cost_models)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_serialize_cost_models_sorted_by_language_id(self) -> None:
        """Cost models must be sorted by language ID for deterministic hashing."""
        cm_v1 = self._make_cost_model(PlutusVersion.V1)
        cm_v3 = self._make_cost_model(PlutusVersion.V3)

        # Order of insertion shouldn't matter
        a = serialize_cost_models_for_integrity({PlutusVersion.V1: cm_v1, PlutusVersion.V3: cm_v3})
        b = serialize_cost_models_for_integrity({PlutusVersion.V3: cm_v3, PlutusVersion.V1: cm_v1})
        assert a == b


# ---------------------------------------------------------------------------
# Script integrity hash
# ---------------------------------------------------------------------------


class TestScriptIntegrityHash:
    """Tests for script integrity hash computation."""

    def test_hash_returns_32_bytes(self) -> None:
        cm_v2 = CostModel(
            version=PlutusVersion.V2,
            params=tuple(range(175)),
        )
        cost_models: CostModels = {PlutusVersion.V2: cm_v2}

        result = hash_script_integrity(
            redeemers_cbor=b"\x80",  # empty CBOR array
            cost_models=cost_models,
            datums_cbor=b"\x80",  # empty CBOR array
        )
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_hash_deterministic(self) -> None:
        cm_v1 = CostModel(
            version=PlutusVersion.V1,
            params=tuple(range(166)),
        )
        cost_models: CostModels = {PlutusVersion.V1: cm_v1}

        a = hash_script_integrity(b"\x80", cost_models, b"\x80")
        b = hash_script_integrity(b"\x80", cost_models, b"\x80")
        assert a == b

    def test_different_redeemers_different_hash(self) -> None:
        cm_v1 = CostModel(
            version=PlutusVersion.V1,
            params=tuple(range(166)),
        )
        cost_models: CostModels = {PlutusVersion.V1: cm_v1}

        a = hash_script_integrity(b"\x80", cost_models, b"\x80")
        b = hash_script_integrity(b"\x81\x01", cost_models, b"\x80")
        assert a != b
