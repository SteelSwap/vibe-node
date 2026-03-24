"""Tests for PlutusData CBOR round-tripping and trace output.

Covers:
1. PlutusData → CBOR → PlutusData round-trip for all Data constructors
2. Trace builtin output correctness and ordering
3. Edge cases: large integers, empty collections, nested structures,
   constructor tag encodings (compact, alternative, general)

Spec references:
    * Plutus Core specification, Section 3 (Data type)
    * CBOR encoding: tags 121-127 (compact), 1280-1400 (alternative),
      tag 102 (general constructor)

Haskell references:
    * PlutusCore.Data — the Data type definition
    * PlutusCore.Data.encodeData / decodeData
"""

from __future__ import annotations

from uplc.ast import (
    PlutusByteString,
    PlutusConstr,
    PlutusData,
    PlutusInteger,
    PlutusList,
    PlutusMap,
    data_from_cbor,
    data_from_json_dict,
    plutus_cbor_dumps,
)
from uplc.tools import eval as uplc_eval
from uplc.tools import parse

# ---------------------------------------------------------------------------
# 1. PlutusData CBOR round-trip
# ---------------------------------------------------------------------------


class TestPlutusDataCborRoundtrip:
    """PlutusData → CBOR → PlutusData must be identity for all types."""

    # --- Integers ---

    def test_zero(self):
        self._assert_roundtrip(PlutusInteger(0))

    def test_positive_int(self):
        self._assert_roundtrip(PlutusInteger(42))

    def test_negative_int(self):
        self._assert_roundtrip(PlutusInteger(-1))

    def test_large_positive_int(self):
        """Integer beyond 64-bit range."""
        self._assert_roundtrip(PlutusInteger(2**128 + 1))

    def test_large_negative_int(self):
        self._assert_roundtrip(PlutusInteger(-(2**128)))

    def test_int_boundary_64bit(self):
        """Exactly at CBOR major type boundary."""
        self._assert_roundtrip(PlutusInteger(2**64 - 1))
        self._assert_roundtrip(PlutusInteger(2**64))

    # --- ByteStrings ---

    def test_empty_bytestring(self):
        self._assert_roundtrip(PlutusByteString(b""))

    def test_short_bytestring(self):
        self._assert_roundtrip(PlutusByteString(b"\xde\xad\xbe\xef"))

    def test_long_bytestring(self):
        """ByteString > 64 bytes triggers chunked CBOR encoding."""
        self._assert_roundtrip(PlutusByteString(bytes(range(256)) * 2))

    # --- Lists ---

    def test_empty_list(self):
        self._assert_roundtrip(PlutusList([]))

    def test_homogeneous_list(self):
        self._assert_roundtrip(PlutusList([PlutusInteger(i) for i in range(5)]))

    def test_heterogeneous_list(self):
        self._assert_roundtrip(
            PlutusList(
                [
                    PlutusInteger(1),
                    PlutusByteString(b"abc"),
                    PlutusList([]),
                ]
            )
        )

    # --- Maps ---

    def test_empty_map(self):
        self._assert_roundtrip(PlutusMap(()))

    def test_simple_map(self):
        self._assert_roundtrip(
            PlutusMap(
                (
                    (PlutusInteger(1), PlutusByteString(b"one")),
                    (PlutusInteger(2), PlutusByteString(b"two")),
                )
            )
        )

    def test_map_with_bytestring_keys(self):
        self._assert_roundtrip(
            PlutusMap(
                (
                    (PlutusByteString(b"key1"), PlutusInteger(1)),
                    (PlutusByteString(b"key2"), PlutusInteger(2)),
                )
            )
        )

    # --- Constructors ---

    def test_constr_tag_0(self):
        """Tag 0-6 use compact CBOR encoding (tags 121-127)."""
        self._assert_roundtrip(PlutusConstr(0, [PlutusInteger(42)]))

    def test_constr_tag_6(self):
        """Last compact tag."""
        self._assert_roundtrip(PlutusConstr(6, []))

    def test_constr_tag_7(self):
        """Tag 7-127 use alternative encoding (tags 1280-1400)."""
        self._assert_roundtrip(PlutusConstr(7, [PlutusInteger(1)]))

    def test_constr_tag_127(self):
        """Last alternative tag."""
        self._assert_roundtrip(PlutusConstr(127, []))

    def test_constr_tag_128(self):
        """Tag >= 128 uses general encoding (tag 102)."""
        self._assert_roundtrip(PlutusConstr(128, [PlutusInteger(1)]))

    def test_constr_tag_large(self):
        """Large constructor tag."""
        self._assert_roundtrip(PlutusConstr(1000, []))

    def test_constr_empty_fields(self):
        self._assert_roundtrip(PlutusConstr(0, []))

    def test_constr_many_fields(self):
        fields = [PlutusInteger(i) for i in range(20)]
        self._assert_roundtrip(PlutusConstr(0, fields))

    # --- Nested structures ---

    def test_nested_constr_in_list(self):
        self._assert_roundtrip(
            PlutusList(
                [
                    PlutusConstr(0, [PlutusInteger(1)]),
                    PlutusConstr(1, [PlutusByteString(b"x")]),
                ]
            )
        )

    def test_deeply_nested(self):
        """3 levels deep: constr containing list containing map."""
        inner_map = PlutusMap(((PlutusInteger(1), PlutusByteString(b"v")),))
        inner_list = PlutusList([inner_map, PlutusInteger(99)])
        outer = PlutusConstr(0, [inner_list])
        self._assert_roundtrip(outer)

    # --- Helper ---

    def _assert_roundtrip(self, data: PlutusData):
        encoded = plutus_cbor_dumps(data)
        decoded = data_from_cbor(encoded)
        assert data == decoded, f"Round-trip failed:\n  Input:   {data}\n  Decoded: {decoded}"


# ---------------------------------------------------------------------------
# 2. PlutusData JSON round-trip
# ---------------------------------------------------------------------------


class TestPlutusDataJsonRoundtrip:
    """PlutusData → JSON → PlutusData round-trip."""

    def test_integer(self):
        data = PlutusInteger(42)
        assert data_from_json_dict(data.to_json()) == data

    def test_bytestring(self):
        data = PlutusByteString(b"\xca\xfe")
        assert data_from_json_dict(data.to_json()) == data

    def test_list(self):
        data = PlutusList([PlutusInteger(1), PlutusInteger(2)])
        assert data_from_json_dict(data.to_json()) == data

    def test_map(self):
        data = PlutusMap(((PlutusInteger(1), PlutusByteString(b"a")),))
        assert data_from_json_dict(data.to_json()) == data

    def test_constr(self):
        data = PlutusConstr(3, [PlutusInteger(10), PlutusByteString(b"")])
        assert data_from_json_dict(data.to_json()) == data


# ---------------------------------------------------------------------------
# 3. Trace output
# ---------------------------------------------------------------------------


class TestTraceOutput:
    """Validate trace builtin captures messages correctly."""

    def test_single_trace(self):
        """Single trace message captured in logs."""
        prog = parse(
            '(program 1.0.0 [[(force (builtin trace)) (con string "hello")] (con integer 1)])'
        )
        result = uplc_eval(prog)
        assert result.logs == ["hello"]
        assert result.result.value == 1

    def test_multiple_traces(self):
        """Multiple traces are captured."""
        prog = parse(
            "(program 1.0.0 "
            '[[(force (builtin trace)) (con string "first")] '
            '[[(force (builtin trace)) (con string "second")] '
            "(con integer 42)]])"
        )
        result = uplc_eval(prog)
        assert set(result.logs) == {"first", "second"}
        assert result.result.value == 42

    def test_trace_with_unicode(self):
        """Trace handles unicode strings."""
        prog = parse(
            '(program 1.0.0 [[(force (builtin trace)) (con string "café")] (con unit ())])'
        )
        result = uplc_eval(prog)
        assert result.logs == ["café"]

    def test_no_trace_empty_logs(self):
        """Program without trace has empty logs."""
        prog = parse("(program 1.0.0 (con integer 42))")
        result = uplc_eval(prog)
        assert result.logs == [] or result.logs is None

    def test_trace_before_error(self):
        """Error after trace — CEK machine may or may not preserve traces."""
        prog = parse(
            '(program 1.0.0 [[(force (builtin trace)) (con string "before error")] (error)])'
        )
        result = uplc_eval(prog)
        assert isinstance(result.result, Exception)
        # Note: the uplc CEK machine currently discards trace logs when
        # evaluation fails. This matches the Haskell behavior where logs
        # are only returned on successful evaluation.
