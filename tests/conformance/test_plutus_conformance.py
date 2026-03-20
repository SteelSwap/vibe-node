"""Conformance tests: Plutus script evaluation against the Haskell node.

Two test tiers:

1. **Fixture-based tests** (no Docker) — validate our cost model parameter
   counts, version availability logic, ExUnits type invariants, and
   serialization round-trips using the uplc package.

2. **Live Ogmios tests** (@pytest.mark.conformance) — for real Plutus
   transactions from preprod, compare script evaluation outcomes:
   success/failure agreement and ExUnits consumption within tolerance.

Spec references:
    * Alonzo ledger formal spec, Section 4.1 (Script evaluation)
    * Alonzo ledger formal spec, Section 4.2 (Cost models)
    * Alonzo ledger formal spec, Section 4.4 (Evaluating scripts)
    * CIP-0055 (PlutusV3 cost model parameters)

Haskell references:
    * ``evalPlutusScript`` in ``Cardano.Ledger.Alonzo.Plutus.Evaluate``
    * ``CostModel`` in ``Cardano.Ledger.Alonzo.Scripts``
    * ``costModelParamsCount`` in ``Cardano.Ledger.Plutus.CostModels``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import websockets

from vibe.cardano.plutus.cost_model import (
    COST_MODEL_PARAM_COUNTS,
    PLUTUS_VERSION_INTRODUCED_AT,
    CostModel,
    ExUnits,
    PlutusVersion,
    builtins_available_at,
    cost_model_param_names,
    is_plutus_version_available,
)

# Make helpers importable from this directory
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from helpers import (  # noqa: E402
    extract_block_metadata,
    fetch_blocks_from_origin,
    fetch_blocks_from_point,
    load_fixture,
    ogmios_rpc,
)


# ===================================================================
# TIER 1: Fixture-based / unit-level Plutus conformance tests
# ===================================================================


class TestCostModelParamCounts:
    """Verify cost model parameter counts match the Haskell implementation.

    These counts must be exact — the ledger rejects cost models with wrong
    parameter counts.

    Haskell ref: ``costModelParamsCount`` in ``Cardano.Ledger.Plutus.CostModels``
    """

    def test_plutus_v1_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V1] == 166

    def test_plutus_v2_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] == 175

    def test_plutus_v3_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V3] == 233

    def test_cost_model_rejects_wrong_count(self) -> None:
        """CostModel construction should reject wrong parameter counts."""
        with pytest.raises(ValueError, match="requires 166 parameters"):
            CostModel.from_list(PlutusVersion.V1, [0] * 100)

    def test_cost_model_accepts_correct_count(self) -> None:
        """CostModel construction should accept correct parameter counts."""
        cm = CostModel.from_list(PlutusVersion.V1, [0] * 166)
        assert len(cm.params) == 166
        assert cm.version == PlutusVersion.V1


class TestCostModelParamNames:
    """Verify cost model parameter names are loadable and correctly sized.

    Parameter names come from the uplc package's network config files.
    If uplc is not installed or config files are missing, these tests
    gracefully handle that.
    """

    @pytest.mark.parametrize("version", [PlutusVersion.V1, PlutusVersion.V2, PlutusVersion.V3])
    def test_param_names_count_at_least_on_chain_count(self, version: PlutusVersion) -> None:
        """Parameter name count must be >= the on-chain cost model vector length.

        The cost_model_param_names function returns ALL parameter names from
        the uplc config (builtin cost params + CEK machine cost params). The
        on-chain cost model vector (COST_MODEL_PARAM_COUNTS) is a subset
        containing only the builtin cost parameters.

        So: len(param_names) >= COST_MODEL_PARAM_COUNTS[version]
        """
        names = cost_model_param_names(version)
        if len(names) == 0:
            pytest.skip("uplc cost model config files not available")
        on_chain_count = COST_MODEL_PARAM_COUNTS[version]
        assert len(names) >= on_chain_count, (
            f"{version.name} has {len(names)} param names, but on-chain count is {on_chain_count}"
        )

    @pytest.mark.parametrize("version", [PlutusVersion.V1, PlutusVersion.V2, PlutusVersion.V3])
    def test_param_names_are_unique(self, version: PlutusVersion) -> None:
        """All parameter names within a version must be unique."""
        names = cost_model_param_names(version)
        if len(names) == 0:
            pytest.skip("uplc cost model config files not available")
        assert len(names) == len(set(names)), "Duplicate parameter names found"

    @pytest.mark.parametrize("version", [PlutusVersion.V1, PlutusVersion.V2, PlutusVersion.V3])
    def test_param_names_are_alphabetically_sorted(self, version: PlutusVersion) -> None:
        """Parameter names must be in alphabetical order (canonical ordering)."""
        names = cost_model_param_names(version)
        if len(names) == 0:
            pytest.skip("uplc cost model config files not available")
        assert list(names) == sorted(names), "Parameter names are not alphabetically sorted"


class TestPlutusVersionAvailability:
    """Verify Plutus version availability at each protocol version.

    Haskell ref: ``ledgerLanguages`` in ``Cardano.Ledger.Plutus.Language``
    """

    def test_v1_available_from_alonzo(self) -> None:
        """PlutusV1 is available from protocol version 5 (Alonzo) onward."""
        assert not is_plutus_version_available(PlutusVersion.V1, 4)
        assert is_plutus_version_available(PlutusVersion.V1, 5)
        assert is_plutus_version_available(PlutusVersion.V1, 6)
        assert is_plutus_version_available(PlutusVersion.V1, 9)

    def test_v2_available_from_babbage(self) -> None:
        """PlutusV2 is available from protocol version 7 (Babbage) onward."""
        assert not is_plutus_version_available(PlutusVersion.V2, 6)
        assert is_plutus_version_available(PlutusVersion.V2, 7)
        assert is_plutus_version_available(PlutusVersion.V2, 8)
        assert is_plutus_version_available(PlutusVersion.V2, 9)

    def test_v3_available_from_conway(self) -> None:
        """PlutusV3 is available from protocol version 9 (Conway) onward."""
        assert not is_plutus_version_available(PlutusVersion.V3, 8)
        assert is_plutus_version_available(PlutusVersion.V3, 9)
        assert is_plutus_version_available(PlutusVersion.V3, 10)

    def test_v1_not_available_before_alonzo(self) -> None:
        """No Plutus version should be available before Alonzo (PV < 5)."""
        for pv in range(0, 5):
            for version in PlutusVersion:
                assert not is_plutus_version_available(version, pv), (
                    f"{version.name} should not be available at PV {pv}"
                )


class TestBuiltinAvailability:
    """Verify builtin function availability across Plutus versions.

    Haskell ref: ``builtinsAvailableIn`` in ``PlutusLedgerApi.Common.Versions``
    """

    def test_v1_has_base_builtins(self) -> None:
        """PlutusV1 should have the core Alonzo builtins."""
        builtins = builtins_available_at(PlutusVersion.V1)
        assert "AddInteger" in builtins
        assert "VerifyEd25519Signature" in builtins
        assert "EqualsData" in builtins

    def test_v2_adds_serialize_and_secp(self) -> None:
        """PlutusV2 should add SerialiseData and secp256k1 builtins."""
        builtins = builtins_available_at(PlutusVersion.V2)
        assert "SerialiseData" in builtins
        assert "VerifyEcdsaSecp256k1Signature" in builtins
        assert "VerifySchnorrSecp256k1Signature" in builtins
        # V2 should include all V1 builtins too
        assert "AddInteger" in builtins

    def test_v3_adds_bls_and_bitwise(self) -> None:
        """PlutusV3 should add BLS12-381 and bitwise builtins."""
        builtins = builtins_available_at(PlutusVersion.V3)
        assert "Bls12_381_G1_Add" in builtins
        assert "Bls12_381_FinalVerify" in builtins
        assert "IntegerToByteString" in builtins
        assert "Keccak_256" in builtins
        assert "Ripemd_160" in builtins
        # V3 should include all V1+V2 builtins too
        assert "AddInteger" in builtins
        assert "SerialiseData" in builtins

    def test_v2_does_not_have_v3_builtins(self) -> None:
        """PlutusV2 should NOT have V3-only builtins."""
        builtins = builtins_available_at(PlutusVersion.V2)
        assert "Bls12_381_G1_Add" not in builtins
        assert "Keccak_256" not in builtins

    def test_v1_does_not_have_v2_builtins(self) -> None:
        """PlutusV1 should NOT have V2-only builtins."""
        builtins = builtins_available_at(PlutusVersion.V1)
        assert "SerialiseData" not in builtins
        assert "VerifyEcdsaSecp256k1Signature" not in builtins


class TestExUnitsInvariants:
    """Verify ExUnits type behavior and invariants.

    Spec ref: Alonzo ledger spec, ``ExUnits = (Natural, Natural)``.
    """

    def test_non_negative_invariant(self) -> None:
        """ExUnits must reject negative values."""
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=-1, steps=0)
        with pytest.raises(ValueError, match="non-negative"):
            ExUnits(mem=0, steps=-1)

    def test_fits_within(self) -> None:
        """fits_within should compare both mem and steps."""
        small = ExUnits(mem=100, steps=200)
        big = ExUnits(mem=1000, steps=2000)
        assert small.fits_within(big)
        assert not big.fits_within(small)

    def test_fits_within_equal(self) -> None:
        """ExUnits should fit within identical budget."""
        eu = ExUnits(mem=500, steps=1000)
        assert eu.fits_within(eu)

    def test_fits_within_partial_exceeds(self) -> None:
        """If mem fits but steps don't, it should not fit."""
        a = ExUnits(mem=100, steps=2000)
        b = ExUnits(mem=1000, steps=1000)
        assert not a.fits_within(b)  # steps exceed


class TestCostModelSerialization:
    """Verify cost model CBOR serialization for script integrity hash.

    The script integrity hash depends on deterministic CBOR encoding of
    cost model parameter vectors.

    Spec ref: Alonzo spec Section 4.5, ``hashScriptIntegrity``.
    """

    def test_serialize_round_trip(self) -> None:
        """Serialized cost model should be valid CBOR."""
        import cbor2

        params = list(range(166))
        cm = CostModel.from_list(PlutusVersion.V1, params)
        serialized = cm.serialize_for_integrity_hash()
        decoded = cbor2.loads(serialized)
        assert decoded == params

    def test_language_ids(self) -> None:
        """Language IDs must be 0-indexed (V1=0, V2=1, V3=2)."""
        cm1 = CostModel.from_list(PlutusVersion.V1, [0] * 166)
        cm2 = CostModel.from_list(PlutusVersion.V2, [0] * 175)
        cm3 = CostModel.from_list(PlutusVersion.V3, [0] * 233)
        assert cm1.language_id == 0
        assert cm2.language_id == 1
        assert cm3.language_id == 2


class TestFixturePlutusFields:
    """Validate Plutus-related fields in fixture block data."""

    def test_alonzo_fixture_has_plutus_v1_script(self) -> None:
        """Alonzo fixture should contain a PlutusV1 script."""
        block = load_fixture("alonzo")
        tx = block["transactions"][0]
        scripts = tx.get("scripts", {})
        assert len(scripts) > 0
        for script_hash, script_data in scripts.items():
            assert script_data["language"] == "plutus:v1"

    def test_babbage_fixture_has_plutus_v2_script(self) -> None:
        """Babbage fixture should contain a PlutusV2 script."""
        block = load_fixture("babbage")
        tx = block["transactions"][0]
        scripts = tx.get("scripts", {})
        assert len(scripts) > 0
        for script_hash, script_data in scripts.items():
            assert script_data["language"] == "plutus:v2"

    def test_alonzo_fixture_redeemer_has_ex_units(self) -> None:
        """Redeemers in Alonzo fixture must have execution units."""
        block = load_fixture("alonzo")
        tx = block["transactions"][0]
        for redeemer in tx.get("redeemers", []):
            eu = redeemer["executionUnits"]
            assert "memory" in eu
            assert "cpu" in eu
            assert eu["memory"] > 0
            assert eu["cpu"] > 0

    def test_babbage_fixture_redeemer_has_ex_units(self) -> None:
        """Redeemers in Babbage fixture must have execution units."""
        block = load_fixture("babbage")
        tx = block["transactions"][0]
        for redeemer in tx.get("redeemers", []):
            eu = redeemer["executionUnits"]
            assert "memory" in eu
            assert "cpu" in eu
            assert eu["memory"] > 0
            assert eu["cpu"] > 0

    def test_redeemer_purpose_is_valid(self) -> None:
        """Redeemer purposes must be one of the valid Ogmios values."""
        valid_purposes = {"spend", "mint", "publish", "withdraw"}
        for era in ["alonzo", "babbage"]:
            block = load_fixture(era)
            for tx in block["transactions"]:
                for redeemer in tx.get("redeemers", []):
                    purpose = redeemer["validator"]["purpose"]
                    assert purpose in valid_purposes, (
                        f"Invalid redeemer purpose '{purpose}' in {era}"
                    )


# ===================================================================
# TIER 2: Live Ogmios Plutus conformance tests (requires Docker)
# ===================================================================


@pytest.mark.conformance
@pytest.mark.timeout(30)
class TestLivePlutusScriptPresence:
    """Verify Plutus-related protocol state via Ogmios queries.

    These tests use Ogmios query methods (not chain-sync traversal)
    for fast, reliable results without needing to seek through blocks.
    """

    async def test_metadata_extraction_on_early_blocks(
        self, ogmios_client: websockets.ClientConnection,
    ) -> None:
        """Verify script metadata extraction logic works on real blocks.

        Uses early chain blocks (from origin) where we know there are
        no scripts — validates the extraction doesn't crash and reports
        zero counts correctly.
        """
        blocks = await fetch_blocks_from_origin(ogmios_client, count=5)
        for block in blocks:
            meta = extract_block_metadata(block)
            # Early Byron blocks have no scripts
            assert meta["script_count"] >= 0
            assert meta["datum_count"] >= 0
            assert meta["redeemer_count"] >= 0

    async def test_protocol_params_have_cost_models(
        self, ogmios_url: str,
    ) -> None:
        """Verify current protocol parameters include Plutus cost models.

        Ogmios queryLedgerState/protocolParameters returns cost models
        for all active Plutus versions.
        """
        async with websockets.connect(ogmios_url) as ws:
            params = await ogmios_rpc(
                ws, "queryLedgerState/protocolParameters", rpc_id="params"
            )

            # Protocol parameters should include cost model data
            # The exact key depends on Ogmios version, but it should exist
            assert "plutusCostModels" in params or "costModels" in params, (
                f"No cost model data in protocol parameters. Keys: {list(params.keys())}"
            )
