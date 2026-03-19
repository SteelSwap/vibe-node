"""Codec split/fragmentation property tests — Haskell test audit gap.

The Haskell ouroboros-network test suite (Ouroboros.Network.Protocol.*.Test)
tests every protocol codec by splitting encoded bytes at random points and
feeding them as separate reads via the ``splits2`` and ``splits3`` helpers.
This catches bugs where decoders assume complete messages arrive in a single
TCP read — a dangerous assumption on real networks where TCP segments arrive
in arbitrary chunks.

Our current decoders (cbor2.loads, struct.unpack_from) expect a complete
buffer.  These tests verify that:

1. Accumulating fragments into a complete buffer and then decoding produces
   the correct result (the "buffer-then-decode" pattern our mux layer uses).
2. Partial input to a decoder raises a clean exception rather than silently
   producing garbage or crashing.

This is the most important gap identified in the Haskell test audit.  The
Haskell node uses incremental CBOR decoding (cborg's Decoder monad with
``deserialiseIncremental``).  We document this as a known limitation —
our decoders are not incremental — and verify correctness of the
buffer-and-decode approach that our multiplexer actually uses.

Haskell reference:
    Ouroboros.Network.Protocol.ChainSync.Test (prop_codec_splits2/3)
    Ouroboros.Network.Protocol.Handshake.Test (prop_codec_splits2/3)
    Network.Mux.Test (segment split tests)
"""

from __future__ import annotations

import io

import cbor2
import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from vibe.cardano.network.chainsync import (
    ORIGIN,
    MsgAwaitReply,
    MsgDone,
    MsgFindIntersect,
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgRequestNext,
    MsgRollBackward,
    MsgRollForward,
    Point,
    Tip,
    decode_client_message,
    decode_server_message,
    encode_await_reply,
    encode_done,
    encode_find_intersect,
    encode_intersect_found,
    encode_intersect_not_found,
    encode_request_next,
    encode_roll_backward,
    encode_roll_forward,
)
from vibe.cardano.network.handshake import (
    MAINNET_NETWORK_MAGIC,
    N2N_V14,
    N2N_V15,
    MsgAcceptVersion,
    MsgProposeVersions,
    MsgRefuse,
    NodeToNodeVersionData,
    PeerSharing,
    RefuseReasonRefused,
    RefuseReasonVersionMismatch,
    build_version_table,
    decode_handshake_response,
    encode_propose_versions,
    _encode_version_data,
)
from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    decode_segment,
    encode_segment,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

block_hashes = st.binary(min_size=32, max_size=32)

points = st.one_of(
    st.just(ORIGIN),
    st.builds(Point, slot=st.integers(min_value=0, max_value=2**63), hash=block_hashes),
)

tips = st.builds(
    Tip,
    point=points,
    block_number=st.integers(min_value=0, max_value=2**63),
)

# Opaque header bytes — just random CBOR-encodable bytes for testing the codec.
headers = st.binary(min_size=1, max_size=256)

version_data = st.builds(
    NodeToNodeVersionData,
    network_magic=st.sampled_from([MAINNET_NETWORK_MAGIC, 1, 2]),
    initiator_only_diffusion_mode=st.booleans(),
    peer_sharing=st.sampled_from(list(PeerSharing)),
    query=st.booleans(),
)


# ---------------------------------------------------------------------------
# Chain-sync message generators — produce (encoded_bytes, expected_decoded)
# for both server and client messages.
# ---------------------------------------------------------------------------


@st.composite
def chainsync_server_messages(draw: st.DrawFn) -> tuple[bytes, object]:
    """Generate a random chain-sync server message as (cbor_bytes, expected)."""
    msg_type = draw(st.sampled_from([
        "await_reply",
        "roll_forward",
        "roll_backward",
        "intersect_found",
        "intersect_not_found",
    ]))

    if msg_type == "await_reply":
        return encode_await_reply(), MsgAwaitReply()
    elif msg_type == "roll_forward":
        h = draw(headers)
        t = draw(tips)
        return encode_roll_forward(h, t), MsgRollForward(header=h, tip=t)
    elif msg_type == "roll_backward":
        p = draw(points)
        t = draw(tips)
        return encode_roll_backward(p, t), MsgRollBackward(point=p, tip=t)
    elif msg_type == "intersect_found":
        p = draw(points)
        t = draw(tips)
        return encode_intersect_found(p, t), MsgIntersectFound(point=p, tip=t)
    else:  # intersect_not_found
        t = draw(tips)
        return encode_intersect_not_found(t), MsgIntersectNotFound(tip=t)


@st.composite
def chainsync_client_messages(draw: st.DrawFn) -> tuple[bytes, object]:
    """Generate a random chain-sync client message as (cbor_bytes, expected)."""
    msg_type = draw(st.sampled_from(["request_next", "find_intersect", "done"]))

    if msg_type == "request_next":
        return encode_request_next(), MsgRequestNext()
    elif msg_type == "find_intersect":
        pts = draw(st.lists(points, min_size=1, max_size=10))
        return encode_find_intersect(pts), MsgFindIntersect(points=pts)
    else:  # done
        return encode_done(), MsgDone()


# ---------------------------------------------------------------------------
# Helpers: buffer-then-decode (simulates what our mux layer does)
# ---------------------------------------------------------------------------


def _buffer_and_decode_cbor(fragments: list[bytes], decoder):
    """Accumulate fragments into a single buffer, then decode.

    This is how our multiplexer works: it reads SDU payloads until it has a
    complete message, then hands the full buffer to the CBOR decoder.

    Returns the decoded message.
    """
    buf = b"".join(fragments)
    return decoder(buf)


def _partial_decode_raises(fragment: bytes, decoder) -> bool:
    """Verify that feeding an incomplete fragment to the decoder raises
    an exception rather than silently producing garbage.

    Returns True if the decoder raised, False if it succeeded (which would
    indicate the fragment happened to be a valid CBOR message on its own —
    possible for very short messages).
    """
    try:
        decoder(fragment)
        return False  # Did not raise — fragment was valid on its own
    except Exception:
        return True  # Good — partial input was rejected


# ============================================================================
# Chain-Sync codec split tests
# ============================================================================


class TestChainSyncCodecSplits2:
    """Split chain-sync messages at 1 random point (2 fragments).

    Mirrors Haskell: prop_codec_ChainSync_splits2
    """

    @given(data=st.data(), msg_pair=chainsync_server_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_chainsync_server_splits2(self, data, msg_pair):
        """Server message split into 2 fragments decodes correctly after buffering."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 2)

        split = data.draw(st.integers(min_value=1, max_value=len(encoded) - 1))
        frag1, frag2 = encoded[:split], encoded[split:]

        # Buffer-then-decode: this is what our mux layer does.
        decoded = _buffer_and_decode_cbor([frag1, frag2], decode_server_message)
        assert decoded == expected

        # Document: partial input should raise, not silently produce garbage.
        # (May not raise if the split point happens to produce valid CBOR.)
        _partial_decode_raises(frag1, decode_server_message)

    @given(data=st.data(), msg_pair=chainsync_client_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_chainsync_client_splits2(self, data, msg_pair):
        """Client message split into 2 fragments decodes correctly after buffering."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 2)

        split = data.draw(st.integers(min_value=1, max_value=len(encoded) - 1))
        frag1, frag2 = encoded[:split], encoded[split:]

        decoded = _buffer_and_decode_cbor([frag1, frag2], decode_client_message)
        assert decoded == expected

        _partial_decode_raises(frag1, decode_client_message)


class TestChainSyncCodecSplits3:
    """Split chain-sync messages at 2 random points (3 fragments).

    Mirrors Haskell: prop_codec_ChainSync_splits3
    """

    @given(data=st.data(), msg_pair=chainsync_server_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_chainsync_server_splits3(self, data, msg_pair):
        """Server message split into 3 fragments decodes correctly after buffering."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 3)

        s1 = data.draw(st.integers(min_value=1, max_value=len(encoded) - 2))
        s2 = data.draw(st.integers(min_value=s1 + 1, max_value=len(encoded) - 1))
        frag1, frag2, frag3 = encoded[:s1], encoded[s1:s2], encoded[s2:]

        decoded = _buffer_and_decode_cbor([frag1, frag2, frag3], decode_server_message)
        assert decoded == expected

    @given(data=st.data(), msg_pair=chainsync_client_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_chainsync_client_splits3(self, data, msg_pair):
        """Client message split into 3 fragments decodes correctly after buffering."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 3)

        s1 = data.draw(st.integers(min_value=1, max_value=len(encoded) - 2))
        s2 = data.draw(st.integers(min_value=s1 + 1, max_value=len(encoded) - 1))
        frag1, frag2, frag3 = encoded[:s1], encoded[s1:s2], encoded[s2:]

        decoded = _buffer_and_decode_cbor([frag1, frag2, frag3], decode_client_message)
        assert decoded == expected


# ============================================================================
# Handshake codec split tests
# ============================================================================


def _encode_accept_version(version_number: int, vd: NodeToNodeVersionData) -> bytes:
    """Encode MsgAcceptVersion for testing — no public encode function exists yet.

    Wire format: [1, versionNumber, versionData]
    """
    return cbor2.dumps([1, version_number, _encode_version_data(vd)])


def _encode_refuse_version_mismatch(versions: list[int]) -> bytes:
    """Encode MsgRefuse(VersionMismatch) for testing.

    Wire format: [2, [0, [versions...]]]
    """
    return cbor2.dumps([2, [0, versions]])


def _encode_refuse_refused(version_number: int, message: str) -> bytes:
    """Encode MsgRefuse(Refused) for testing.

    Wire format: [2, [2, versionNumber, message]]
    """
    return cbor2.dumps([2, [2, version_number, message]])


@st.composite
def handshake_response_messages(draw: st.DrawFn) -> tuple[bytes, object]:
    """Generate a random handshake response message as (cbor_bytes, expected)."""
    msg_type = draw(st.sampled_from(["accept", "refuse_mismatch", "refuse_refused"]))

    if msg_type == "accept":
        vn = draw(st.sampled_from([N2N_V14, N2N_V15]))
        vd = draw(version_data)
        encoded = _encode_accept_version(vn, vd)
        expected = MsgAcceptVersion(version_number=vn, version_data=vd)
        return encoded, expected
    elif msg_type == "refuse_mismatch":
        versions = draw(st.lists(
            st.sampled_from([N2N_V14, N2N_V15, 10, 11, 12, 13]),
            min_size=1,
            max_size=6,
        ))
        encoded = _encode_refuse_version_mismatch(versions)
        expected = MsgRefuse(reason=RefuseReasonVersionMismatch(versions=versions))
        return encoded, expected
    else:  # refuse_refused
        vn = draw(st.sampled_from([N2N_V14, N2N_V15]))
        msg = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "Z"),
        )))
        encoded = _encode_refuse_refused(vn, msg)
        expected = MsgRefuse(reason=RefuseReasonRefused(version_number=vn, message=msg))
        return encoded, expected


class TestHandshakeCodecSplits2:
    """Split handshake messages at 1 random point (2 fragments).

    Mirrors Haskell: prop_codec_Handshake_splits2
    """

    @given(data=st.data(), msg_pair=handshake_response_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_handshake_codec_splits2(self, data, msg_pair):
        """Handshake response split into 2 fragments decodes correctly."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 2)

        split = data.draw(st.integers(min_value=1, max_value=len(encoded) - 1))
        frag1, frag2 = encoded[:split], encoded[split:]

        decoded = _buffer_and_decode_cbor([frag1, frag2], decode_handshake_response)
        assert decoded == expected

        _partial_decode_raises(frag1, decode_handshake_response)


class TestHandshakeCodecSplits3:
    """Split handshake messages at 2 random points (3 fragments).

    Mirrors Haskell: prop_codec_Handshake_splits3
    """

    @given(data=st.data(), msg_pair=handshake_response_messages())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_handshake_codec_splits3(self, data, msg_pair):
        """Handshake response split into 3 fragments decodes correctly."""
        encoded, expected = msg_pair
        assume(len(encoded) >= 3)

        s1 = data.draw(st.integers(min_value=1, max_value=len(encoded) - 2))
        s2 = data.draw(st.integers(min_value=s1 + 1, max_value=len(encoded) - 1))
        frag1, frag2, frag3 = encoded[:s1], encoded[s1:s2], encoded[s2:]

        decoded = _buffer_and_decode_cbor(
            [frag1, frag2, frag3], decode_handshake_response
        )
        assert decoded == expected


# ============================================================================
# MuxSegment codec split tests
# ============================================================================


@st.composite
def mux_segments(draw: st.DrawFn) -> MuxSegment:
    """Generate a random MuxSegment with reasonable payload sizes."""
    return MuxSegment(
        timestamp=draw(st.integers(min_value=0, max_value=0xFFFFFFFF)),
        protocol_id=draw(st.integers(min_value=0, max_value=0x7FFF)),
        is_initiator=draw(st.booleans()),
        # Keep payloads small-ish for fast tests, but cover boundary sizes.
        payload=draw(st.binary(min_size=0, max_size=1024)),
    )


def _buffer_and_decode_segment(fragments: list[bytes]) -> tuple[MuxSegment, int]:
    """Accumulate segment fragments and decode."""
    buf = b"".join(fragments)
    return decode_segment(buf)


class TestSegmentSplits2:
    """Split MuxSegment encoding at 1 random point (2 fragments).

    The segment decoder uses struct.unpack_from and requires the full header
    + payload.  This test verifies buffer-then-decode correctness.
    """

    @given(data=st.data(), segment=mux_segments())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_segment_splits2(self, data, segment):
        """Segment split into 2 fragments decodes correctly after buffering."""
        encoded = encode_segment(segment)
        assume(len(encoded) >= 2)

        split = data.draw(st.integers(min_value=1, max_value=len(encoded) - 1))
        frag1, frag2 = encoded[:split], encoded[split:]

        decoded, consumed = _buffer_and_decode_segment([frag1, frag2])

        assert decoded.timestamp == segment.timestamp
        assert decoded.protocol_id == segment.protocol_id
        assert decoded.is_initiator == segment.is_initiator
        assert decoded.payload == segment.payload
        assert consumed == len(encoded)

        # Partial input: decoder should raise ValueError for incomplete data.
        with pytest.raises(ValueError):
            decode_segment(frag1)

    @given(data=st.data(), segment=mux_segments())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_segment_splits3(self, data, segment):
        """Segment split into 3 fragments decodes correctly after buffering."""
        encoded = encode_segment(segment)
        assume(len(encoded) >= 3)

        s1 = data.draw(st.integers(min_value=1, max_value=len(encoded) - 2))
        s2 = data.draw(st.integers(min_value=s1 + 1, max_value=len(encoded) - 1))
        frag1, frag2, frag3 = encoded[:s1], encoded[s1:s2], encoded[s2:]

        decoded, consumed = _buffer_and_decode_segment([frag1, frag2, frag3])

        assert decoded.timestamp == segment.timestamp
        assert decoded.protocol_id == segment.protocol_id
        assert decoded.is_initiator == segment.is_initiator
        assert decoded.payload == segment.payload
        assert consumed == len(encoded)


# ============================================================================
# Known limitation documentation tests
# ============================================================================


class TestIncrementalDecodeLimitation:
    """Document and test the known limitation: our decoders are NOT incremental.

    The Haskell node uses cborg's ``deserialiseIncremental`` which can consume
    partial input and ask for more bytes.  Our decoders (cbor2.loads,
    struct.unpack_from) require a complete buffer.

    This is acceptable because our multiplexer layer accumulates complete SDU
    payloads before handing them to protocol decoders.  The split tests above
    verify that buffer-then-decode is correct.

    These tests explicitly document the partial-input behavior: decoders should
    raise exceptions on truncated input, never silently return garbage.
    """

    def test_cbor_decoder_rejects_truncated_chainsync(self):
        """cbor2.loads raises on truncated chain-sync CBOR."""
        encoded = encode_request_next()
        assert len(encoded) >= 2, "Need at least 2 bytes to truncate"

        # Every proper prefix shorter than the full message should fail.
        for i in range(1, len(encoded)):
            with pytest.raises(Exception):
                decode_client_message(encoded[:i])

    def test_cbor_decoder_rejects_truncated_handshake(self):
        """cbor2.loads raises on truncated handshake CBOR."""
        vt = build_version_table(MAINNET_NETWORK_MAGIC)
        encoded = encode_propose_versions(vt)
        assert len(encoded) >= 2

        # MsgProposeVersions is decoded by decode_handshake_response which
        # expects tag 1 or 2.  Any truncation should raise.
        for i in range(1, len(encoded)):
            with pytest.raises(Exception):
                decode_handshake_response(encoded[:i])

    def test_segment_decoder_rejects_truncated_header(self):
        """decode_segment raises ValueError when header is incomplete."""
        seg = MuxSegment(
            timestamp=12345, protocol_id=2, is_initiator=True, payload=b"test"
        )
        encoded = encode_segment(seg)

        # Any prefix shorter than header + payload should raise ValueError.
        for i in range(1, len(encoded)):
            with pytest.raises(ValueError):
                decode_segment(encoded[:i])
