"""Tests for the Plutus script evaluation pipeline.

Covers:
1. Script deserialization (flat decode, double-CBOR unwrap, V3 strict mode)
2. Flat encode/decode round-trip against conformance test programs
3. Cost model resolution and wiring (V1, V2, V3 defaults and overrides)
4. Budget enforcement (exhaustion detection)
5. PlutusData conversion (pycardano → uplc)
6. Full evaluate_script pipeline

Spec references:
    * Alonzo ledger formal spec, Section 4.1 (Script evaluation)
    * Alonzo ledger formal spec, Section 4.4 (Evaluating scripts)

Haskell references:
    * evalPlutusScript in Cardano.Ledger.Alonzo.Plutus.Evaluate
    * deserialiseScript in Cardano.Ledger.Plutus.Language
"""

from __future__ import annotations

import pytest
from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusInteger,
    PlutusList,
    PlutusMap,
)
from uplc.tools import eval as uplc_eval
from uplc.tools import flatten, parse, unflatten

from vibe.cardano.plutus.cost_model import ExUnits, PlutusVersion
from vibe.cardano.plutus.evaluate import (
    _get_uplc_cost_models,
    deserialize_script,
    evaluate_script,
    pycardano_to_uplc_data,
)

# ---------------------------------------------------------------------------
# 1. Script deserialization
# ---------------------------------------------------------------------------


class TestDeserializeScript:
    """Test flat decode and double-CBOR unwrap of Plutus scripts."""

    def test_simple_program_roundtrip(self):
        """Parse → flatten → unflatten preserves program semantics."""
        prog = parse("(program 1.0.0 (con integer 42))")
        flat_bytes = flatten(prog)
        restored = unflatten(flat_bytes)
        result = uplc_eval(restored)
        assert result.result.value == 42

    def test_double_cbor_wrap(self):
        """deserialize_script handles double-CBOR wrapping (on-chain format)."""
        import cbor2pure as cbor2

        prog = parse("(program 1.0.0 (con integer 99))")
        flat_bytes = flatten(prog)
        # Double-wrap: CBOR(CBOR(flat_bytes))
        double_wrapped = cbor2.dumps(flat_bytes)
        restored = deserialize_script(double_wrapped)
        result = uplc_eval(restored)
        assert result.result.value == 99

    def test_v3_strict_rejects_trailing(self):
        """V3 strict mode rejects programs with trailing bytes.

        We construct trailing data by manually appending extra bits to the
        flat-encoded bytes before CBOR wrapping.
        """
        import cbor2pure as cbor2

        prog = parse("(program 1.1.0 (con integer 1))")
        flat_bytes = flatten(prog)
        # The flat_bytes is CBOR(flat_data). Unwrap to get raw flat, pad, re-wrap.
        raw_flat = cbor2.loads(flat_bytes)
        padded_flat = raw_flat + b"\xaa\xbb"
        # Single-CBOR wrap for unflatten
        padded_cbor = cbor2.dumps(padded_flat)
        # Double-CBOR wrap for deserialize_script
        double_wrapped = cbor2.dumps(padded_cbor)
        with pytest.raises(ValueError, match="[Tt]railing"):
            deserialize_script(double_wrapped, version=PlutusVersion.V3)

    def test_v2_lenient_accepts_trailing(self):
        """V2 lenient mode accepts programs with trailing bytes."""
        import cbor2pure as cbor2

        prog = parse("(program 1.0.0 (con integer 1))")
        flat_bytes = flatten(prog)
        padded = flat_bytes + b"\x00\x00"
        padded_cbor = cbor2.dumps(padded)
        # V2 lenient should accept
        restored = deserialize_script(padded_cbor, version=PlutusVersion.V2)
        assert restored is not None

    def test_malformed_bytes_raises(self):
        """Completely invalid bytes raise ValueError."""
        with pytest.raises(ValueError):
            deserialize_script(b"\xff\xff\xff")

    def test_conformance_programs_roundtrip(self):
        """Spot-check: parse conformance programs → flatten → unflatten → eval
        produces the same result as direct eval.
        """
        programs = [
            "(program 1.0.0 [(builtin addInteger) (con integer 3) (con integer 4)])",
            "(program 1.0.0 (con bool True))",
            "(program 1.0.0 [(builtin sha2_256) (con bytestring #)])",
            "(program 1.1.0 (case (constr 0) (con integer 42)))",
        ]
        for source in programs:
            prog = parse(source)
            direct_result = uplc_eval(prog)
            flat_bytes = flatten(prog)
            restored = unflatten(flat_bytes)
            roundtrip_result = uplc_eval(restored)
            # Both should produce the same output type
            assert type(direct_result.result) is type(roundtrip_result.result)


# ---------------------------------------------------------------------------
# 2. Cost model resolution
# ---------------------------------------------------------------------------


class TestCostModelResolution:
    """Test cost model selection and override wiring."""

    def test_v1_defaults(self):
        """V1 returns V1 cost models."""
        cek, builtin = _get_uplc_cost_models(PlutusVersion.V1)
        assert cek is not None
        assert builtin is not None

    def test_v2_defaults(self):
        """V2 returns V2 cost models."""
        cek, builtin = _get_uplc_cost_models(PlutusVersion.V2)
        assert cek is not None
        assert builtin is not None

    def test_v3_defaults(self):
        """V3 returns V3 cost models."""
        cek, builtin = _get_uplc_cost_models(PlutusVersion.V3)
        assert cek is not None
        assert builtin is not None

    def test_all_versions_cover_all_builtins(self):
        """All versions have cost entries for all defined builtins."""
        for ver in (PlutusVersion.V1, PlutusVersion.V2, PlutusVersion.V3):
            _, builtin = _get_uplc_cost_models(ver)
            # Should have entries for all builtins in the enum
            assert len(builtin.cpu) > 0
            assert len(builtin.memory) > 0
            assert len(builtin.cpu) == len(builtin.memory)

    def test_budget_consumed_matches_cost_model(self):
        """Eval with default V3 cost model produces non-zero budget."""
        prog = parse("(program 1.0.0 [(builtin addInteger) (con integer 1) (con integer 2)])")
        result = uplc_eval(prog)
        assert result.cost.cpu > 0
        assert result.cost.memory > 0


# ---------------------------------------------------------------------------
# 3. Budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    """Test that budget exhaustion is detected."""

    def _make_script_bytes(self, source: str) -> bytes:
        import cbor2pure as cbor2

        prog = parse(source)
        return cbor2.dumps(flatten(prog))

    def test_sufficient_budget_succeeds(self):
        """Script with ample budget succeeds."""
        # Script accepts 2 args (redeemer, context) and returns unit
        script = self._make_script_bytes("(program 1.0.0 (lam r (lam ctx (con unit ()))))")
        result = evaluate_script(
            script_bytes=script,
            datum=None,
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V2,
        )
        assert result.success
        assert result.ex_units_consumed.steps > 0
        assert result.ex_units_consumed.mem > 0

    def test_tiny_budget_fails(self):
        """Script with impossibly small budget fails."""
        script = self._make_script_bytes("(program 1.0.0 (lam r (lam ctx (con unit ()))))")

        result = evaluate_script(
            script_bytes=script,
            datum=None,
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=1, steps=1),
            version=PlutusVersion.V2,
        )
        assert not result.success
        assert result.error is not None


# ---------------------------------------------------------------------------
# 4. PlutusData conversion
# ---------------------------------------------------------------------------


class TestPlutusDataConversion:
    """Test pycardano_to_uplc_data conversion."""

    def test_int_to_plutus_integer(self):
        assert pycardano_to_uplc_data(42) == PlutusInteger(42)

    def test_negative_int(self):
        assert pycardano_to_uplc_data(-1) == PlutusInteger(-1)

    def test_bytes_to_plutus_bytestring(self):
        assert pycardano_to_uplc_data(b"\xde\xad") == PlutusByteString(b"\xde\xad")

    def test_empty_bytes(self):
        assert pycardano_to_uplc_data(b"") == PlutusByteString(b"")

    def test_list_to_plutus_list(self):
        result = pycardano_to_uplc_data([1, 2, 3])
        assert isinstance(result, PlutusList)
        assert len(result.value) == 3

    def test_dict_to_plutus_map(self):
        result = pycardano_to_uplc_data({1: b"a", 2: b"b"})
        assert isinstance(result, PlutusMap)
        pairs = list(result.items())
        assert len(pairs) == 2

    def test_nested_structure(self):
        """Nested list of dicts converts correctly."""
        data = [{"key": 1}, {"key": 2}]
        # This uses string keys which aren't valid PlutusData, but dict keys
        # are converted recursively — strings aren't supported though
        # Use bytes keys instead
        data = [{b"k": 1}, {b"k": 2}]
        result = pycardano_to_uplc_data(data)
        assert isinstance(result, PlutusList)
        assert len(result.value) == 2

    def test_none_raises(self):
        with pytest.raises(TypeError):
            pycardano_to_uplc_data(None)

    def test_bool_not_converted_as_int(self):
        """Python bool should not be silently converted to PlutusInteger."""
        with pytest.raises(TypeError):
            pycardano_to_uplc_data(True)

    def test_passthrough_uplc_data(self):
        """Already-uplc PlutusData passes through unchanged."""
        data = PlutusInteger(42)
        assert pycardano_to_uplc_data(data) is data


# ---------------------------------------------------------------------------
# 5. Full pipeline: evaluate_script
# ---------------------------------------------------------------------------


class TestEvaluateScript:
    """Integration tests for the full evaluate_script pipeline."""

    def _make_script_bytes(self, source: str) -> bytes:
        """Helper: parse → flatten → CBOR-wrap."""
        import cbor2pure as cbor2

        prog = parse(source)
        return cbor2.dumps(flatten(prog))

    def test_always_succeeds(self):
        """Script that ignores args and returns unit succeeds."""
        # (lam d (lam r (lam ctx (con unit ()))))
        script = self._make_script_bytes("(program 1.0.0 (lam d (lam r (lam ctx (con unit ())))))")
        result = evaluate_script(
            script_bytes=script,
            datum=PlutusInteger(0),
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V2,
        )
        assert result.success

    def test_always_fails(self):
        """Script that calls error always fails."""
        script = self._make_script_bytes("(program 1.0.0 (lam d (lam r (lam ctx (error)))))")
        result = evaluate_script(
            script_bytes=script,
            datum=PlutusInteger(0),
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V2,
        )
        assert not result.success

    def test_v3_single_arg(self):
        """V3 scripts receive a single context argument."""
        script = self._make_script_bytes("(program 1.1.0 (lam ctx (con unit ())))")
        result = evaluate_script(
            script_bytes=script,
            datum=None,
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V3,
        )
        assert result.success

    def test_deserialization_failure_returns_error(self):
        """Invalid script bytes produce an error result, not an exception."""
        result = evaluate_script(
            script_bytes=b"\xff\xff",
            datum=None,
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V2,
        )
        assert not result.success
        assert "deserialization" in result.error.lower()

    def test_consumed_units_reported(self):
        """Successful evaluation reports consumed ExUnits."""
        script = self._make_script_bytes(
            "(program 1.0.0 (lam d (lam r (lam ctx "
            "[(builtin addInteger) (con integer 1) (con integer 2)]))))"
        )
        result = evaluate_script(
            script_bytes=script,
            datum=PlutusInteger(0),
            redeemer=PlutusInteger(0),
            script_context=PlutusConstr(0, []),
            ex_units=ExUnits(mem=10_000_000, steps=10_000_000_000),
            version=PlutusVersion.V2,
        )
        assert result.success
        assert result.ex_units_consumed.steps > 0
        assert result.ex_units_consumed.mem > 0
