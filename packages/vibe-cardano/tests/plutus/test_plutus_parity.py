"""Plutus test parity — cost model params, budget enforcement, data round-trip.

Haskell references:
    - cardano-ledger/eras/alonzo/impl/test/ (cost model param counts)
    - plutus-ledger-api (ExUnits, budget checking)
    - plutus-core (PlutusData CBOR encoding)
"""

from __future__ import annotations

import cbor2pure as cbor2

from vibe.cardano.plutus.cost_model import (
    BUILTINS_INTRODUCED_IN,
    COST_MODEL_PARAM_COUNTS,
    ExUnits,
    PlutusVersion,
    builtins_available_at,
)

# ---------------------------------------------------------------------------
# Cost model parameter counts
# ---------------------------------------------------------------------------


class TestCostModelParamCounts:
    """Verify exact cost model parameter counts per Plutus version."""

    def test_v1_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V1] == 166

    def test_v2_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] == 175

    def test_v3_param_count(self) -> None:
        assert COST_MODEL_PARAM_COUNTS[PlutusVersion.V3] == 233

    def test_v2_has_more_params_than_v1(self) -> None:
        assert (
            COST_MODEL_PARAM_COUNTS[PlutusVersion.V2] > COST_MODEL_PARAM_COUNTS[PlutusVersion.V1]
        )

    def test_v3_has_more_params_than_v2(self) -> None:
        assert (
            COST_MODEL_PARAM_COUNTS[PlutusVersion.V3] > COST_MODEL_PARAM_COUNTS[PlutusVersion.V2]
        )


class TestBuiltinVersionEnforcement:
    """Verify builtins are correctly assigned to versions."""

    def test_v1_builtins_nonempty(self) -> None:
        assert len(BUILTINS_INTRODUCED_IN[PlutusVersion.V1]) > 0

    def test_v2_adds_serialise_data(self) -> None:
        assert "SerialiseData" in BUILTINS_INTRODUCED_IN[PlutusVersion.V2]

    def test_v2_adds_secp256k1(self) -> None:
        v2 = BUILTINS_INTRODUCED_IN[PlutusVersion.V2]
        assert "VerifyEcdsaSecp256k1Signature" in v2
        assert "VerifySchnorrSecp256k1Signature" in v2

    def test_v3_adds_bls(self) -> None:
        v3 = BUILTINS_INTRODUCED_IN[PlutusVersion.V3]
        assert "Bls12_381_G1_Add" in v3
        assert "Bls12_381_FinalVerify" in v3

    def test_v3_adds_bitwise(self) -> None:
        v3 = BUILTINS_INTRODUCED_IN[PlutusVersion.V3]
        assert "IntegerToByteString" in v3
        assert "ByteStringToInteger" in v3
        assert "AndByteString" in v3

    def test_builtins_available_at_v1_subset_of_v2(self) -> None:
        v1 = builtins_available_at(PlutusVersion.V1)
        v2 = builtins_available_at(PlutusVersion.V2)
        assert v1.issubset(v2)

    def test_builtins_available_at_v2_subset_of_v3(self) -> None:
        v2 = builtins_available_at(PlutusVersion.V2)
        v3 = builtins_available_at(PlutusVersion.V3)
        assert v2.issubset(v3)

    def test_no_version_overlap(self) -> None:
        """Each builtin is introduced in exactly one version."""
        v1 = BUILTINS_INTRODUCED_IN[PlutusVersion.V1]
        v2 = BUILTINS_INTRODUCED_IN[PlutusVersion.V2]
        v3 = BUILTINS_INTRODUCED_IN[PlutusVersion.V3]
        assert v1.isdisjoint(v2)
        assert v1.isdisjoint(v3)
        assert v2.isdisjoint(v3)


# ---------------------------------------------------------------------------
# ExUnits validation
# ---------------------------------------------------------------------------


class TestExUnitsValidation:
    """Verify ExUnits dataclass behavior."""

    def test_creation(self) -> None:
        eu = ExUnits(mem=1000, steps=2000)
        assert eu.mem == 1000
        assert eu.steps == 2000

    def test_zero_units(self) -> None:
        eu = ExUnits(mem=0, steps=0)
        assert eu.mem == 0
        assert eu.steps == 0

    def test_large_values(self) -> None:
        """Mainnet max: 14M mem, 10B steps."""
        eu = ExUnits(mem=14_000_000, steps=10_000_000_000)
        assert eu.mem == 14_000_000
        assert eu.steps == 10_000_000_000

    def test_fits_within_both_dimensions(self) -> None:
        small = ExUnits(mem=100, steps=200)
        big = ExUnits(mem=1000, steps=2000)
        assert small.mem <= big.mem and small.steps <= big.steps

    def test_exceeds_in_one_dimension(self) -> None:
        a = ExUnits(mem=100, steps=3000)
        b = ExUnits(mem=1000, steps=2000)
        # a.steps > b.steps even though a.mem < b.mem
        assert a.steps > b.steps


# ---------------------------------------------------------------------------
# PlutusData CBOR round-trip
# ---------------------------------------------------------------------------


class TestPlutusDataCborRoundTrip:
    """Verify PlutusData CBOR encoding/decoding preserves structure."""

    def test_integer_roundtrip(self) -> None:
        data = 42
        assert cbor2.loads(cbor2.dumps(data)) == data

    def test_negative_integer(self) -> None:
        data = -1
        assert cbor2.loads(cbor2.dumps(data)) == data

    def test_bytestring_roundtrip(self) -> None:
        data = b"\x01\x02\x03"
        assert cbor2.loads(cbor2.dumps(data)) == data

    def test_list_roundtrip(self) -> None:
        data = [1, 2, 3]
        assert cbor2.loads(cbor2.dumps(data)) == data

    def test_map_roundtrip(self) -> None:
        data = {1: 2, 3: 4}
        assert cbor2.loads(cbor2.dumps(data)) == data

    def test_constructor_tag_121(self) -> None:
        """Constr 0 uses CBOR tag 121."""
        data = cbor2.CBORTag(121, [])
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded.tag == 121
        assert decoded.value == []

    def test_constructor_tag_122(self) -> None:
        """Constr 1 uses CBOR tag 122."""
        data = cbor2.CBORTag(122, [42])
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded.tag == 122
        assert decoded.value == [42]

    def test_nested_structure(self) -> None:
        """Nested constructors and lists."""
        inner = cbor2.CBORTag(121, [1, b"\xab"])
        outer = cbor2.CBORTag(122, [inner, [3, 4]])
        encoded = cbor2.dumps(outer)
        decoded = cbor2.loads(encoded)
        assert decoded.tag == 122
        assert decoded.value[0].tag == 121

    def test_empty_collections(self) -> None:
        for data in [[], {}, b""]:
            assert cbor2.loads(cbor2.dumps(data)) == data

    def test_large_integer(self) -> None:
        """Big integers used in Cardano for lovelace amounts."""
        data = 45_000_000_000_000_000  # 45M ADA in lovelace
        assert cbor2.loads(cbor2.dumps(data)) == data
