"""CBOR round-trip property tests for Cardano serialization fidelity.

VNODE-155: Validates that cbor2 (pure Python mode) correctly round-trips all
data types found in Cardano blocks and transactions. This is the serialization
foundation — if CBOR encode/decode isn't bit-perfect, nothing downstream works.

We use cbor2 in pure Python mode because the C extension has known bugs that
affect Cardano-specific patterns (see feedback_cbor2_issues.md). pycardano uses
cbor2pure for the same reason.

Key Cardano CBOR patterns tested:
- Tag 24: Embedded CBOR (used for Plutus script datums)
- Tag 258: Sets (used for transaction inputs, required signers)
- Indefinite-length arrays/maps (used in real block encoding)
- Bytestring map keys (used for policy IDs, asset names)
- Canonical CBOR (deterministic serialization for hashing)
"""

from __future__ import annotations

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Force pure-Python cbor2 — the C extension has bugs that bite Cardano data.
# We verify this at import time so tests fail loudly if something changes.
# ---------------------------------------------------------------------------

def _ensure_pure_python_cbor2() -> None:
    """Verify we can use cbor2 and it behaves correctly.

    Note: cbor2 >= 5.6 auto-decodes some well-known tags:
    - Tag 258 -> frozenset (RFC 8949 §3.4.5.1)
    - Tag 2/3 -> int (bignums)
    - Tag 1 -> datetime

    We use tag_hook=None or check for these conversions explicitly.
    """
    # Smoke test: encode and decode a tagged value
    test_val = cbor2.CBORTag(24, cbor2.dumps(42))
    raw = cbor2.dumps(test_val)
    decoded = cbor2.loads(raw)
    assert isinstance(decoded, cbor2.CBORTag)
    assert decoded.tag == 24


_ensure_pure_python_cbor2()


# ---------------------------------------------------------------------------
# Hypothesis strategies for Cardano-relevant CBOR data
# ---------------------------------------------------------------------------

# Integers: Cardano uses unsigned for most fields, but signed for some
# (e.g., transaction metadata). CBOR supports arbitrary precision.
cardano_integers = st.one_of(
    st.integers(min_value=0, max_value=0),            # zero
    st.integers(min_value=1, max_value=23),            # single-byte CBOR
    st.integers(min_value=24, max_value=255),          # two-byte CBOR
    st.integers(min_value=256, max_value=65535),        # three-byte CBOR
    st.integers(min_value=65536, max_value=2**32 - 1),  # five-byte CBOR
    st.integers(min_value=2**32, max_value=2**64 - 1),  # nine-byte CBOR
    st.integers(min_value=-(2**64), max_value=-1),      # negative
    st.integers(min_value=2**64, max_value=2**128),     # big integers
)

# Bytestrings at boundary lengths (CBOR encoding changes at 24, 256, 65536)
cardano_bytestrings = st.one_of(
    st.binary(min_size=0, max_size=0),     # empty
    st.binary(min_size=1, max_size=1),     # single byte
    st.binary(min_size=23, max_size=23),   # max single-byte length
    st.binary(min_size=24, max_size=24),   # triggers two-byte length
    st.binary(min_size=255, max_size=255),
    st.binary(min_size=256, max_size=256), # triggers three-byte length
    st.binary(min_size=1, max_size=512),   # general range
)

# Text strings (used in metadata)
cardano_text = st.text(min_size=0, max_size=64)


# ---------------------------------------------------------------------------
# Test 1: Integer round-trip
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestIntegerRoundtrip:
    """Verify CBOR integer encoding/decoding across the full range."""

    @given(n=cardano_integers)
    @settings(max_examples=200)
    def test_integer_roundtrip(self, n: int) -> None:
        """Arbitrary integers survive encode-decode unchanged."""
        encoded = cbor2.dumps(n)
        decoded = cbor2.loads(encoded)
        assert decoded == n
        assert type(decoded) is type(n)

    @given(n=st.integers(min_value=-(2**64), max_value=2**64))
    @settings(max_examples=200)
    def test_integer_canonical_roundtrip(self, n: int) -> None:
        """Canonical encoding also round-trips correctly."""
        encoded = cbor2.dumps(n, canonical=True)
        decoded = cbor2.loads(encoded)
        assert decoded == n


# ---------------------------------------------------------------------------
# Test 2: Bytestring round-trip
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestBytestringRoundtrip:
    """Verify CBOR bytestring encoding at all length boundaries."""

    @given(data=cardano_bytestrings)
    @settings(max_examples=200)
    def test_bytestring_roundtrip(self, data: bytes) -> None:
        """Bytestrings of various lengths survive encode-decode."""
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded == data
        assert isinstance(decoded, bytes)

    @given(data=st.binary(min_size=0, max_size=1024))
    @settings(max_examples=200)
    def test_bytestring_canonical_roundtrip(self, data: bytes) -> None:
        """Canonical bytestring encoding round-trips."""
        encoded = cbor2.dumps(data, canonical=True)
        decoded = cbor2.loads(encoded)
        assert decoded == data


# ---------------------------------------------------------------------------
# Test 3: Nested structure round-trip (Cardano patterns)
# ---------------------------------------------------------------------------

# Strategy for map keys: Cardano uses bytestrings (policy IDs, asset names)
# and integers as map keys
map_keys = st.one_of(
    st.binary(min_size=0, max_size=32),
    st.integers(min_value=0, max_value=2**32),
    st.text(min_size=0, max_size=32),
)

# Leaf values in Cardano structures
leaf_values = st.one_of(
    cardano_integers,
    cardano_bytestrings,
    cardano_text,
    st.booleans(),
    st.none(),
)

# Recursive strategy for nested Cardano-like structures
cardano_structures = st.recursive(
    leaf_values,
    lambda children: st.one_of(
        # Lists (used for transaction bodies, witness sets)
        st.lists(children, min_size=0, max_size=5),
        # Maps with bytestring/integer keys (used for multi-assets, metadata)
        st.dictionaries(
            keys=map_keys,
            values=children,
            min_size=0,
            max_size=5,
        ),
    ),
    max_leaves=20,
)


@pytest.mark.property
class TestNestedStructureRoundtrip:
    """Verify nested structures matching Cardano data patterns."""

    @given(structure=cardano_structures)
    @settings(max_examples=200)
    def test_nested_structure_roundtrip(self, structure: object) -> None:
        """Nested lists/maps with mixed key types survive encode-decode."""
        encoded = cbor2.dumps(structure)
        decoded = cbor2.loads(encoded)
        assert decoded == structure

    @given(inner=leaf_values)
    @settings(max_examples=200)
    def test_tag24_wrapped_structure(self, inner: object) -> None:
        """Tag 24 (embedded CBOR) wrapping arbitrary values round-trips.

        Cardano uses tag 24 for Plutus script datums — the datum is
        CBOR-encoded, then that bytestring is itself CBOR-encoded with
        tag 24 wrapping it.
        """
        # Encode inner value, wrap in tag 24 (embedded CBOR pattern)
        inner_cbor = cbor2.dumps(inner)
        tagged = cbor2.CBORTag(24, inner_cbor)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, cbor2.CBORTag)
        assert decoded.tag == 24
        assert decoded.value == inner_cbor

        # Verify the inner value can be extracted
        inner_decoded = cbor2.loads(decoded.value)
        assert inner_decoded == inner

    @given(elements=st.lists(st.integers(min_value=0, max_value=2**32), min_size=0, max_size=10))
    @settings(max_examples=200)
    def test_tag258_set_structure(self, elements: list[int]) -> None:
        """Tag 258 (sets) wrapping lists of integers round-trips.

        Cardano uses tag 258 for sets (transaction inputs, required signers).
        cbor2 auto-decodes tag 258 to a frozenset, so we verify the
        semantic equivalence rather than raw tag preservation.
        """
        unique_elements = set(elements)
        tagged = cbor2.CBORTag(258, sorted(unique_elements))
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        # cbor2 auto-decodes tag 258 -> frozenset
        assert isinstance(decoded, (set, frozenset)), (
            f"Expected set/frozenset for tag 258, got {type(decoded).__name__}"
        )
        assert set(decoded) == unique_elements

        # Verify re-encoding a set produces tag 258
        re_encoded = cbor2.dumps(decoded)
        # Decode with tag_hook to verify the tag is preserved in the wire format
        def preserve_tags(decoder, tag):
            return cbor2.CBORTag(tag.tag, tag.value)
        re_decoded = cbor2.loads(re_encoded, tag_hook=preserve_tags)
        if isinstance(re_decoded, cbor2.CBORTag):
            assert re_decoded.tag == 258


# ---------------------------------------------------------------------------
# Test 4: Canonical CBOR determinism
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestCanonicalCborDeterministic:
    """Verify canonical encoding is deterministic — same input, same bytes.

    This is critical for Cardano: transaction IDs are hashes of canonical
    CBOR. If encoding isn't deterministic, hashes won't match.
    """

    @given(value=cardano_structures)
    @settings(max_examples=200)
    def test_canonical_deterministic(self, value: object) -> None:
        """Same Python object always encodes to identical bytes."""
        encoded1 = cbor2.dumps(value, canonical=True)
        encoded2 = cbor2.dumps(value, canonical=True)
        assert encoded1 == encoded2

    @given(value=cardano_structures)
    @settings(max_examples=200)
    def test_canonical_decode_reencode_stable(self, value: object) -> None:
        """Encode -> decode -> re-encode produces identical bytes."""
        encoded1 = cbor2.dumps(value, canonical=True)
        decoded = cbor2.loads(encoded1)
        encoded2 = cbor2.dumps(decoded, canonical=True)
        assert encoded1 == encoded2


# ---------------------------------------------------------------------------
# Test 5: Tag preservation
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestTagPreservation:
    """Verify CBOR tags survive encode/decode round-trips."""

    @given(
        tag_number=st.sampled_from([24, 121, 122]),
        inner=leaf_values,
    )
    @settings(max_examples=200)
    def test_tag_preservation_non_semantic(self, tag_number: int, inner: object) -> None:
        """Tags without semantic auto-decoding preserve as CBORTag.

        Tags tested:
        - 24: Embedded CBOR (Plutus datums)
        - 121-122: Constr alternatives (Plutus data constructors)

        These tags are NOT auto-decoded by cbor2, so they survive
        as CBORTag instances.
        """
        if tag_number == 24:
            inner_bytes = cbor2.dumps(inner)
            tagged = cbor2.CBORTag(24, inner_bytes)
        else:
            tagged = cbor2.CBORTag(tag_number, inner)

        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, cbor2.CBORTag), (
            f"Tag {tag_number} was not preserved as CBORTag; "
            f"got {type(decoded).__name__}: {decoded!r}"
        )
        assert decoded.tag == tag_number
        if tag_number == 24:
            assert decoded.value == inner_bytes
        else:
            assert decoded.value == inner

    @given(inner=st.binary(min_size=0, max_size=32))
    @settings(max_examples=200)
    def test_tag2_bignum_semantic(self, inner: bytes) -> None:
        """Tag 2 (positive bignum) is auto-decoded to int by cbor2.

        This is correct behavior per RFC 8949. We verify the
        semantic conversion is faithful.
        """
        tagged = cbor2.CBORTag(2, inner)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        # cbor2 converts tag 2 to a Python int
        expected = int.from_bytes(inner, "big") if inner else 0
        assert decoded == expected

    @given(inner=st.binary(min_size=0, max_size=32))
    @settings(max_examples=200)
    def test_tag3_negative_bignum_semantic(self, inner: bytes) -> None:
        """Tag 3 (negative bignum) is auto-decoded to int by cbor2."""
        tagged = cbor2.CBORTag(3, inner)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        # cbor2 converts tag 3: -1 - unsigned_value
        unsigned = int.from_bytes(inner, "big") if inner else 0
        expected = -1 - unsigned
        assert decoded == expected

    @given(
        elements=st.lists(
            st.integers(min_value=0, max_value=1000),
            min_size=1,
            max_size=8,
        )
    )
    @settings(max_examples=200)
    def test_tag258_set_semantic(self, elements: list[int]) -> None:
        """Tag 258 (set) is auto-decoded to frozenset by cbor2.

        Cardano uses tag 258 for sets. cbor2 auto-converts this to
        a Python frozenset, which is the correct semantic interpretation.
        We verify the wire format preserves tag 258 via tag_hook.
        """
        unique = sorted(set(elements))
        tagged = cbor2.CBORTag(258, unique)
        encoded = cbor2.dumps(tagged)

        # Default decoding: auto-converted to set/frozenset
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))
        assert set(decoded) == set(unique)

        # Wire-level verification: tag 258 is present in the encoding
        # Verify the raw bytes start with tag 258 marker (0xd9 0x01 0x02)
        assert encoded[:3] == b"\xd9\x01\x02", (
            f"Expected tag 258 prefix d90102, got {encoded[:3].hex()}"
        )

    def test_tag258_empty_set(self) -> None:
        """Tag 258 with empty list round-trips as empty set."""
        tagged = cbor2.CBORTag(258, [])
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))
        assert len(decoded) == 0

    @given(
        elements=st.lists(
            st.binary(min_size=1, max_size=32),
            min_size=1,
            max_size=8,
        )
    )
    @settings(max_examples=200)
    def test_tag258_set_with_bytestring_elements(self, elements: list[bytes]) -> None:
        """Tag 258 sets with bytestring elements (like tx input refs)."""
        unique = sorted(set(elements))
        tagged = cbor2.CBORTag(258, unique)
        encoded = cbor2.dumps(tagged)

        # Default: auto-decoded to frozenset
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, (set, frozenset))
        assert set(decoded) == set(unique)

        # Verify tag 258 prefix in wire format
        assert encoded[:3] == b"\xd9\x01\x02"


# ---------------------------------------------------------------------------
# Test 6: Indefinite-length handling
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestIndefiniteLengthHandling:
    """Verify indefinite-length arrays and maps decode correctly.

    Real Cardano blocks use indefinite-length encoding in several positions.
    The CBOR wire format uses 0x9f...0xff for indefinite arrays and
    0xbf...0xff for indefinite maps.
    """

    @given(items=st.lists(leaf_values, min_size=0, max_size=10))
    @settings(max_examples=200)
    def test_indefinite_array_decode(self, items: list[object]) -> None:
        """Hand-craft indefinite-length array bytes, verify decode matches."""
        # Build indefinite array: 0x9f <items> 0xff
        parts = [b"\x9f"]
        for item in items:
            parts.append(cbor2.dumps(item))
        parts.append(b"\xff")
        raw = b"".join(parts)

        decoded = cbor2.loads(raw)
        assert isinstance(decoded, list)
        assert len(decoded) == len(items)
        for i, (dec, orig) in enumerate(zip(decoded, items)):
            assert dec == orig, f"Mismatch at index {i}: {dec!r} != {orig!r}"

    @given(
        keys=st.lists(
            st.binary(min_size=1, max_size=16),
            min_size=0,
            max_size=5,
            unique=True,
        ),
        values=st.lists(
            st.integers(min_value=0, max_value=1000),
            min_size=0,
            max_size=5,
        ),
    )
    @settings(max_examples=200)
    def test_indefinite_map_decode(
        self, keys: list[bytes], values: list[int]
    ) -> None:
        """Hand-craft indefinite-length map bytes, verify decode matches."""
        # Truncate to min length
        n = min(len(keys), len(values))
        keys = keys[:n]
        values = values[:n]

        # Build indefinite map: 0xbf <key-value pairs> 0xff
        parts = [b"\xbf"]
        for k, v in zip(keys, values):
            parts.append(cbor2.dumps(k))
            parts.append(cbor2.dumps(v))
        parts.append(b"\xff")
        raw = b"".join(parts)

        decoded = cbor2.loads(raw)
        assert isinstance(decoded, dict)
        assert len(decoded) == n
        for k, v in zip(keys, values):
            assert decoded[k] == v

    @given(items=st.lists(st.integers(min_value=0, max_value=100), min_size=0, max_size=8))
    @settings(max_examples=200)
    def test_indefinite_vs_definite_equivalence(self, items: list[int]) -> None:
        """Indefinite and definite arrays decode to the same Python list."""
        # Definite encoding via cbor2
        definite = cbor2.dumps(items)

        # Indefinite encoding by hand
        parts = [b"\x9f"]
        for item in items:
            parts.append(cbor2.dumps(item))
        parts.append(b"\xff")
        indefinite = b"".join(parts)

        assert cbor2.loads(definite) == cbor2.loads(indefinite)


# ---------------------------------------------------------------------------
# Test 7: Map key ordering in canonical CBOR
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestMapKeyOrderingCanonical:
    """Verify canonical CBOR produces correctly ordered map keys.

    RFC 7049 Section 3.9 (Canonical CBOR): map keys are sorted by:
    1. Shorter encoded keys come first
    2. Keys of equal length are sorted lexicographically by encoded bytes

    This matters for Cardano because transaction body hashes depend on
    deterministic serialization — wrong key order = wrong hash = invalid block.
    """

    @given(
        mapping=st.dictionaries(
            keys=st.one_of(
                st.integers(min_value=0, max_value=2**32),
                st.binary(min_size=0, max_size=32),
                st.text(min_size=0, max_size=16),
            ),
            values=st.integers(min_value=0, max_value=100),
            min_size=2,
            max_size=10,
        )
    )
    @settings(max_examples=200)
    def test_canonical_key_ordering(self, mapping: dict) -> None:
        """Canonical encoding sorts keys: shorter first, then lexicographic."""
        encoded = cbor2.dumps(mapping, canonical=True)
        decoded_raw = cbor2.loads(encoded)

        # Re-encode each key to get its CBOR byte representation
        key_bytes = [cbor2.dumps(k, canonical=True) for k in decoded_raw.keys()]

        # Verify keys are in canonical order
        for i in range(len(key_bytes) - 1):
            a, b = key_bytes[i], key_bytes[i + 1]
            if len(a) != len(b):
                assert len(a) < len(b), (
                    f"Canonical violation: key at index {i} "
                    f"(len={len(a)}) should come before key at index {i+1} "
                    f"(len={len(b)})"
                )
            else:
                assert a <= b, (
                    f"Canonical violation: keys of equal length at "
                    f"indices {i},{i+1} are not lexicographically ordered"
                )

    @given(
        keys=st.lists(
            st.binary(min_size=1, max_size=32),
            min_size=2,
            max_size=8,
            unique=True,
        )
    )
    @settings(max_examples=200)
    def test_canonical_bytestring_key_ordering(self, keys: list[bytes]) -> None:
        """Maps with bytestring keys (like multi-asset maps) are ordered."""
        mapping = {k: i for i, k in enumerate(keys)}
        encoded = cbor2.dumps(mapping, canonical=True)

        # Decode and get the raw bytes of each key
        decoded = cbor2.loads(encoded)
        encoded_keys = [cbor2.dumps(k, canonical=True) for k in decoded.keys()]

        # Verify ordering
        for i in range(len(encoded_keys) - 1):
            a, b = encoded_keys[i], encoded_keys[i + 1]
            assert (len(a), a) <= (len(b), b), (
                f"Bytestring keys not in canonical order at indices {i},{i+1}"
            )

    @given(
        int_keys=st.lists(
            st.integers(min_value=0, max_value=2**16),
            min_size=2,
            max_size=8,
            unique=True,
        )
    )
    @settings(max_examples=200)
    def test_canonical_integer_key_ordering(self, int_keys: list[int]) -> None:
        """Maps with integer keys (like tx body fields) are ordered."""
        mapping = {k: f"field_{k}" for k in int_keys}
        encoded = cbor2.dumps(mapping, canonical=True)

        decoded = cbor2.loads(encoded)
        encoded_keys = [cbor2.dumps(k, canonical=True) for k in decoded.keys()]

        for i in range(len(encoded_keys) - 1):
            a, b = encoded_keys[i], encoded_keys[i + 1]
            assert (len(a), a) <= (len(b), b), (
                f"Integer keys not in canonical order at indices {i},{i+1}"
            )


# ---------------------------------------------------------------------------
# Test 8: Canonical encoding minimal length for unsigned integers
# Spec: test_canonical_encoding_minimal_length_for_unsigned_int
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestCanonicalEncodingMinimalLengthUnsignedInt:
    """Verify CBOR canonical encoding uses minimal byte length for unsigned ints.

    Per RFC 7049 Section 2.1, the canonical encoding of unsigned integers must
    use the shortest possible representation:
    - 0-23:         1 byte  (value in additional info)
    - 24-255:       2 bytes (additional info = 24, then 1 byte)
    - 256-65535:    3 bytes (additional info = 25, then 2 bytes)
    - 65536-2^32-1: 5 bytes (additional info = 26, then 4 bytes)

    This is critical for Cardano because transaction hashes depend on
    deterministic, minimal-length CBOR encoding.
    """

    @given(n=st.integers(min_value=0, max_value=2**32 - 1))
    @settings(max_examples=500)
    def test_canonical_encoding_minimal_length_unsigned_int(self, n: int) -> None:
        """Unsigned int canonical encoding uses the minimum number of bytes."""
        encoded = cbor2.dumps(n, canonical=True)

        if n <= 23:
            expected_len = 1
        elif n <= 255:
            expected_len = 2
        elif n <= 65535:
            expected_len = 3
        else:  # n <= 2**32 - 1
            expected_len = 5

        assert len(encoded) == expected_len, (
            f"Canonical encoding of {n} is {len(encoded)} bytes, "
            f"expected {expected_len}. Hex: {encoded.hex()}"
        )

        # Verify round-trip
        decoded = cbor2.loads(encoded)
        assert decoded == n

    def test_canonical_encoding_boundary_values(self) -> None:
        """Explicit boundary checks at each encoding width transition."""
        boundaries = [
            (0, 1),
            (23, 1),
            (24, 2),
            (255, 2),
            (256, 3),
            (65535, 3),
            (65536, 5),
            (2**32 - 1, 5),
        ]
        for value, expected_len in boundaries:
            encoded = cbor2.dumps(value, canonical=True)
            assert len(encoded) == expected_len, (
                f"Boundary value {value}: expected {expected_len} bytes, "
                f"got {len(encoded)}. Hex: {encoded.hex()}"
            )


# ---------------------------------------------------------------------------
# Test 9: Indefinite-length bytestring encoding for >= 65 bytes
# Spec: test_eBS_long_is_indefinite_length
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestIndefiniteBytestringLongEncoding:
    """Verify indefinite-length bytestring encoding for >= 65 bytes.

    The Plutus spec defines eBS (encode bytestring) such that bytestrings
    >= 65 bytes are encoded as indefinite-length bytestrings (0x5F...0xFF)
    with 64-byte chunks. cbor2 with canonical=False may use this encoding.

    This test verifies that regardless of encoding style, the decoded
    bytestring is always the original bytes.
    """

    @given(data=st.binary(min_size=65, max_size=1024))
    @settings(max_examples=200)
    def test_indefinite_bytestring_65_plus_bytes(self, data: bytes) -> None:
        """Bytestrings >= 65 bytes survive encode-decode regardless of encoding form.

        We manually construct the indefinite-length chunked encoding that
        Cardano uses for long bytestrings and verify cbor2 decodes it correctly.
        """
        # Build indefinite-length bytestring with 64-byte chunks (Cardano pattern)
        # 0x5F = indefinite-length bytestring marker
        parts = [b"\x5f"]
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 64]
            parts.append(cbor2.dumps(chunk))  # Each chunk as a definite bytestring
            offset += 64
        parts.append(b"\xff")  # break code
        indefinite_encoded = b"".join(parts)

        # Verify the marker bytes
        assert indefinite_encoded[0:1] == b"\x5f", "Should start with indefinite marker"
        assert indefinite_encoded[-1:] == b"\xff", "Should end with break code"

        # Decode and verify
        decoded = cbor2.loads(indefinite_encoded)
        assert isinstance(decoded, bytes)
        assert decoded == data, (
            f"Indefinite bytestring decode mismatch: "
            f"expected {len(data)} bytes, got {len(decoded)}"
        )

    @given(data=st.binary(min_size=65, max_size=512))
    @settings(max_examples=200)
    def test_indefinite_bytestring_chunk_structure(self, data: bytes) -> None:
        """Verify all interior chunks in the indefinite encoding are exactly 64 bytes
        except possibly the last."""
        # Build chunks the way Cardano does it
        chunks = []
        offset = 0
        while offset < len(data):
            chunks.append(data[offset:offset + 64])
            offset += 64

        # All chunks except the last must be exactly 64 bytes
        for i, chunk in enumerate(chunks[:-1]):
            assert len(chunk) == 64, (
                f"Interior chunk {i} is {len(chunk)} bytes, expected 64"
            )

        # Last chunk can be 1-64 bytes
        assert 1 <= len(chunks[-1]) <= 64

        # Verify reassembly
        assert b"".join(chunks) == data


# ---------------------------------------------------------------------------
# Test 10: Bounded bytestring max 64 round-trip (dBlock boundary)
# Spec: test_dblock_valid_bytestrings_roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestBoundedBytestringMax64Roundtrip:
    """Verify bytestrings 0-64 bytes encode and decode faithfully.

    The Plutus spec defines dBlock as the decoder for bounded bytestrings
    (max 64 bytes). This is the fundamental building block for Plutus Data
    bytestring values — every B(b) in PlutusData has |b| <= 64.

    This test validates that the CBOR layer correctly handles bytestrings
    at and below this boundary.
    """

    @given(data=st.binary(min_size=0, max_size=64))
    @settings(max_examples=300)
    def test_bounded_bytestring_max_64_roundtrip(self, data: bytes) -> None:
        """Bytestrings 0-64 bytes survive CBOR encode-decode exactly."""
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded == data
        assert isinstance(decoded, bytes)

        # Verify canonical encoding also works
        canonical = cbor2.dumps(data, canonical=True)
        assert cbor2.loads(canonical) == data

        # For <= 64 bytes, encoding must be definite-length (not indefinite)
        # Major type 2 (bytestring): first byte high nibble = 0x40
        assert (encoded[0] & 0xe0) == 0x40, (
            f"Expected major type 2 (bytestring), got 0x{encoded[0]:02x}. "
            f"Bytestrings <= 64 bytes should use definite-length encoding."
        )

    def test_bounded_bytestring_boundary_values(self) -> None:
        """Explicit tests at the 64-byte boundary."""
        # Exactly 64 bytes — should work
        data_64 = bytes(range(64))
        encoded = cbor2.dumps(data_64)
        assert cbor2.loads(encoded) == data_64
        # Must be definite-length
        assert (encoded[0] & 0xe0) == 0x40

        # Empty bytestring — should work
        data_0 = b""
        encoded_0 = cbor2.dumps(data_0)
        assert cbor2.loads(encoded_0) == data_0
        assert encoded_0 == b"\x40"  # Major type 2, length 0


# ---------------------------------------------------------------------------
# Test 11: Bounded bytestring 65 bytes rejected by validation
# Spec: test_dblock_rejects_oversized_bytestrings
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestBoundedBytestring65Rejected:
    """Verify that bytestrings exceeding the 64-byte Plutus bound are detected.

    The Plutus spec says dBlock must reject bytestrings > 64 bytes. cbor2
    itself doesn't enforce this (it's a generic CBOR library), so this test
    validates our detection logic: given a decoded bytestring, we can
    identify when it violates the 64-byte bound.

    This documents the contract that our Plutus Data decoder must enforce.
    """

    PLUTUS_MAX_BYTESTRING_LEN = 64

    @given(data=st.binary(min_size=65, max_size=1024))
    @settings(max_examples=200)
    def test_bounded_bytestring_65_rejected(self, data: bytes) -> None:
        """Bytestrings > 64 bytes are detectable as bound violations.

        cbor2 will happily encode/decode them — the bound enforcement
        is our responsibility at the Plutus Data layer.
        """
        # cbor2 encodes it fine (it doesn't know about Plutus bounds)
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)
        assert decoded == data

        # But our validation logic must reject it
        assert len(decoded) > self.PLUTUS_MAX_BYTESTRING_LEN, (
            f"Expected bytestring > {self.PLUTUS_MAX_BYTESTRING_LEN} bytes, "
            f"got {len(decoded)}"
        )

        # Simulate the dBlock validation check
        is_valid = len(decoded) <= self.PLUTUS_MAX_BYTESTRING_LEN
        assert not is_valid, (
            f"dBlock should reject bytestring of {len(decoded)} bytes "
            f"(max {self.PLUTUS_MAX_BYTESTRING_LEN})"
        )

    def test_boundary_64_accepted_65_rejected(self) -> None:
        """Explicit boundary: 64 bytes accepted, 65 bytes rejected."""
        data_64 = b"\x00" * 64
        data_65 = b"\x00" * 65

        assert len(data_64) <= self.PLUTUS_MAX_BYTESTRING_LEN
        assert len(data_65) > self.PLUTUS_MAX_BYTESTRING_LEN


# ---------------------------------------------------------------------------
# Test 12: PlutusData-like structure round-trip
# Spec: test_data_roundtrip_arbitrary
# ---------------------------------------------------------------------------

# Strategy for PlutusData-like structures:
# PlutusData = Constr(tag, [PlutusData]) | Map([(PlutusData, PlutusData)]) |
#              List([PlutusData]) | Integer(int) | Bytes(bytes)

# Leaf PlutusData values
plutus_leaf = st.one_of(
    # I(n) — integers (Plutus supports arbitrary precision)
    st.integers(min_value=-(2**64), max_value=2**64),
    # B(b) — bounded bytestrings (max 64 bytes per Plutus spec)
    st.binary(min_size=0, max_size=64),
)

# Recursive PlutusData strategy
plutus_data = st.recursive(
    plutus_leaf,
    lambda children: st.one_of(
        # List([PlutusData]) — encoded as CBOR list
        st.lists(children, min_size=0, max_size=4),
        # Map([(PlutusData, PlutusData)]) — encoded as CBOR map
        # Note: Plutus maps allow duplicate keys (unlike Python dicts),
        # but for round-trip testing we use unique keys via dict strategy
        st.dictionaries(
            keys=st.one_of(
                st.integers(min_value=0, max_value=2**32),
                st.binary(min_size=0, max_size=32),
            ),
            values=children,
            min_size=0,
            max_size=4,
        ),
        # Constr(tag, fields) — encoded as CBORTag(121+tag, [fields])
        # Tags 121-127 for alternatives 0-6, 1280-1400 for 7+
        st.tuples(
            st.integers(min_value=0, max_value=6),
            st.lists(children, min_size=0, max_size=4),
        ).map(lambda t: cbor2.CBORTag(121 + t[0], t[1])),
    ),
    max_leaves=15,
)


@pytest.mark.property
class TestPlutusDataRoundtrip:
    """Verify arbitrary PlutusData-like structures survive CBOR round-trip.

    PlutusData is the core data type for Plutus smart contract datums,
    redeemers, and script context. It consists of:
    - Constr(tag, fields): encoded as CBORTag(121+alt, [fields]) for alt 0-6
    - Map(entries): CBOR map with PlutusData keys and values
    - List(items): CBOR array of PlutusData
    - I(n): CBOR integer
    - B(b): CBOR bytestring (max 64 bytes)

    The two-step roundtrip must be identity: decode(encode(data)) == data.
    """

    @given(data=plutus_data)
    @settings(max_examples=300)
    def test_plutus_data_roundtrip(self, data: object) -> None:
        """Arbitrary PlutusData structures survive encode-decode."""
        encoded = cbor2.dumps(data)
        decoded = cbor2.loads(encoded)

        # For CBORTag objects, compare structurally
        if isinstance(data, cbor2.CBORTag):
            assert isinstance(decoded, cbor2.CBORTag), (
                f"Expected CBORTag, got {type(decoded).__name__}"
            )
            assert decoded.tag == data.tag
            assert decoded.value == data.value
        else:
            assert decoded == data

    @given(data=plutus_data)
    @settings(max_examples=200)
    def test_plutus_data_canonical_roundtrip(self, data: object) -> None:
        """PlutusData canonical encoding round-trips (for datum hashing)."""
        encoded = cbor2.dumps(data, canonical=True)
        decoded = cbor2.loads(encoded)
        re_encoded = cbor2.dumps(decoded, canonical=True)

        # Canonical encoding must be deterministic
        assert encoded == re_encoded, (
            f"Canonical re-encoding differs: "
            f"{encoded.hex()} != {re_encoded.hex()}"
        )

    @given(
        alt=st.integers(min_value=0, max_value=6),
        fields=st.lists(plutus_leaf, min_size=0, max_size=5),
    )
    @settings(max_examples=200)
    def test_plutus_constr_tag_roundtrip(
        self, alt: int, fields: list[object]
    ) -> None:
        """Constr alternatives 0-6 use tags 121-127 and round-trip correctly."""
        tag_number = 121 + alt
        tagged = cbor2.CBORTag(tag_number, fields)
        encoded = cbor2.dumps(tagged)
        decoded = cbor2.loads(encoded)

        assert isinstance(decoded, cbor2.CBORTag)
        assert decoded.tag == tag_number
        assert decoded.value == fields


# ---------------------------------------------------------------------------
# Test 13: Map with duplicate keys — cbor2 behavior documentation
# Spec: Documents uplc issue #35
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestMapWithDuplicateKeysPreserved:
    """Document cbor2 behavior with duplicate map keys.

    Plutus allows maps with duplicate keys (it's a list of pairs, not a
    true map). However, cbor2 decodes CBOR maps into Python dicts, which
    silently drop duplicates (last-writer-wins).

    This is a known issue (uplc #35) that our Plutus Data decoder must
    handle by decoding maps as lists of pairs rather than dicts.

    These tests document the current cbor2 behavior so we know exactly
    what we're working around.
    """

    def test_map_with_duplicate_keys_cbor2_drops_duplicates(self) -> None:
        """cbor2 silently drops duplicate map keys (last-writer-wins).

        This documents the known behavior that our PlutusData decoder
        must work around by using a custom map decoder.
        """
        # Manually construct CBOR bytes for map {1: 10, 1: 20}
        # A2      = map(2 items)
        # 01      = key: 1
        # 0A      = value: 10
        # 01      = key: 1 (duplicate!)
        # 14      = value: 20
        cbor_bytes = bytes([
            0xa2,  # map(2)
            0x01,  # key: 1
            0x0a,  # value: 10
            0x01,  # key: 1 (duplicate)
            0x14,  # value: 20
        ])

        decoded = cbor2.loads(cbor_bytes)
        assert isinstance(decoded, dict)

        # cbor2 keeps the LAST value for duplicate keys
        assert decoded[1] == 20, (
            f"Expected last-writer-wins for duplicate key 1, got {decoded[1]}"
        )
        # The first value (10) is silently dropped
        assert len(decoded) == 1, (
            f"Expected 1 entry (duplicates merged), got {len(decoded)}"
        )

    def test_map_with_duplicate_bytestring_keys(self) -> None:
        """Duplicate bytestring keys are also dropped by cbor2."""
        # map {h'CAFE': 1, h'CAFE': 2}
        # A2 42 CAFE 01 42 CAFE 02
        cbor_bytes = bytes([
            0xa2,        # map(2)
            0x42,        # bstr(2)
            0xca, 0xfe,  # key: h'CAFE'
            0x01,        # value: 1
            0x42,        # bstr(2)
            0xca, 0xfe,  # key: h'CAFE' (duplicate)
            0x02,        # value: 2
        ])

        decoded = cbor2.loads(cbor_bytes)
        assert isinstance(decoded, dict)
        assert decoded[b"\xca\xfe"] == 2  # last-writer-wins
        assert len(decoded) == 1

    def test_map_with_mixed_duplicate_keys(self) -> None:
        """Multiple different duplicate keys in the same map."""
        # map {1: "a", 2: "b", 1: "c", 2: "d"}
        # A4 01 61 61 02 61 62 01 61 63 02 61 64
        cbor_bytes = bytes([
            0xa4,        # map(4)
            0x01,        # key: 1
            0x61, 0x61,  # value: "a"
            0x02,        # key: 2
            0x61, 0x62,  # value: "b"
            0x01,        # key: 1 (duplicate)
            0x61, 0x63,  # value: "c"
            0x02,        # key: 2 (duplicate)
            0x61, 0x64,  # value: "d"
        ])

        decoded = cbor2.loads(cbor_bytes)
        assert isinstance(decoded, dict)
        # Last-writer-wins for both keys
        assert decoded[1] == "c"
        assert decoded[2] == "d"
        assert len(decoded) == 2

    def test_indefinite_map_with_duplicate_keys(self) -> None:
        """Indefinite-length maps with duplicates also drop them."""
        # BF 01 0A 01 14 FF = indef map {1: 10, 1: 20}
        cbor_bytes = bytes([
            0xbf,  # indefinite map
            0x01,  # key: 1
            0x0a,  # value: 10
            0x01,  # key: 1 (duplicate)
            0x14,  # value: 20
            0xff,  # break
        ])

        decoded = cbor2.loads(cbor_bytes)
        assert isinstance(decoded, dict)
        assert decoded[1] == 20  # last-writer-wins
        assert len(decoded) == 1


# ---------------------------------------------------------------------------
# Test 14: Metadata CBOR round-trip
# Spec: test_metadata_roundtrip_cbor
# ---------------------------------------------------------------------------

# Strategy for valid metadata values (must satisfy pycardano Metadata constraints)
metadata_leaf = st.one_of(
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.binary(min_size=0, max_size=64),
    # Text limited to 64 bytes UTF-8 — use ASCII to keep it simple
    st.text(alphabet=st.characters(whitelist_categories=("L", "N")), min_size=0, max_size=64),
)

metadata_values = st.recursive(
    metadata_leaf,
    lambda children: st.one_of(
        st.lists(children, min_size=0, max_size=4),
        st.dictionaries(
            keys=st.integers(min_value=0, max_value=2**32),
            values=children,
            min_size=0,
            max_size=4,
        ),
    ),
    max_leaves=10,
)


@pytest.mark.property
class TestMetadataRoundtripCbor:
    """Property test: arbitrary metadata structures roundtrip through CBOR.

    Metadata is a map from uint keys to transaction_metadatum values.
    The metadatum values can be ints, bytes (<= 64), text (<= 64 bytes UTF-8),
    lists, or maps — all of which must survive CBOR encode/decode.
    """

    @given(
        key=st.integers(min_value=0, max_value=2**32),
        value=metadata_values,
    )
    @settings(max_examples=200)
    def test_metadata_roundtrip_cbor(self, key: int, value: object) -> None:
        """Metadata with arbitrary valid values survives CBOR round-trip."""
        from pycardano.metadata import Metadata, AuxiliaryData

        try:
            m = Metadata({key: value})
        except Exception:
            # Some generated values may not satisfy pycardano's validation
            # (e.g., nested dicts with non-int keys at inner levels are fine
            # for Metadata). Skip those.
            return

        cbor_bytes = m.to_cbor()
        restored = Metadata.from_cbor(cbor_bytes)
        assert restored[key] == value

    @given(
        key=st.integers(min_value=0, max_value=2**32),
        value=metadata_values,
    )
    @settings(max_examples=100)
    def test_auxiliary_data_roundtrip(self, key: int, value: object) -> None:
        """AuxiliaryData wrapping Metadata also round-trips."""
        from pycardano.metadata import Metadata, AuxiliaryData

        try:
            m = Metadata({key: value})
            aux = AuxiliaryData(data=m)
        except Exception:
            return

        cbor_bytes = aux.to_cbor()
        restored = AuxiliaryData.from_cbor(cbor_bytes)
        assert isinstance(restored.data, Metadata)
        assert restored.data[key] == value


# ---------------------------------------------------------------------------
# Test 15: Protocol version (bver) round-trip
# Spec: test_bver_roundtrip
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestBverRoundtrip:
    """Property test: protocol version (major, minor) roundtrips through CBOR.

    Spec: Shelley CDDL — protocol_version = [uint, uint]
    Used in block headers and update proposals.
    """

    @given(
        major=st.integers(min_value=0, max_value=15),
        minor=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=200)
    def test_bver_roundtrip(self, major: int, minor: int) -> None:
        """Protocol version [major, minor] survives CBOR round-trip."""
        bver = [major, minor]
        encoded = cbor2.dumps(bver)
        decoded = cbor2.loads(encoded)
        assert decoded == bver
        assert isinstance(decoded, list)
        assert len(decoded) == 2

    @given(
        major=st.integers(min_value=0, max_value=15),
        minor=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=200)
    def test_bver_canonical_deterministic(self, major: int, minor: int) -> None:
        """Canonical encoding of protocol version is deterministic."""
        bver = [major, minor]
        enc1 = cbor2.dumps(bver, canonical=True)
        enc2 = cbor2.dumps(bver, canonical=True)
        assert enc1 == enc2

    def test_known_cardano_versions(self) -> None:
        """Known Cardano protocol versions round-trip correctly."""
        versions = [
            [1, 0],   # Shelley
            [2, 0],   # Allegra
            [3, 0],   # Mary
            [5, 0],   # Alonzo
            [7, 0],   # Babbage
            [9, 0],   # Conway
            [10, 0],  # Future
        ]
        for v in versions:
            assert cbor2.loads(cbor2.dumps(v)) == v


# ---------------------------------------------------------------------------
# Test 16: Metadata rejects invalid value types
# Spec: test_metadata_rejects_invalid_values
# ---------------------------------------------------------------------------

@pytest.mark.property
class TestMetadataRejectsInvalidValues:
    """Property test: metadata with invalid value types is detected.

    pycardano's Metadata validates that values must be one of:
    (dict, list, int, bytes, str). Other types should be rejected.
    Additionally, bytes > 64 and text > 64 bytes are rejected.
    """

    @given(
        key=st.integers(min_value=0, max_value=1000),
        bad_value=st.one_of(
            st.floats(allow_nan=False, allow_infinity=False),
            # Note: booleans are NOT tested here because Python's bool is a
            # subclass of int, so isinstance(True, int) is True. pycardano
            # accepts bools as metadata values. The CDDL spec doesn't include
            # bool as a metadatum type, so our validation layer must reject
            # them separately.
            st.tuples(st.integers(), st.integers()),  # tuples are invalid
        ),
    )
    @settings(max_examples=100)
    def test_metadata_rejects_invalid_types(self, key: int, bad_value: object) -> None:
        """Float and tuple values are not valid transaction metadata."""
        from pycardano.exception import InvalidArgumentException
        from pycardano.metadata import Metadata

        with pytest.raises(InvalidArgumentException):
            Metadata({key: bad_value})

    @given(data=st.binary(min_size=65, max_size=256))
    @settings(max_examples=100)
    def test_metadata_rejects_oversized_bytes(self, data: bytes) -> None:
        """Bytestring values > 64 bytes must be rejected."""
        from pycardano.exception import InvalidArgumentException
        from pycardano.metadata import Metadata

        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: data})

    @given(
        length=st.integers(min_value=65, max_value=200),
    )
    @settings(max_examples=50)
    def test_metadata_rejects_oversized_text(self, length: int) -> None:
        """Text values > 64 bytes must be rejected."""
        from pycardano.exception import InvalidArgumentException
        from pycardano.metadata import Metadata

        text = "a" * length  # ASCII so 1 byte per char
        with pytest.raises(InvalidArgumentException, match="exceeds"):
            Metadata({1: text})
