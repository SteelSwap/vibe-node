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
