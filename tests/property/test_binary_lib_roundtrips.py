"""Binary lib CBOR round-trip tests — Cardano-specific typed wrappers.

Tests that mirror cardano-binary's Haskell test suite (Test.Cardano.Binary):
- SlotNo / EpochNo / BlockNo / EpochSize as CBOR uint at boundary values
- SystemStart as ISO 8601 text
- embedTripSpec: smaller type encodes, larger type decodes (Word8→Word16)
- Set→List embedding: CBOR tag 258 set decodes as list
- Vintage Byron-style: Unit, Bool, Integer, Word32/64, Int32/64, Float, Rational
- Sum-type CBOR encoding with tag discriminators
- SubBytes / Annotated: pre-encoded CBOR bytes wrapped in tag 24
- Hex text round-trip: bytes.hex() ↔ bytes.fromhex()

These tests validate the CBOR serialization patterns used in cardano-binary
and cardano-ledger-binary, which are the foundation of all on-chain data.

Haskell reference:
    cardano-ledger-binary:test:Test.Cardano.Ledger.Binary.RoundTrip
    cardano-base:cardano-binary:test:Test.Cardano.Binary.RoundTrip
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction

import cbor2
import pytest


# ---------------------------------------------------------------------------
# 1. SlotNo / EpochNo / BlockNo / EpochSize as CBOR uint
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestSlotEpochBlockBoundaryValues:
    """Round-trip Cardano numeric identifiers at uint boundary values.

    Haskell reference: Cardano.Slotting.Slot (SlotNo, EpochNo, EpochSize)
    and Cardano.Slotting.Block (BlockNo) are all newtypes over Word64.
    They encode as bare CBOR unsigned integers.
    """

    # (label, value) pairs covering CBOR encoding boundaries.
    BOUNDARY_VALUES: list[tuple[str, int]] = [
        ("zero", 0),
        ("one", 1),
        ("max_single_byte", 23),
        ("two_byte_boundary", 24),
        ("uint8_max", 255),
        ("uint16_boundary", 256),
        ("uint16_max", 65535),
        ("uint32_boundary", 65536),
        ("uint32_max", 2**32 - 1),
        ("uint64_boundary", 2**32),
        ("uint64_max", 2**64 - 1),
    ]

    @pytest.mark.parametrize("label,value", BOUNDARY_VALUES, ids=[v[0] for v in BOUNDARY_VALUES])
    def test_slot_no_roundtrip(self, label: str, value: int) -> None:
        """SlotNo round-trips as CBOR uint."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert isinstance(decoded, int)

    @pytest.mark.parametrize("label,value", BOUNDARY_VALUES, ids=[v[0] for v in BOUNDARY_VALUES])
    def test_epoch_no_roundtrip(self, label: str, value: int) -> None:
        """EpochNo round-trips as CBOR uint (same encoding as SlotNo)."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value

    @pytest.mark.parametrize("label,value", BOUNDARY_VALUES, ids=[v[0] for v in BOUNDARY_VALUES])
    def test_block_no_roundtrip(self, label: str, value: int) -> None:
        """BlockNo round-trips as CBOR uint."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value

    @pytest.mark.parametrize("label,value", BOUNDARY_VALUES, ids=[v[0] for v in BOUNDARY_VALUES])
    def test_epoch_size_roundtrip(self, label: str, value: int) -> None:
        """EpochSize round-trips as CBOR uint."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value

    @pytest.mark.parametrize("label,value", BOUNDARY_VALUES, ids=[v[0] for v in BOUNDARY_VALUES])
    def test_cbor_uint_minimal_encoding(self, label: str, value: int) -> None:
        """Verify CBOR uses minimal encoding for each boundary value.

        Per RFC 7049 Section 2.1:
        - 0-23:     1 byte (major type 0 + additional info in low 5 bits)
        - 24-255:   2 bytes (major type 0 + 0x18 + 1 byte)
        - 256-65535: 3 bytes (major type 0 + 0x19 + 2 bytes)
        - 65536-2^32-1: 5 bytes (major type 0 + 0x1a + 4 bytes)
        - 2^32-2^64-1: 9 bytes (major type 0 + 0x1b + 8 bytes)
        """
        encoded = cbor2.dumps(value)
        if value <= 23:
            assert len(encoded) == 1
        elif value <= 255:
            assert len(encoded) == 2
        elif value <= 65535:
            assert len(encoded) == 3
        elif value <= 2**32 - 1:
            assert len(encoded) == 5
        else:
            assert len(encoded) == 9


# ---------------------------------------------------------------------------
# 2. SystemStart as CBOR text (ISO 8601) round-trip
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestSystemStartIso8601:
    """SystemStart encodes as ISO 8601 text in CBOR.

    Haskell reference: Cardano.Slotting.Time (SystemStart) is a UTCTime
    serialized as a CBOR text string in ISO 8601 format.
    """

    SYSTEM_START_VALUES: list[str] = [
        "2017-09-23T21:44:51Z",       # Byron mainnet genesis
        "2022-11-01T00:00:00Z",        # Preview testnet
        "2000-01-01T00:00:00Z",        # Y2K boundary
        "2099-12-31T23:59:59Z",        # Far future
    ]

    @pytest.mark.parametrize("iso_str", SYSTEM_START_VALUES)
    def test_system_start_text_roundtrip(self, iso_str: str) -> None:
        """SystemStart ISO 8601 string round-trips through CBOR text."""
        encoded = cbor2.dumps(iso_str)
        decoded = cbor2.loads(encoded)
        assert decoded == iso_str
        assert isinstance(decoded, str)

    @pytest.mark.parametrize("iso_str", SYSTEM_START_VALUES)
    def test_system_start_parses_to_datetime(self, iso_str: str) -> None:
        """ISO 8601 text from CBOR parses to a valid datetime."""
        encoded = cbor2.dumps(iso_str)
        decoded = cbor2.loads(encoded)
        # Parse the ISO string — Cardano uses the Z suffix for UTC
        dt = datetime.fromisoformat(decoded.replace("Z", "+00:00"))
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0  # Must be UTC

    def test_system_start_canonical_encoding(self) -> None:
        """Canonical encoding of SystemStart text is deterministic."""
        iso_str = "2017-09-23T21:44:51Z"
        enc1 = cbor2.dumps(iso_str, canonical=True)
        enc2 = cbor2.dumps(iso_str, canonical=True)
        assert enc1 == enc2


# ---------------------------------------------------------------------------
# 3. embedTripSpec: Word8 → Word16 embedding
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestEmbedTripSpec:
    """embedTripSpec equivalent — smaller type encodes, larger type decodes.

    Haskell reference: Test.Cardano.Ledger.Binary.RoundTrip.embedTripSpec
    Tests that a value encoded as a smaller numeric type can be decoded
    as a wider type (e.g., Word8 → Word16, Word16 → Word32).
    """

    WORD8_VALUES: list[int] = [0, 1, 127, 255]

    @pytest.mark.parametrize("value", WORD8_VALUES)
    def test_word8_embeds_in_word16(self, value: int) -> None:
        """A Word8 value encoded as CBOR uint decodes within Word16 range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert 0 <= decoded <= 65535, "decoded value out of Word16 range"

    @pytest.mark.parametrize("value", WORD8_VALUES)
    def test_word8_embeds_in_word32(self, value: int) -> None:
        """A Word8 value encoded as CBOR uint decodes within Word32 range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert 0 <= decoded <= 2**32 - 1

    @pytest.mark.parametrize("value", WORD8_VALUES)
    def test_word8_embeds_in_word64(self, value: int) -> None:
        """A Word8 value encoded as CBOR uint decodes within Word64 range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert 0 <= decoded <= 2**64 - 1

    WORD16_VALUES: list[int] = [0, 255, 256, 65535]

    @pytest.mark.parametrize("value", WORD16_VALUES)
    def test_word16_embeds_in_word32(self, value: int) -> None:
        """Word16 encoded as CBOR uint decodes within Word32 range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert 0 <= decoded <= 2**32 - 1

    WORD32_VALUES: list[int] = [0, 65535, 65536, 2**32 - 1]

    @pytest.mark.parametrize("value", WORD32_VALUES)
    def test_word32_embeds_in_word64(self, value: int) -> None:
        """Word32 encoded as CBOR uint decodes within Word64 range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert 0 <= decoded <= 2**64 - 1


# ---------------------------------------------------------------------------
# 4. Set → List embedding (CBOR tag 258 set decodes as list)
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestSetListEmbedding:
    """CBOR tag 258 set can be decoded as a plain list.

    Haskell reference: The ledger encodes sets using tag 258. When
    decoding with a tag hook that preserves raw tags, the underlying
    array is accessible as a list.
    """

    def test_tag258_set_decodes_as_list_via_conversion(self) -> None:
        """Tag 258 wrapping an array decodes as set, convertible to sorted list.

        cbor2 >= 5.6 auto-decodes tag 258 to frozenset (RFC 8949 semantics).
        The embedding test verifies that the set can be converted back to a
        sorted list matching the original canonical ordering.
        """
        elements = [3, 1, 4, 1, 5]
        unique_sorted = sorted(set(elements))
        tagged = cbor2.CBORTag(258, unique_sorted)
        encoded = cbor2.dumps(tagged)

        # cbor2 auto-decodes tag 258 → frozenset
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))

        # Convert back to sorted list — the embedding relationship
        as_list = sorted(decoded)
        assert as_list == unique_sorted

    def test_tag258_empty_set_as_list(self) -> None:
        """Empty tag 258 set decodes as empty set, convertible to list."""
        tagged = cbor2.CBORTag(258, [])
        encoded = cbor2.dumps(tagged)

        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))
        assert sorted(decoded) == []

    def test_tag258_bytestring_elements(self) -> None:
        """Tag 258 with bytestring elements (like tx input refs) → set → list."""
        elements = [b"\xde\xad", b"\xbe\xef", b"\xca\xfe"]
        tagged = cbor2.CBORTag(258, sorted(elements))
        encoded = cbor2.dumps(tagged)

        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))
        assert all(isinstance(e, bytes) for e in decoded)
        # The set→list embedding: sorted conversion recovers the original order
        assert sorted(decoded) == sorted(elements)


# ---------------------------------------------------------------------------
# 5. Vintage Byron-style round-trips
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestByronStyleRoundtrips:
    """Byron-era CBOR patterns — the simplest building blocks.

    Haskell reference: Test.Cardano.Binary.RoundTrip (Unit, Bool, Integer,
    Word8/16/32/64, Int32/64, Float, Rational).
    """

    def test_unit_as_empty_cbor(self) -> None:
        """Unit encodes as CBOR null (major type 7, value 22)."""
        encoded = cbor2.dumps(None)
        decoded = cbor2.loads(encoded)
        assert decoded is None
        # Verify wire format: single byte 0xf6 (null)
        assert encoded == b"\xf6"

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_roundtrip(self, value: bool) -> None:
        """Bool round-trips as CBOR simple values (true=0xf5, false=0xf4)."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded is value
        expected_byte = b"\xf5" if value else b"\xf4"
        assert encoded == expected_byte

    @pytest.mark.parametrize(
        "value",
        [0, 1, -1, 42, -42, 2**63 - 1, -(2**63), 2**128, -(2**128)],
        ids=["zero", "one", "neg_one", "small_pos", "small_neg",
             "max_int64", "min_int64", "big_pos", "big_neg"],
    )
    def test_integer_roundtrip(self, value: int) -> None:
        """Arbitrary-precision integers round-trip via CBOR."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value

    @pytest.mark.parametrize(
        "value,bits",
        [(0, 32), (2**32 - 1, 32), (0, 64), (2**64 - 1, 64)],
        ids=["word32_min", "word32_max", "word64_min", "word64_max"],
    )
    def test_word_roundtrip(self, value: int, bits: int) -> None:
        """Word32/Word64 round-trip within their unsigned range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert 0 <= decoded < 2**bits

    @pytest.mark.parametrize(
        "value,bits",
        [
            (0, 32), (2**31 - 1, 32), (-(2**31), 32),
            (0, 64), (2**63 - 1, 64), (-(2**63), 64),
        ],
        ids=["int32_zero", "int32_max", "int32_min",
             "int64_zero", "int64_max", "int64_min"],
    )
    def test_signed_int_roundtrip(self, value: int, bits: int) -> None:
        """Int32/Int64 round-trip within their signed range."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value
        assert -(2**(bits - 1)) <= decoded < 2**(bits - 1)

    @pytest.mark.parametrize(
        "value",
        [0.0, 1.0, -1.0, 3.14159, float("inf"), float("-inf")],
        ids=["zero", "one", "neg_one", "pi", "inf", "neg_inf"],
    )
    def test_float_roundtrip(self, value: float) -> None:
        """Float round-trips via CBOR (IEEE 754)."""
        encoded = cbor2.dumps(value)
        decoded = cbor2.loads(encoded)
        assert decoded == value

    def test_float_nan_roundtrip(self) -> None:
        """NaN round-trips (NaN != NaN, so check with math.isnan)."""
        encoded = cbor2.dumps(float("nan"))
        decoded = cbor2.loads(encoded)
        assert math.isnan(decoded)

    @pytest.mark.parametrize(
        "num,den",
        [(1, 3), (22, 7), (0, 1), (-1, 2), (2**64, 3)],
        ids=["one_third", "pi_approx", "zero", "neg_half", "large"],
    )
    def test_rational_as_tagged_array(self, num: int, den: int) -> None:
        """Rational encodes as CBOR tag 30 [numerator, denominator].

        Haskell reference: Data.Ratio encoded via CBOR as tag 30.
        cbor2 auto-decodes tag 30 to a Fraction.
        """
        frac = Fraction(num, den)
        # Encode as tag 30 with [numerator, denominator] array
        tagged = cbor2.CBORTag(30, [frac.numerator, frac.denominator])
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        # cbor2 may auto-decode tag 30 to Fraction
        if isinstance(decoded, Fraction):
            assert decoded == frac
        elif isinstance(decoded, cbor2.CBORTag):
            assert decoded.tag == 30
            assert decoded.value == [frac.numerator, frac.denominator]
        else:
            pytest.fail(f"Unexpected type: {type(decoded)}")


# ---------------------------------------------------------------------------
# 6. Sum-type CBOR encoding with tag discriminator
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestSumTypeCborEncoding:
    """Sum types (ADTs) encoded with CBOR tag as discriminator.

    In Cardano ledger CBOR, sum types typically encode as:
    [tag_number, ...fields]  or  CBOR tag wrapping the variant data.

    Haskell reference: various ledger types use encodeListLen + encodeWord
    for the discriminator tag at the start of a CBOR array.
    """

    @dataclass
    class VariantA:
        value: int

    @dataclass
    class VariantB:
        name: str
        flag: bool

    def _encode_sum_type(self, obj: object) -> bytes:
        """Encode a sum type as [discriminator, ...fields]."""
        if isinstance(obj, self.VariantA):
            return cbor2.dumps([0, obj.value])
        elif isinstance(obj, self.VariantB):
            return cbor2.dumps([1, obj.name, obj.flag])
        raise TypeError(f"Unknown variant: {type(obj)}")

    def _decode_sum_type(self, data: bytes) -> object:
        """Decode a sum type from [discriminator, ...fields]."""
        arr = cbor2.loads(data)
        tag = arr[0]
        if tag == 0:
            return self.VariantA(value=arr[1])
        elif tag == 1:
            return self.VariantB(name=arr[1], flag=arr[2])
        raise ValueError(f"Unknown discriminator: {tag}")

    def test_variant_a_roundtrip(self) -> None:
        """VariantA (tag 0) round-trips through CBOR."""
        obj = self.VariantA(value=42)
        encoded = self._encode_sum_type(obj)
        decoded = self._decode_sum_type(encoded)
        assert isinstance(decoded, self.VariantA)
        assert decoded.value == 42

    def test_variant_b_roundtrip(self) -> None:
        """VariantB (tag 1) round-trips through CBOR."""
        obj = self.VariantB(name="hello", flag=True)
        encoded = self._encode_sum_type(obj)
        decoded = self._decode_sum_type(encoded)
        assert isinstance(decoded, self.VariantB)
        assert decoded.name == "hello"
        assert decoded.flag is True

    def test_discriminator_preserved_in_wire_format(self) -> None:
        """The first element of the CBOR array is the discriminator tag."""
        obj_a = self.VariantA(value=99)
        obj_b = self.VariantB(name="x", flag=False)

        raw_a = cbor2.loads(self._encode_sum_type(obj_a))
        raw_b = cbor2.loads(self._encode_sum_type(obj_b))

        assert raw_a[0] == 0
        assert raw_b[0] == 1

    def test_invalid_discriminator_raises(self) -> None:
        """Unknown discriminator tag raises ValueError."""
        bad_data = cbor2.dumps([99, "bogus"])
        with pytest.raises(ValueError, match="Unknown discriminator"):
            self._decode_sum_type(bad_data)


# ---------------------------------------------------------------------------
# 7. SubBytes / Annotated: pre-encoded CBOR in tag 24
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestSubBytesAnnotatedPattern:
    """SubBytes / Annotated pattern — pre-encoded CBOR wrapped in tag 24.

    In Cardano, tag 24 (embedded CBOR) is used for Plutus script datums
    and other cases where a blob of pre-serialized CBOR is stored inline.
    The Haskell 'Annotated' pattern preserves the original bytes alongside
    the decoded value for re-serialization fidelity.

    Haskell reference:
        Cardano.Ledger.Binary.Decoding.Annotated (Annotator, decCBOR)
        CBOR tag 24 = "Encoded CBOR data item" (RFC 7049 Section 2.4.4.1)
    """

    @pytest.mark.parametrize(
        "inner_value",
        [42, "hello", [1, 2, 3], {"key": "value"}, True, None, b"\xde\xad"],
        ids=["int", "text", "list", "map", "bool", "null", "bytes"],
    )
    def test_tag24_wraps_pre_encoded_cbor(self, inner_value: object) -> None:
        """Tag 24 wrapping pre-encoded CBOR bytes round-trips."""
        inner_cbor = cbor2.dumps(inner_value)
        tagged = cbor2.CBORTag(24, inner_cbor)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, cbor2.CBORTag)
        assert decoded.tag == 24
        assert decoded.value == inner_cbor

        # Extract and verify inner value
        inner_decoded = cbor2.loads(decoded.value)
        assert inner_decoded == inner_value

    def test_tag24_nested(self) -> None:
        """Tag 24 inside tag 24 — double-wrapped CBOR."""
        inner = cbor2.dumps(99)
        middle = cbor2.dumps(cbor2.CBORTag(24, inner))
        outer = cbor2.CBORTag(24, middle)
        encoded = cbor2.dumps(outer)

        # Decode outer
        dec_outer = cbor2.loads(encoded)
        assert isinstance(dec_outer, cbor2.CBORTag)
        assert dec_outer.tag == 24

        # Decode middle
        dec_middle = cbor2.loads(dec_outer.value)
        assert isinstance(dec_middle, cbor2.CBORTag)
        assert dec_middle.tag == 24

        # Decode inner
        dec_inner = cbor2.loads(dec_middle.value)
        assert dec_inner == 99

    def test_tag24_preserves_exact_bytes(self) -> None:
        """The inner CBOR bytes are preserved bit-for-bit — no re-encoding.

        This is the key invariant for the Annotated pattern: the original
        serialization is kept intact for hash stability.
        """
        # Use a non-canonical encoding on purpose (map with unordered keys)
        inner_cbor = cbor2.dumps({2: "b", 1: "a"})
        tagged = cbor2.CBORTag(24, inner_cbor)
        encoded = cbor2.dumps(tagged)

        decoded = cbor2.loads(encoded)
        # The exact bytes must be preserved — not re-encoded
        assert decoded.value == inner_cbor


# ---------------------------------------------------------------------------
# 8. Hex text round-trip: bytes.hex() ↔ bytes.fromhex()
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestHexTextRoundtrip:
    """Hex text encoding of CBOR payloads — used in JSON APIs and logs.

    In the Cardano ecosystem, CBOR-encoded data is often transmitted as
    hex strings (e.g., in Ogmios JSON responses, transaction submission APIs).
    This tests the hex encoding/decoding of CBOR payloads.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"\x00",
            b"\xff",
            b"\xde\xad\xbe\xef",
            bytes(range(256)),
        ],
        ids=["empty", "zero_byte", "ff_byte", "deadbeef", "all_256"],
    )
    def test_hex_roundtrip_raw_bytes(self, payload: bytes) -> None:
        """Raw bytes → hex string → bytes round-trips exactly."""
        hex_str = payload.hex()
        recovered = bytes.fromhex(hex_str)
        assert recovered == payload

    @pytest.mark.parametrize(
        "value",
        [42, [1, 2, 3], {"a": 1}, b"\xca\xfe", True],
        ids=["int", "list", "map", "bytes", "bool"],
    )
    def test_hex_roundtrip_cbor_payload(self, value: object) -> None:
        """CBOR-encoded value → hex → bytes → CBOR decode round-trips."""
        cbor_bytes = cbor2.dumps(value)
        hex_str = cbor_bytes.hex()

        # Recover from hex
        recovered_bytes = bytes.fromhex(hex_str)
        assert recovered_bytes == cbor_bytes

        # Decode and verify
        decoded = cbor2.loads(recovered_bytes)
        assert decoded == value

    def test_hex_roundtrip_tag24_plutus_datum(self) -> None:
        """Tag 24 wrapped Plutus datum survives hex encoding."""
        datum = cbor2.CBORTag(121, [42, b"\xde\xad"])
        inner_cbor = cbor2.dumps(datum)
        tagged = cbor2.CBORTag(24, inner_cbor)
        full_cbor = cbor2.dumps(tagged)

        # Hex round-trip
        hex_str = full_cbor.hex()
        recovered = bytes.fromhex(hex_str)
        assert recovered == full_cbor

        # Decode and verify structure
        decoded = cbor2.loads(recovered)
        assert decoded.tag == 24
        inner_decoded = cbor2.loads(decoded.value)
        assert inner_decoded.tag == 121
        assert inner_decoded.value == [42, b"\xde\xad"]

    def test_hex_case_insensitive_decode(self) -> None:
        """bytes.fromhex() handles mixed-case hex strings."""
        cbor_bytes = cbor2.dumps(42)
        lower = cbor_bytes.hex()
        upper = lower.upper()
        mixed = "".join(
            c.upper() if i % 2 == 0 else c.lower()
            for i, c in enumerate(lower)
        )

        assert bytes.fromhex(lower) == cbor_bytes
        assert bytes.fromhex(upper) == cbor_bytes
        assert bytes.fromhex(mixed) == cbor_bytes
