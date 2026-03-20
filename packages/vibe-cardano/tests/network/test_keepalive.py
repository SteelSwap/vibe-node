"""Tests for keep-alive miniprotocol CBOR message types and codec.

Tests cover:
- Message construction and field access
- CBOR encoding produces expected wire format
- CBOR decoding recovers the original message
- Round-trip property: decode(encode(msg)) == msg for all message types
- Edge cases: cookie boundaries (0, 65535), invalid cookies, malformed CBOR
- Hypothesis property tests for CBOR round-trip with arbitrary uint16 cookies
"""

from __future__ import annotations

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.keepalive import (
    COOKIE_MAX,
    COOKIE_MIN,
    KEEP_ALIVE_PROTOCOL_ID,
    MsgDone,
    MsgKeepAlive,
    MsgKeepAliveResponse,
    decode_client_message,
    decode_message,
    decode_server_message,
    encode_done,
    encode_keep_alive,
    encode_keep_alive_response,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify protocol constants match the spec."""

    def test_protocol_id(self) -> None:
        assert KEEP_ALIVE_PROTOCOL_ID == 8

    def test_cookie_range(self) -> None:
        assert COOKIE_MIN == 0
        assert COOKIE_MAX == 0xFFFF


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMsgKeepAlive:
    """MsgKeepAlive message construction and fields."""

    def test_construction(self) -> None:
        msg = MsgKeepAlive(cookie=42)
        assert msg.cookie == 42
        assert msg.msg_id == 0

    def test_frozen(self) -> None:
        msg = MsgKeepAlive(cookie=42)
        with pytest.raises(AttributeError):
            msg.cookie = 99  # type: ignore[misc]

    def test_equality(self) -> None:
        assert MsgKeepAlive(cookie=42) == MsgKeepAlive(cookie=42)
        assert MsgKeepAlive(cookie=42) != MsgKeepAlive(cookie=43)

    def test_boundary_cookies(self) -> None:
        msg_min = MsgKeepAlive(cookie=0)
        assert msg_min.cookie == 0
        msg_max = MsgKeepAlive(cookie=65535)
        assert msg_max.cookie == 65535


class TestMsgKeepAliveResponse:
    """MsgKeepAliveResponse message construction and fields."""

    def test_construction(self) -> None:
        msg = MsgKeepAliveResponse(cookie=42)
        assert msg.cookie == 42
        assert msg.msg_id == 1

    def test_frozen(self) -> None:
        msg = MsgKeepAliveResponse(cookie=42)
        with pytest.raises(AttributeError):
            msg.cookie = 99  # type: ignore[misc]

    def test_equality(self) -> None:
        assert MsgKeepAliveResponse(cookie=1000) == MsgKeepAliveResponse(cookie=1000)
        assert MsgKeepAliveResponse(cookie=1000) != MsgKeepAliveResponse(cookie=1001)


class TestMsgDone:
    """MsgDone message construction."""

    def test_construction(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == 2

    def test_equality(self) -> None:
        assert MsgDone() == MsgDone()


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestEncoding:
    """CBOR encoding produces the correct wire format."""

    def test_encode_keep_alive(self) -> None:
        encoded = encode_keep_alive(42)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 42]

    def test_encode_keep_alive_response(self) -> None:
        encoded = encode_keep_alive_response(42)
        decoded = cbor2.loads(encoded)
        assert decoded == [1, 42]

    def test_encode_done(self) -> None:
        encoded = encode_done()
        decoded = cbor2.loads(encoded)
        assert decoded == [2]

    def test_encode_keep_alive_zero_cookie(self) -> None:
        encoded = encode_keep_alive(0)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 0]

    def test_encode_keep_alive_max_cookie(self) -> None:
        encoded = encode_keep_alive(65535)
        decoded = cbor2.loads(encoded)
        assert decoded == [0, 65535]

    def test_encode_keep_alive_invalid_cookie_negative(self) -> None:
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive(-1)

    def test_encode_keep_alive_invalid_cookie_too_large(self) -> None:
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive(65536)

    def test_encode_response_invalid_cookie_negative(self) -> None:
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive_response(-1)

    def test_encode_response_invalid_cookie_too_large(self) -> None:
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive_response(65536)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


class TestDecoding:
    """CBOR decoding recovers the original message."""

    def test_decode_keep_alive(self) -> None:
        cbor_bytes = cbor2.dumps([0, 42])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgKeepAlive)
        assert msg.cookie == 42

    def test_decode_keep_alive_response(self) -> None:
        cbor_bytes = cbor2.dumps([1, 42])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgKeepAliveResponse)
        assert msg.cookie == 42

    def test_decode_done(self) -> None:
        cbor_bytes = cbor2.dumps([2])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_unknown_message_id(self) -> None:
        cbor_bytes = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown keep-alive message ID"):
            decode_message(cbor_bytes)

    def test_decode_not_a_list(self) -> None:
        cbor_bytes = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_empty_list(self) -> None:
        cbor_bytes = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_keep_alive_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([0])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_keep_alive_extra_element(self) -> None:
        cbor_bytes = cbor2.dumps([0, 42, 99])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_response_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([1])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_done_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([2, 0])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_message(cbor_bytes)

    def test_decode_cookie_not_integer(self) -> None:
        cbor_bytes = cbor2.dumps([0, "hello"])
        with pytest.raises(ValueError, match="must be an integer"):
            decode_message(cbor_bytes)

    def test_decode_cookie_is_bool(self) -> None:
        """Booleans are technically ints in Python but should be rejected."""
        cbor_bytes = cbor2.dumps([0, True])
        with pytest.raises(ValueError, match="must be an integer"):
            decode_message(cbor_bytes)

    def test_decode_cookie_out_of_range(self) -> None:
        cbor_bytes = cbor2.dumps([0, 70000])
        with pytest.raises(ValueError, match="uint16"):
            decode_message(cbor_bytes)

    def test_decode_cookie_negative(self) -> None:
        cbor_bytes = cbor2.dumps([0, -1])
        with pytest.raises(ValueError, match="uint16"):
            decode_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Typed decode helpers
# ---------------------------------------------------------------------------


class TestTypedDecode:
    """decode_server_message and decode_client_message."""

    def test_decode_server_message(self) -> None:
        cbor_bytes = encode_keep_alive_response(123)
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgKeepAliveResponse)
        assert msg.cookie == 123

    def test_decode_server_message_rejects_client_msg(self) -> None:
        cbor_bytes = encode_keep_alive(123)
        with pytest.raises(ValueError, match="Expected server message"):
            decode_server_message(cbor_bytes)

    def test_decode_server_message_rejects_done(self) -> None:
        cbor_bytes = encode_done()
        with pytest.raises(ValueError, match="Expected server message"):
            decode_server_message(cbor_bytes)

    def test_decode_client_message_keep_alive(self) -> None:
        cbor_bytes = encode_keep_alive(456)
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgKeepAlive)
        assert msg.cookie == 456

    def test_decode_client_message_done(self) -> None:
        cbor_bytes = encode_done()
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_client_message_rejects_server_msg(self) -> None:
        cbor_bytes = encode_keep_alive_response(456)
        with pytest.raises(ValueError, match="Expected client message"):
            decode_client_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Encode then decode recovers the original message."""

    def test_keep_alive_round_trip(self) -> None:
        original = MsgKeepAlive(cookie=42)
        encoded = encode_keep_alive(original.cookie)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgKeepAlive)
        assert decoded == original

    def test_response_round_trip(self) -> None:
        original = MsgKeepAliveResponse(cookie=12345)
        encoded = encode_keep_alive_response(original.cookie)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgKeepAliveResponse)
        assert decoded == original

    def test_done_round_trip(self) -> None:
        encoded = encode_done()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgDone)
        assert decoded == MsgDone()


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestHypothesis:
    """Property-based tests for CBOR round-trip with arbitrary cookies."""

    @given(cookie=st.integers(min_value=0, max_value=65535))
    @settings(max_examples=200)
    def test_keep_alive_round_trip(self, cookie: int) -> None:
        """For any uint16 cookie, encode->decode is identity."""
        encoded = encode_keep_alive(cookie)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgKeepAlive)
        assert decoded.cookie == cookie

    @given(cookie=st.integers(min_value=0, max_value=65535))
    @settings(max_examples=200)
    def test_response_round_trip(self, cookie: int) -> None:
        """For any uint16 cookie, encode->decode is identity for responses."""
        encoded = encode_keep_alive_response(cookie)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgKeepAliveResponse)
        assert decoded.cookie == cookie

    @given(cookie=st.integers(min_value=0, max_value=65535))
    @settings(max_examples=200)
    def test_wire_format_structure(self, cookie: int) -> None:
        """Wire format is always [msg_id, cookie] for ping/pong."""
        keep_alive_bytes = encode_keep_alive(cookie)
        keep_alive_wire = cbor2.loads(keep_alive_bytes)
        assert keep_alive_wire == [0, cookie]

        response_bytes = encode_keep_alive_response(cookie)
        response_wire = cbor2.loads(response_bytes)
        assert response_wire == [1, cookie]

    @given(cookie=st.integers().filter(lambda x: x < 0 or x > 65535))
    @settings(max_examples=100)
    def test_invalid_cookie_rejected(self, cookie: int) -> None:
        """Cookies outside uint16 range are rejected at encode time."""
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive(cookie)
        with pytest.raises(ValueError, match="uint16"):
            encode_keep_alive_response(cookie)

    def test_done_wire_format(self) -> None:
        """MsgDone wire format is always [2]."""
        wire = cbor2.loads(encode_done())
        assert wire == [2]
