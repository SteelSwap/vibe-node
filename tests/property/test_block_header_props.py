"""Property-based tests for block header hashing invariants.

These tests use Hypothesis to verify that block_hash satisfies critical
properties across arbitrary inputs:
  - Determinism: same input always produces same output
  - Fixed output size: always 32 bytes (Blake2b-256)
  - Stability: re-computation on the same CBOR yields identical results

Spec reference: block hash = Blake2b-256(header_cbor), used as the
canonical block identifier for chain-sync, block-fetch, and prev_hash.

Structured for Antithesis compatibility: deterministic given the same
seed, with property invariants expressible as assertions.
"""

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.serialization.block import (
    Era,
    block_hash,
    decode_block_header,
)

# Mark all tests in this module as property tests
pytestmark = pytest.mark.property


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary byte strings in the range that could plausibly be header CBOR
_arbitrary_bytes = st.binary(min_size=32, max_size=500)

# Dummy values for constructing valid header CBOR
_hash32 = b"\xab" * 32
_sig64 = b"\xcd" * 64
_vkey32 = b"\xef" * 32
_vrf_cert = [b"\x01" * 32, b"\x02" * 80]


def _make_header_cbor(
    slot: int = 1000,
    block_number: int = 42,
    body_size: int = 512,
) -> bytes:
    """Build a valid Babbage-era header CBOR for property testing."""
    header_body = [
        block_number,
        slot,
        _hash32,  # prev_hash
        _vkey32,  # issuer_vkey
        _vkey32,  # vrf_vkey
        _vrf_cert,  # vrf_result
        body_size,
        _hash32,  # block_body_hash
        _vkey32,  # op_cert hot_vkey
        7,  # op_cert sequence_number
        100,  # op_cert kes_period
        _sig64,  # op_cert sigma
        7,  # protocol_version major
        0,  # protocol_version minor
    ]
    header = [header_body, _sig64]
    return cbor2.dumps(header)


def _wrap_tagged_block(era_tag: int, block_payload: list) -> bytes:
    """Manually encode a CBOR-tagged block (same as test_block_header helper)."""
    tag_byte = bytes([0xC0 | era_tag])
    payload_cbor = cbor2.dumps(block_payload)
    return tag_byte + payload_cbor


# ---------------------------------------------------------------------------
# Property: block_hash is deterministic
# ---------------------------------------------------------------------------


class TestBlockHashDeterministicProperty:
    """block_hash must be a pure function: same input, same output, every time."""

    @given(data=_arbitrary_bytes)
    @settings(max_examples=200)
    def test_block_hash_deterministic_property(self, data: bytes):
        """For arbitrary bytes(32-500), block_hash always produces the same
        32-byte output for the same input.

        This is a critical consensus invariant: if two nodes compute different
        hashes for the same header bytes, they will disagree on the chain.
        """
        h1 = block_hash(data)
        h2 = block_hash(data)

        # Same input must produce identical output
        assert h1 == h2, (
            f"block_hash produced different results for same input: "
            f"{h1.hex()} != {h2.hex()}"
        )

        # Output must always be exactly 32 bytes
        assert len(h1) == 32, (
            f"block_hash produced {len(h1)} bytes, expected 32"
        )

        # Output must be bytes
        assert isinstance(h1, bytes)


# ---------------------------------------------------------------------------
# Property: roundtrip hash stability
# ---------------------------------------------------------------------------


class TestRoundtripHashStability:
    """For any valid header CBOR, block_hash is deterministic and stable
    across re-computation."""

    @given(
        slot=st.integers(min_value=0, max_value=2**32 - 1),
        block_number=st.integers(min_value=0, max_value=2**32 - 1),
        body_size=st.integers(min_value=0, max_value=2**32 - 1),
    )
    @settings(max_examples=100)
    def test_roundtrip_hash_stability(
        self, slot: int, block_number: int, body_size: int
    ):
        """For any valid header CBOR, block_hash(header) is deterministic
        and stable across re-computation.

        This test constructs valid Babbage-era headers with Hypothesis-generated
        field values, encodes them to CBOR, and verifies that:
          1. block_hash produces the same digest on repeated calls
          2. Decoding the full block and accessing .hash gives the same result
          3. The hash is always exactly 32 bytes

        This guards against non-determinism in CBOR encoding (map ordering,
        float representation, etc.) that could cause hash instability.
        """
        header_cbor = _make_header_cbor(
            slot=slot,
            block_number=block_number,
            body_size=body_size,
        )

        # Direct hash computation must be stable
        h1 = block_hash(header_cbor)
        h2 = block_hash(header_cbor)
        assert h1 == h2

        # Build a full tagged block and decode it
        header_body_and_sig = cbor2.loads(header_cbor)
        block_payload = [header_body_and_sig, [], [], {}]
        full_block = _wrap_tagged_block(Era.BABBAGE, block_payload)

        decoded = decode_block_header(full_block)

        # The decoded header's .hash property must match
        assert decoded.hash == block_hash(decoded.header_cbor)
        assert len(decoded.hash) == 32

        # Verify decoded fields match what we put in
        assert decoded.slot == slot
        assert decoded.block_number == block_number
        assert decoded.block_body_size == body_size
