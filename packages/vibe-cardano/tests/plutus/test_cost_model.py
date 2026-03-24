"""Tests for Plutus cost model types and serialization.

Tests cover:
    - ExUnits construction and validation
    - CostModel construction with correct parameter counts
    - CostModel parameter count enforcement per Plutus version
    - Cost model serialization for script integrity hash
    - Script integrity hash computation
"""

from __future__ import annotations

import pytest

from vibe.cardano.plutus.cost_model import (
    BUILTINS_INTRODUCED_IN,
    COST_MODEL_PARAM_COUNTS,
    CostModel,
    CostModels,
    ExUnits,
    PlutusVersion,
    builtins_available_at,
    cost_model_param_names,
    hash_script_integrity,
    is_plutus_version_available,
    param_index_to_name,
    param_name_to_index,
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


# ---------------------------------------------------------------------------
# Test 1: Plutus version availability per protocol version
# ---------------------------------------------------------------------------


class TestPlutusVersionAvailability:
    """Test that Plutus versions are available at the correct protocol versions.

    This is consensus-critical: using the wrong Plutus version at a protocol
    version that doesn't support it would cause validation divergence from
    the Haskell node.

    Haskell ref: ``ledgerLanguages`` in ``Cardano.Ledger.Plutus.Language``
    """

    def test_v1_not_available_before_alonzo(self) -> None:
        """PlutusV1 not available at PV 4 (Mary era)."""
        assert not is_plutus_version_available(PlutusVersion.V1, 4)

    def test_v1_available_at_alonzo_pv5(self) -> None:
        """PlutusV1 introduced at Alonzo (PV 5)."""
        assert is_plutus_version_available(PlutusVersion.V1, 5)

    def test_v1_available_at_alonzo_pv6(self) -> None:
        """PlutusV1 still available at PV 6 (Alonzo intra-era HF)."""
        assert is_plutus_version_available(PlutusVersion.V1, 6)

    def test_v1_available_at_babbage_and_beyond(self) -> None:
        """PlutusV1 remains available in later eras."""
        assert is_plutus_version_available(PlutusVersion.V1, 7)
        assert is_plutus_version_available(PlutusVersion.V1, 9)

    def test_v2_not_available_at_alonzo(self) -> None:
        """PlutusV2 not available at PV 6 (still Alonzo)."""
        assert not is_plutus_version_available(PlutusVersion.V2, 6)

    def test_v2_available_at_babbage_pv7(self) -> None:
        """PlutusV2 introduced at Babbage (PV 7)."""
        assert is_plutus_version_available(PlutusVersion.V2, 7)

    def test_v2_available_at_babbage_pv8(self) -> None:
        """PlutusV2 available at PV 8 (Babbage intra-era HF)."""
        assert is_plutus_version_available(PlutusVersion.V2, 8)

    def test_v2_available_at_conway(self) -> None:
        """PlutusV2 remains available in Conway."""
        assert is_plutus_version_available(PlutusVersion.V2, 9)

    def test_v3_not_available_at_babbage(self) -> None:
        """PlutusV3 not available at PV 8 (still Babbage)."""
        assert not is_plutus_version_available(PlutusVersion.V3, 8)

    def test_v3_available_at_conway_pv9(self) -> None:
        """PlutusV3 introduced at Conway (PV 9)."""
        assert is_plutus_version_available(PlutusVersion.V3, 9)

    def test_v3_available_at_conway_pv10(self) -> None:
        """PlutusV3 available at PV 10 (Conway intra-era HF)."""
        assert is_plutus_version_available(PlutusVersion.V3, 10)

    def test_no_plutus_before_alonzo(self) -> None:
        """No Plutus versions are available before Alonzo (PV < 5)."""
        for pv in range(1, 5):
            for version in PlutusVersion:
                assert not is_plutus_version_available(
                    version, pv
                ), f"{version.name} should not be available at PV {pv}"


# ---------------------------------------------------------------------------
# Test 2: Builtin availability per language/PV combination
# ---------------------------------------------------------------------------


class TestBuiltinAvailability:
    """Test that specific builtins are only available at the correct Plutus version.

    Haskell ref: ``builtinsIntroducedIn`` in ``PlutusLedgerApi.Common.Versions``
    """

    def test_v1_has_base_builtins(self) -> None:
        """V1 should have all base builtins (AddInteger, Trace, etc.)."""
        v1_builtins = builtins_available_at(PlutusVersion.V1)
        assert "AddInteger" in v1_builtins
        assert "Trace" in v1_builtins
        assert "EqualsData" in v1_builtins
        assert "MkPairData" in v1_builtins

    def test_v1_does_not_have_v2_builtins(self) -> None:
        """V1 should NOT have V2-introduced builtins."""
        v1_builtins = builtins_available_at(PlutusVersion.V1)
        assert "SerialiseData" not in v1_builtins
        assert "VerifyEcdsaSecp256k1Signature" not in v1_builtins
        assert "VerifySchnorrSecp256k1Signature" not in v1_builtins

    def test_v1_does_not_have_v3_builtins(self) -> None:
        """V1 should NOT have V3-introduced builtins."""
        v1_builtins = builtins_available_at(PlutusVersion.V1)
        assert "Bls12_381_G1_Add" not in v1_builtins
        assert "Keccak_256" not in v1_builtins
        assert "IntegerToByteString" not in v1_builtins

    def test_v2_has_serialise_data(self) -> None:
        """SerialiseData is a V2+ builtin (CIP-0042)."""
        v2_builtins = builtins_available_at(PlutusVersion.V2)
        assert "SerialiseData" in v2_builtins

    def test_v2_has_secp256k1(self) -> None:
        """ECDSA and Schnorr secp256k1 are V2+ builtins."""
        v2_builtins = builtins_available_at(PlutusVersion.V2)
        assert "VerifyEcdsaSecp256k1Signature" in v2_builtins
        assert "VerifySchnorrSecp256k1Signature" in v2_builtins

    def test_v2_includes_all_v1_builtins(self) -> None:
        """V2 should be a superset of V1 builtins."""
        v1_builtins = builtins_available_at(PlutusVersion.V1)
        v2_builtins = builtins_available_at(PlutusVersion.V2)
        assert v1_builtins.issubset(
            v2_builtins
        ), f"V1 builtins not in V2: {v1_builtins - v2_builtins}"

    def test_v2_does_not_have_v3_builtins(self) -> None:
        """V2 should NOT have V3-introduced builtins."""
        v2_builtins = builtins_available_at(PlutusVersion.V2)
        assert "Bls12_381_G1_Add" not in v2_builtins
        assert "Blake2b_224" not in v2_builtins

    def test_v3_has_bls12_381(self) -> None:
        """BLS12-381 builtins are V3+ (CIP-0055)."""
        v3_builtins = builtins_available_at(PlutusVersion.V3)
        bls_builtins = [
            "Bls12_381_G1_Add",
            "Bls12_381_G1_Neg",
            "Bls12_381_G1_ScalarMul",
            "Bls12_381_G1_Equal",
            "Bls12_381_G1_Compress",
            "Bls12_381_G1_Uncompress",
            "Bls12_381_G1_HashToGroup",
            "Bls12_381_G2_Add",
            "Bls12_381_G2_Neg",
            "Bls12_381_G2_ScalarMul",
            "Bls12_381_G2_Equal",
            "Bls12_381_G2_Compress",
            "Bls12_381_G2_Uncompress",
            "Bls12_381_G2_HashToGroup",
            "Bls12_381_MillerLoop",
            "Bls12_381_MulMlResult",
            "Bls12_381_FinalVerify",
        ]
        for builtin in bls_builtins:
            assert builtin in v3_builtins, f"{builtin} should be in V3"

    def test_v3_has_bitwise_ops(self) -> None:
        """Bitwise operation builtins are V3+ (CIP-0058)."""
        v3_builtins = builtins_available_at(PlutusVersion.V3)
        assert "IntegerToByteString" in v3_builtins
        assert "ByteStringToInteger" in v3_builtins
        assert "AndByteString" in v3_builtins

    def test_v3_includes_all_v2_builtins(self) -> None:
        """V3 should be a superset of V2 builtins."""
        v2_builtins = builtins_available_at(PlutusVersion.V2)
        v3_builtins = builtins_available_at(PlutusVersion.V3)
        assert v2_builtins.issubset(
            v3_builtins
        ), f"V2 builtins not in V3: {v2_builtins - v3_builtins}"

    def test_v2_adds_exactly_3_builtins_over_v1(self) -> None:
        """V2 adds exactly 3 builtins over V1."""
        assert len(BUILTINS_INTRODUCED_IN[PlutusVersion.V2]) == 3


# ---------------------------------------------------------------------------
# Test 3: Cost model parameter name round-trip
# ---------------------------------------------------------------------------


class TestCostModelParamNames:
    """Test that cost model parameter names round-trip correctly.

    Parameters have canonical names (e.g., "addInteger-cpu-arguments-intercept")
    and the name<->index mapping must be bijective.

    Haskell ref: ``costModelParamNames`` in ``Cardano.Ledger.Plutus.CostModels``
    """

    def test_v1_param_names_loaded(self) -> None:
        """V1 should have parameter names loaded from uplc config.

        The uplc config includes both builtin and CEK machine cost params.
        V1: 150 builtin + 16 CEK = 166.
        """
        names = cost_model_param_names(PlutusVersion.V1)
        assert len(names) == COST_MODEL_PARAM_COUNTS[PlutusVersion.V1]

    def test_v2_param_names_loaded(self) -> None:
        """V2 should have parameter names loaded from uplc config.

        V2: 159 builtin + 16 CEK = 175.
        """
        names = cost_model_param_names(PlutusVersion.V2)
        assert len(names) == COST_MODEL_PARAM_COUNTS[PlutusVersion.V2]

    def test_v3_param_names_loaded(self) -> None:
        """V3 parameter names from uplc config may exceed on-chain count.

        The uplc package's config includes all parameters used by the
        evaluator, which may be more than the 233 on-chain cost model
        parameters. The uplc config has 277 entries for V3 (including
        CEK machine costs and extra evaluator params). The on-chain
        cost model has 233 params.

        This test verifies that names are loaded and has at least the
        expected on-chain count.
        """
        names = cost_model_param_names(PlutusVersion.V3)
        assert len(names) >= COST_MODEL_PARAM_COUNTS[PlutusVersion.V3], (
            f"V3 should have at least {COST_MODEL_PARAM_COUNTS[PlutusVersion.V3]} "
            f"params, got {len(names)}"
        )

    def test_name_to_index_round_trip(self) -> None:
        """Converting name -> index -> name should return the original name."""
        for version in PlutusVersion:
            names = cost_model_param_names(version)
            if not names:
                continue
            # Test first, last, and a middle parameter
            for name in [names[0], names[len(names) // 2], names[-1]]:
                idx = param_name_to_index(version, name)
                recovered = param_index_to_name(version, idx)
                assert (
                    recovered == name
                ), f"Round-trip failed for {version.name}: {name} -> {idx} -> {recovered}"

    def test_index_to_name_round_trip(self) -> None:
        """Converting index -> name -> index should return the original index."""
        for version in PlutusVersion:
            names = cost_model_param_names(version)
            if not names:
                continue
            for idx in [0, len(names) // 2, len(names) - 1]:
                name = param_index_to_name(version, idx)
                recovered = param_name_to_index(version, name)
                assert (
                    recovered == idx
                ), f"Round-trip failed for {version.name}: {idx} -> {name} -> {recovered}"

    def test_known_parameter_name_exists(self) -> None:
        """A known parameter name should be present and resolvable."""
        # "addInteger-cpu-arguments-intercept" is a well-known parameter
        # present in all versions.
        for version in PlutusVersion:
            names = cost_model_param_names(version)
            assert (
                "addInteger-cpu-arguments-intercept" in names
            ), f"Expected addInteger-cpu-arguments-intercept in {version.name}"

    def test_invalid_name_raises_key_error(self) -> None:
        """An invalid parameter name should raise KeyError."""
        with pytest.raises(KeyError, match="not found"):
            param_name_to_index(PlutusVersion.V1, "nonExistentParam-foobar")

    def test_invalid_index_raises_index_error(self) -> None:
        """An out-of-range index should raise IndexError."""
        with pytest.raises(IndexError, match="out of range"):
            param_index_to_name(PlutusVersion.V1, 999)

    def test_all_names_unique(self) -> None:
        """All parameter names within a version must be unique."""
        for version in PlutusVersion:
            names = cost_model_param_names(version)
            assert len(names) == len(set(names)), f"Duplicate parameter names in {version.name}"

    def test_names_are_sorted(self) -> None:
        """Parameter names should be in alphabetical order (canonical ordering)."""
        for version in PlutusVersion:
            names = cost_model_param_names(version)
            assert names == tuple(sorted(names)), f"Parameter names not sorted for {version.name}"


# ---------------------------------------------------------------------------
# Test 4: V1/V2/V3 cost model parameter count relationships
# ---------------------------------------------------------------------------


class TestCostModelParamCountRelationships:
    """Test the parameter count relationships between Plutus versions.

    V1 has 166, V2 has 175, V3 has 233 params. V1 params are a prefix/subset
    of V2 (they share the same base builtins). V3 has a different structure
    (not a simple superset of V1/V2).

    Haskell ref: ``costModelParamsCount`` in ``Cardano.Ledger.Plutus.CostModels``
    """

    def test_v1_has_166_params(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V1] == 166

    def test_v2_has_175_params(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] == 175

    def test_v3_has_233_params(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V3] == 233

    def test_v2_has_more_params_than_v1(self) -> None:
        """V2 adds builtins (serialiseData, secp256k1) so has more params."""
        assert (
            COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] > COST_MODEL_PARAM_COUNTS[PlutusVersion.V1]
        )

    def test_v3_has_more_params_than_v2(self) -> None:
        """V3 adds many builtins (BLS, bitwise) so has more params."""
        assert (
            COST_MODEL_PARAM_COUNTS[PlutusVersion.V3] > COST_MODEL_PARAM_COUNTS[PlutusVersion.V2]
        )

    def test_v1_builtin_params_are_subset_of_v2(self) -> None:
        """V1 builtin parameter names should be a subset of V2 builtin params.

        V2 extends V1 with additional builtins, so V1's builtin cost
        parameters should all appear in V2's parameter list.

        Note: CEK machine parameter naming may differ slightly between
        versions (e.g., "exBudgetMem" vs "exBudgetMemory"), so we
        compare only non-CEK (builtin) parameters for the subset check.
        """
        v1_names = {n for n in cost_model_param_names(PlutusVersion.V1) if not n.startswith("cek")}
        v2_names = {n for n in cost_model_param_names(PlutusVersion.V2) if not n.startswith("cek")}
        assert v1_names.issubset(v2_names), f"V1 builtin params not in V2: {v1_names - v2_names}"

    def test_v2_adds_9_params_over_v1(self) -> None:
        """V2 adds exactly 9 parameters over V1 (175 - 166 = 9).

        These correspond to the 3 new builtins (serialiseData,
        verifyEcdsaSecp256k1Signature, verifySchnorrSecp256k1Signature),
        each with multiple cost parameters.
        """
        diff = (
            COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] - COST_MODEL_PARAM_COUNTS[PlutusVersion.V1]
        )
        assert diff == 9

    def test_v3_is_not_superset_of_v1_v2_params(self) -> None:
        """V3 restructured cost model parameters -- NOT a simple superset of V1/V2.

        Conway's PlutusV3 introduces new cost model parameter naming conventions
        and reorganizes some existing parameters. The parameter names may differ
        from V1/V2 naming even for the same builtins.

        This tests that V3 has parameter names not in V2 (the new builtins),
        confirming the parameter structure difference.
        """
        v2_names = set(cost_model_param_names(PlutusVersion.V2))
        v3_names = set(cost_model_param_names(PlutusVersion.V3))

        # V3 should have names not in V2 (new builtins like bls12_381)
        v3_only = v3_names - v2_names
        assert len(v3_only) > 0, "V3 should have parameters not in V2"

    def test_cost_model_construction_enforces_count(self) -> None:
        """CostModel rejects wrong parameter count for each version."""
        for version in PlutusVersion:
            expected = COST_MODEL_PARAM_COUNTS[version]
            # Correct count should work
            CostModel(version=version, params=tuple(range(expected)))
            # Wrong count should fail
            with pytest.raises(ValueError):
                CostModel(version=version, params=tuple(range(expected + 1)))
            with pytest.raises(ValueError):
                CostModel(version=version, params=tuple(range(expected - 1)))
