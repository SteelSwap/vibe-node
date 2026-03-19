"""Tests for Chain-Sync miniprotocol CBOR message codec.

Covers encode/decode roundtrips, known CBOR byte vectors, point/tip
encoding, and message ID correctness.

Derived from test specifications:
- test_server_agency_after_request_next
- test_server_agency_after_find_intersect
- test_request_next_always_gets_one_of_three_responses
- test_msg_request_next_roll_forward_response
- test_msg_request_next_roll_backward_response
- test_n2n_chainsync_block_roundtrip
- test_chain_sync_message_within_limit

Spec reference: ouroboros-network, Network.Protocol.ChainSync.Codec
"""

from __future__ import annotations

import cbor2
import pytest

from vibe.cardano.network.chainsync import (
    CHAIN_SYNC_N2C_ID,
    CHAIN_SYNC_N2N_ID,
    MSG_AWAIT_REPLY,
    MSG_DONE,
    MSG_FIND_INTERSECT,
    MSG_INTERSECT_FOUND,
    MSG_INTERSECT_NOT_FOUND,
    MSG_REQUEST_NEXT,
    MSG_ROLL_BACKWARD,
    MSG_ROLL_FORWARD,
    ORIGIN,
    MsgAwaitReply,
    MsgDone,
    MsgFindIntersect,
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgRequestNext,
    MsgRollBackward,
    MsgRollForward,
    Origin,
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


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

HASH_32 = b"\xab" * 32  # Deterministic 32-byte hash for tests
HASH_32_ALT = b"\xcd" * 32

SAMPLE_POINT = Point(slot=42, hash=HASH_32)
SAMPLE_POINT_ALT = Point(slot=1000, hash=HASH_32_ALT)
SAMPLE_TIP = Tip(point=SAMPLE_POINT, block_number=100)
SAMPLE_TIP_ORIGIN = Tip(point=ORIGIN, block_number=0)
SAMPLE_HEADER = b"\xde\xad\xbe\xef"


# ---------------------------------------------------------------------------
# Message ID constants
# ---------------------------------------------------------------------------


class TestMessageIDs:
    """Verify message ID constants match the CBOR array index 0."""

    def test_request_next_id(self) -> None:
        assert MSG_REQUEST_NEXT == 0

    def test_await_reply_id(self) -> None:
        assert MSG_AWAIT_REPLY == 1

    def test_roll_forward_id(self) -> None:
        assert MSG_ROLL_FORWARD == 2

    def test_roll_backward_id(self) -> None:
        assert MSG_ROLL_BACKWARD == 3

    def test_find_intersect_id(self) -> None:
        assert MSG_FIND_INTERSECT == 4

    def test_intersect_found_id(self) -> None:
        assert MSG_INTERSECT_FOUND == 5

    def test_intersect_not_found_id(self) -> None:
        assert MSG_INTERSECT_NOT_FOUND == 6

    def test_done_id(self) -> None:
        assert MSG_DONE == 7

    def test_miniprotocol_n2n_id(self) -> None:
        """Chain-sync is miniprotocol ID 2 for node-to-node."""
        assert CHAIN_SYNC_N2N_ID == 2

    def test_miniprotocol_n2c_id(self) -> None:
        """Chain-sync is miniprotocol ID 5 for node-to-client."""
        assert CHAIN_SYNC_N2C_ID == 5


# ---------------------------------------------------------------------------
# Dataclass message IDs
# ---------------------------------------------------------------------------


class TestDataclassMessageIDs:
    """Each dataclass exposes its msg_id matching the constant."""

    def test_request_next(self) -> None:
        assert MsgRequestNext().msg_id == MSG_REQUEST_NEXT

    def test_await_reply(self) -> None:
        assert MsgAwaitReply().msg_id == MSG_AWAIT_REPLY

    def test_roll_forward(self) -> None:
        msg = MsgRollForward(header=SAMPLE_HEADER, tip=SAMPLE_TIP)
        assert msg.msg_id == MSG_ROLL_FORWARD

    def test_roll_backward(self) -> None:
        msg = MsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.msg_id == MSG_ROLL_BACKWARD

    def test_find_intersect(self) -> None:
        msg = MsgFindIntersect(points=[SAMPLE_POINT])
        assert msg.msg_id == MSG_FIND_INTERSECT

    def test_intersect_found(self) -> None:
        msg = MsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.msg_id == MSG_INTERSECT_FOUND

    def test_intersect_not_found(self) -> None:
        msg = MsgIntersectNotFound(tip=SAMPLE_TIP)
        assert msg.msg_id == MSG_INTERSECT_NOT_FOUND

    def test_done(self) -> None:
        assert MsgDone().msg_id == MSG_DONE


# ---------------------------------------------------------------------------
# Point encoding
# ---------------------------------------------------------------------------


class TestPointEncoding:
    """Test CBOR encoding of Point and Origin."""

    def test_origin_singleton(self) -> None:
        """Origin is a singleton."""
        assert Origin() is Origin()
        assert Origin() is ORIGIN

    def test_origin_equality(self) -> None:
        assert Origin() == ORIGIN
        assert hash(Origin()) == hash(ORIGIN)

    def test_origin_repr(self) -> None:
        assert repr(ORIGIN) == "Origin"

    def test_point_repr(self) -> None:
        p = Point(slot=42, hash=b"\x00" * 32)
        r = repr(p)
        assert "slot=42" in r
        assert "hash=" in r

    def test_point_frozen(self) -> None:
        """Points are immutable (frozen dataclass)."""
        p = Point(slot=42, hash=HASH_32)
        with pytest.raises(AttributeError):
            p.slot = 99  # type: ignore[misc]

    def test_point_hashable(self) -> None:
        """Points can be used in sets/dicts."""
        s = {SAMPLE_POINT, SAMPLE_POINT_ALT}
        assert len(s) == 2
        assert SAMPLE_POINT in s


# ---------------------------------------------------------------------------
# Known CBOR byte vectors
# ---------------------------------------------------------------------------


class TestKnownCBORVectors:
    """Verify exact CBOR byte output for known inputs.

    These are derived from the CBOR specification:
    - 0x81 = array(1), 0x82 = array(2), 0x83 = array(3), 0x80 = array(0)
    - Small ints 0-23 are single bytes 0x00-0x17
    """

    def test_request_next_bytes(self) -> None:
        """MsgRequestNext encodes as CBOR [0] = 0x81 0x00."""
        raw = encode_request_next()
        assert raw == bytes([0x81, 0x00])

    def test_done_bytes(self) -> None:
        """MsgDone encodes as CBOR [7] = 0x81 0x07."""
        raw = encode_done()
        assert raw == bytes([0x81, 0x07])

    def test_await_reply_bytes(self) -> None:
        """MsgAwaitReply encodes as CBOR [1] = 0x81 0x01."""
        raw = encode_await_reply()
        assert raw == bytes([0x81, 0x01])

    def test_find_intersect_empty_points(self) -> None:
        """MsgFindIntersect with no points: [4, []] = 0x82 0x04 0x80."""
        raw = encode_find_intersect([])
        assert raw == bytes([0x82, 0x04, 0x80])

    def test_find_intersect_origin_point(self) -> None:
        """MsgFindIntersect with origin: [4, [[]]] = 0x82 0x04 0x81 0x80."""
        raw = encode_find_intersect([ORIGIN])
        assert raw == bytes([0x82, 0x04, 0x81, 0x80])

    def test_request_next_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [0]."""
        parsed = cbor2.loads(encode_request_next())
        assert parsed == [0]

    def test_done_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [7]."""
        parsed = cbor2.loads(encode_done())
        assert parsed == [7]

    def test_find_intersect_cbor_structure(self) -> None:
        """Decoded CBOR for FindIntersect has correct array nesting."""
        raw = encode_find_intersect([SAMPLE_POINT, ORIGIN])
        parsed = cbor2.loads(raw)
        assert parsed[0] == 4
        assert len(parsed[1]) == 2
        assert parsed[1][0] == [42, HASH_32]
        assert parsed[1][1] == []

    def test_roll_forward_cbor_structure(self) -> None:
        """Decoded CBOR for RollForward has [2, header, [point, blockno]]."""
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 2
        assert parsed[1] == SAMPLE_HEADER
        # Tip is [point, block_number]
        tip_raw = parsed[2]
        assert tip_raw[0] == [42, HASH_32]  # point
        assert tip_raw[1] == 100  # block_number

    def test_roll_backward_cbor_structure(self) -> None:
        """Decoded CBOR for RollBackward has [3, point, [point, blockno]]."""
        raw = encode_roll_backward(SAMPLE_POINT, SAMPLE_TIP)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 3
        assert parsed[1] == [42, HASH_32]
        assert parsed[2][0] == [42, HASH_32]
        assert parsed[2][1] == 100

    def test_intersect_found_cbor_structure(self) -> None:
        """Decoded CBOR for IntersectFound has [5, point, tip]."""
        raw = encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 5
        assert parsed[1] == [42, HASH_32]

    def test_intersect_not_found_cbor_structure(self) -> None:
        """Decoded CBOR for IntersectNotFound has [6, tip]."""
        raw = encode_intersect_not_found(SAMPLE_TIP)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 6
        assert parsed[1][0] == [42, HASH_32]
        assert parsed[1][1] == 100

    def test_roll_backward_origin_point(self) -> None:
        """RollBackward with origin point: point encodes as []."""
        raw = encode_roll_backward(ORIGIN, SAMPLE_TIP_ORIGIN)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 3
        assert parsed[1] == []  # origin
        assert parsed[2][0] == []  # tip point is also origin
        assert parsed[2][1] == 0  # genesis block number


# ---------------------------------------------------------------------------
# Tip encoding
# ---------------------------------------------------------------------------


class TestTipEncoding:
    """Test CBOR encoding of Tip (via roundtrip through messages)."""

    def test_tip_with_block_point(self) -> None:
        """Tip with a concrete point encodes as [[slot, hash], blockno]."""
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)
        assert msg.tip.point == SAMPLE_POINT
        assert msg.tip.block_number == 100

    def test_tip_with_origin(self) -> None:
        """Tip at genesis encodes as [[], 0]."""
        tip = Tip(point=ORIGIN, block_number=0)
        raw = encode_roll_forward(SAMPLE_HEADER, tip)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)
        assert msg.tip.point == ORIGIN
        assert msg.tip.block_number == 0

    def test_tip_frozen(self) -> None:
        """Tips are immutable (frozen dataclass)."""
        with pytest.raises(AttributeError):
            SAMPLE_TIP.block_number = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Encode/decode roundtrip — client messages
# ---------------------------------------------------------------------------


class TestClientMessageRoundtrip:
    """Encode then decode client messages and verify fidelity."""

    def test_request_next_roundtrip(self) -> None:
        raw = encode_request_next()
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgRequestNext)
        assert msg.msg_id == MSG_REQUEST_NEXT

    def test_find_intersect_roundtrip_empty(self) -> None:
        raw = encode_find_intersect([])
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgFindIntersect)
        assert msg.points == []

    def test_find_intersect_roundtrip_single_point(self) -> None:
        raw = encode_find_intersect([SAMPLE_POINT])
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgFindIntersect)
        assert len(msg.points) == 1
        assert msg.points[0] == SAMPLE_POINT

    def test_find_intersect_roundtrip_multiple_points(self) -> None:
        points = [SAMPLE_POINT, SAMPLE_POINT_ALT, ORIGIN]
        raw = encode_find_intersect(points)
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgFindIntersect)
        assert len(msg.points) == 3
        assert msg.points[0] == SAMPLE_POINT
        assert msg.points[1] == SAMPLE_POINT_ALT
        assert msg.points[2] == ORIGIN

    def test_find_intersect_roundtrip_origin_only(self) -> None:
        raw = encode_find_intersect([ORIGIN])
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgFindIntersect)
        assert len(msg.points) == 1
        assert msg.points[0] is ORIGIN

    def test_done_roundtrip(self) -> None:
        raw = encode_done()
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgDone)
        assert msg.msg_id == MSG_DONE


# ---------------------------------------------------------------------------
# Encode/decode roundtrip — server messages
# ---------------------------------------------------------------------------


class TestServerMessageRoundtrip:
    """Encode then decode server messages and verify fidelity."""

    def test_await_reply_roundtrip(self) -> None:
        raw = encode_await_reply()
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgAwaitReply)

    def test_roll_forward_roundtrip(self) -> None:
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)
        assert msg.header == SAMPLE_HEADER
        assert msg.tip == SAMPLE_TIP

    def test_roll_forward_large_header(self) -> None:
        """RollForward with a realistically-sized header (1400 bytes)."""
        header = b"\x42" * 1400
        raw = encode_roll_forward(header, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)
        assert msg.header == header
        assert msg.tip == SAMPLE_TIP

    def test_roll_forward_origin_tip(self) -> None:
        """RollForward with genesis tip."""
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP_ORIGIN)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)
        assert msg.tip.point == ORIGIN
        assert msg.tip.block_number == 0

    def test_roll_backward_roundtrip(self) -> None:
        raw = encode_roll_backward(SAMPLE_POINT, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollBackward)
        assert msg.point == SAMPLE_POINT
        assert msg.tip == SAMPLE_TIP

    def test_roll_backward_to_origin(self) -> None:
        """RollBackward to genesis."""
        raw = encode_roll_backward(ORIGIN, SAMPLE_TIP_ORIGIN)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollBackward)
        assert msg.point == ORIGIN
        assert msg.tip.point == ORIGIN
        assert msg.tip.block_number == 0

    def test_intersect_found_roundtrip(self) -> None:
        raw = encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgIntersectFound)
        assert msg.point == SAMPLE_POINT
        assert msg.tip == SAMPLE_TIP

    def test_intersect_found_origin(self) -> None:
        """IntersectFound at origin."""
        raw = encode_intersect_found(ORIGIN, SAMPLE_TIP_ORIGIN)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgIntersectFound)
        assert msg.point == ORIGIN

    def test_intersect_not_found_roundtrip(self) -> None:
        raw = encode_intersect_not_found(SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgIntersectNotFound)
        assert msg.tip == SAMPLE_TIP


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestDecodeErrors:
    """Verify error handling for malformed messages."""

    def test_decode_server_unknown_msg_id(self) -> None:
        raw = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_decode_server_not_a_list(self) -> None:
        raw = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(raw)

    def test_decode_server_empty_list(self) -> None:
        raw = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(raw)

    def test_decode_client_unknown_msg_id(self) -> None:
        raw = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_decode_client_not_a_list(self) -> None:
        raw = cbor2.dumps("hello")
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_client_message(raw)

    def test_decode_roll_forward_wrong_length(self) -> None:
        """MsgRollForward with wrong number of elements."""
        raw = cbor2.dumps([2, b"\xde\xad"])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_server_message(raw)

    def test_decode_roll_backward_wrong_length(self) -> None:
        raw = cbor2.dumps([3, [42, HASH_32]])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_server_message(raw)

    def test_decode_intersect_found_wrong_length(self) -> None:
        raw = cbor2.dumps([5, [42, HASH_32]])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_server_message(raw)

    def test_decode_intersect_not_found_wrong_length(self) -> None:
        raw = cbor2.dumps([6])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_server_message(raw)

    def test_decode_await_reply_wrong_length(self) -> None:
        raw = cbor2.dumps([1, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_server_message(raw)

    def test_decode_request_next_wrong_length(self) -> None:
        raw = cbor2.dumps([0, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_client_message(raw)

    def test_decode_done_wrong_length(self) -> None:
        raw = cbor2.dumps([7, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_client_message(raw)

    def test_invalid_point_length(self) -> None:
        """A point with 1 element is invalid (must be 0 or 2)."""
        raw = cbor2.dumps([3, [42], [[], 0]])
        with pytest.raises(ValueError, match="Invalid point encoding"):
            decode_server_message(raw)

    def test_invalid_tip_length(self) -> None:
        """A tip with wrong number of elements."""
        raw = cbor2.dumps([2, b"\xde\xad", [[], 0, "extra"]])
        with pytest.raises(ValueError, match="Invalid tip encoding"):
            decode_server_message(raw)


# ---------------------------------------------------------------------------
# Cross-decode: client encodes, server decodes (and vice versa)
# ---------------------------------------------------------------------------


class TestCrossDecode:
    """Client messages decoded by server decoder should fail (wrong IDs)."""

    def test_server_decoder_rejects_request_next(self) -> None:
        """Server decoder should reject MsgRequestNext (client message)."""
        raw = encode_request_next()
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_server_decoder_rejects_done(self) -> None:
        raw = encode_done()
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_server_decoder_rejects_find_intersect(self) -> None:
        raw = encode_find_intersect([SAMPLE_POINT])
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_client_decoder_rejects_await_reply(self) -> None:
        raw = encode_await_reply()
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_client_decoder_rejects_roll_forward(self) -> None:
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP)
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)


# ---------------------------------------------------------------------------
# Spec conformance: response types after MsgRequestNext
# ---------------------------------------------------------------------------


class TestRequestNextResponses:
    """After MsgRequestNext, only three server responses are valid:
    MsgRollForward, MsgRollBackward, or MsgAwaitReply.

    From test spec: test_request_next_always_gets_one_of_three_responses
    """

    def test_roll_forward_is_valid_response(self) -> None:
        raw = encode_roll_forward(SAMPLE_HEADER, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollForward)

    def test_roll_backward_is_valid_response(self) -> None:
        raw = encode_roll_backward(SAMPLE_POINT, SAMPLE_TIP)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgRollBackward)

    def test_await_reply_is_valid_response(self) -> None:
        raw = encode_await_reply()
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgAwaitReply)


# ---------------------------------------------------------------------------
# Message size conformance
# ---------------------------------------------------------------------------


class TestMessageSize:
    """From test spec: test_chain_sync_message_within_limit

    A RollForward with max header size (1400 bytes) should produce a
    serialized message within reasonable bounds.
    """

    def test_roll_forward_max_header_fits(self) -> None:
        """A 1400-byte header in RollForward should serialize under 2KB."""
        header = b"\x42" * 1400
        raw = encode_roll_forward(header, SAMPLE_TIP)
        # Overhead: msg_id + tip encoding ~ tens of bytes.
        # Total should be well under 2000 bytes.
        assert len(raw) < 2000
        # But it must include the full header
        assert len(raw) > 1400
