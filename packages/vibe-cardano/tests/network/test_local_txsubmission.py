"""Tests for local tx-submission miniprotocol CBOR message types and codec.

Tests cover:
- Message construction and field access
- CBOR encoding produces expected wire format
- CBOR decoding recovers the original message
- Round-trip property: decode(encode(msg)) == msg for all message types
- Edge cases: malformed CBOR, unknown message IDs
- Hypothesis property tests for CBOR round-trip
"""

from __future__ import annotations

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.local_txsubmission import (
    LOCAL_TX_SUBMISSION_ID,
    MSG_ACCEPT_TX,
    MSG_DONE,
    MSG_REJECT_TX,
    MSG_SUBMIT_TX,
    MsgAcceptTx,
    MsgDone,
    MsgRejectTx,
    MsgSubmitTx,
    decode_client_message,
    decode_message,
    decode_server_message,
    encode_accept_tx,
    encode_done,
    encode_reject_tx,
    encode_submit_tx,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify protocol constants match the spec."""

    def test_protocol_id(self) -> None:
        assert LOCAL_TX_SUBMISSION_ID == 6

    def test_message_ids(self) -> None:
        assert MSG_SUBMIT_TX == 0
        assert MSG_ACCEPT_TX == 1
        assert MSG_REJECT_TX == 2
        assert MSG_DONE == 3


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMsgSubmitTx:
    """MsgSubmitTx message construction and fields."""

    def test_construction(self) -> None:
        msg = MsgSubmitTx(era_id=6, tx_bytes=b"\x01\x02\x03")
        assert msg.era_id == 6
        assert msg.tx_bytes == b"\x01\x02\x03"
        assert msg.msg_id == MSG_SUBMIT_TX

    def test_frozen(self) -> None:
        msg = MsgSubmitTx(era_id=6, tx_bytes=b"\x01")
        with pytest.raises(AttributeError):
            msg.era_id = 7  # type: ignore[misc]

    def test_equality(self) -> None:
        assert MsgSubmitTx(era_id=6, tx_bytes=b"\x01") == MsgSubmitTx(era_id=6, tx_bytes=b"\x01")
        assert MsgSubmitTx(era_id=6, tx_bytes=b"\x01") != MsgSubmitTx(era_id=5, tx_bytes=b"\x01")


class TestMsgAcceptTx:
    """MsgAcceptTx message construction."""

    def test_construction(self) -> None:
        msg = MsgAcceptTx()
        assert msg.msg_id == MSG_ACCEPT_TX

    def test_equality(self) -> None:
        assert MsgAcceptTx() == MsgAcceptTx()


class TestMsgRejectTx:
    """MsgRejectTx message construction and fields."""

    def test_construction(self) -> None:
        reason = cbor2.dumps("insufficient funds")
        msg = MsgRejectTx(reason=reason)
        assert msg.reason == reason
        assert msg.msg_id == MSG_REJECT_TX

    def test_frozen(self) -> None:
        msg = MsgRejectTx(reason=b"\x01")
        with pytest.raises(AttributeError):
            msg.reason = b"\x02"  # type: ignore[misc]


class TestMsgDone:
    """MsgDone message construction."""

    def test_construction(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == MSG_DONE

    def test_equality(self) -> None:
        assert MsgDone() == MsgDone()


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestEncoding:
    """CBOR encoding produces the correct wire format."""

    def test_encode_submit_tx(self) -> None:
        tx_bytes = b"\x84\xa4\x00\x81"
        encoded = encode_submit_tx(6, tx_bytes)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == MSG_SUBMIT_TX
        assert decoded[1] == 6
        assert bytes(decoded[2]) == tx_bytes

    def test_encode_accept_tx(self) -> None:
        encoded = encode_accept_tx()
        decoded = cbor2.loads(encoded)
        assert decoded == [MSG_ACCEPT_TX]

    def test_encode_reject_tx(self) -> None:
        reason = cbor2.dumps("bad tx")
        encoded = encode_reject_tx(reason)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == MSG_REJECT_TX
        assert decoded[1] == "bad tx"

    def test_encode_done(self) -> None:
        encoded = encode_done()
        decoded = cbor2.loads(encoded)
        assert decoded == [MSG_DONE]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


class TestDecoding:
    """CBOR decoding recovers the original message."""

    def test_decode_submit_tx(self) -> None:
        tx_bytes = b"\x84\xa4\x00\x81"
        cbor_bytes = cbor2.dumps([MSG_SUBMIT_TX, 6, tx_bytes])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgSubmitTx)
        assert msg.era_id == 6
        assert msg.tx_bytes == tx_bytes

    def test_decode_accept_tx(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_ACCEPT_TX])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgAcceptTx)

    def test_decode_reject_tx(self) -> None:
        reason_value = "insufficient funds"
        cbor_bytes = cbor2.dumps([MSG_REJECT_TX, reason_value])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgRejectTx)
        # The reason is re-encoded to bytes
        assert cbor2.loads(msg.reason) == reason_value

    def test_decode_done(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_DONE])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_unknown_message_id(self) -> None:
        cbor_bytes = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown local tx-submission message ID"):
            decode_message(cbor_bytes)

    def test_decode_not_a_list(self) -> None:
        cbor_bytes = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_empty_list(self) -> None:
        cbor_bytes = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_submit_tx_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_SUBMIT_TX, 6])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_message(cbor_bytes)

    def test_decode_accept_tx_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_ACCEPT_TX, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_message(cbor_bytes)

    def test_decode_reject_tx_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_REJECT_TX])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_done_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_DONE, 0])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_message(cbor_bytes)

    def test_decode_submit_tx_era_not_int(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_SUBMIT_TX, "six", b"\x01"])
        with pytest.raises(ValueError, match="era_id must be int"):
            decode_message(cbor_bytes)

    def test_decode_submit_tx_era_is_bool(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_SUBMIT_TX, True, b"\x01"])
        with pytest.raises(ValueError, match="era_id must be int"):
            decode_message(cbor_bytes)

    def test_decode_submit_tx_bytes_not_bytes(self) -> None:
        cbor_bytes = cbor2.dumps([MSG_SUBMIT_TX, 6, "not bytes"])
        with pytest.raises(ValueError, match="tx_bytes must be bytes"):
            decode_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Typed decode helpers
# ---------------------------------------------------------------------------


class TestTypedDecode:
    """decode_client_message and decode_server_message."""

    def test_decode_client_submit_tx(self) -> None:
        cbor_bytes = encode_submit_tx(6, b"\x01\x02")
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgSubmitTx)

    def test_decode_client_done(self) -> None:
        cbor_bytes = encode_done()
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_client_rejects_server_msg(self) -> None:
        cbor_bytes = encode_accept_tx()
        with pytest.raises(ValueError, match="Expected client message"):
            decode_client_message(cbor_bytes)

    def test_decode_server_accept(self) -> None:
        cbor_bytes = encode_accept_tx()
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgAcceptTx)

    def test_decode_server_reject(self) -> None:
        reason = cbor2.dumps("bad")
        cbor_bytes = encode_reject_tx(reason)
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgRejectTx)

    def test_decode_server_rejects_client_msg(self) -> None:
        cbor_bytes = encode_submit_tx(6, b"\x01")
        with pytest.raises(ValueError, match="Expected server message"):
            decode_server_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Encode then decode recovers the original message."""

    def test_submit_tx_round_trip(self) -> None:
        tx_bytes = b"\x84\xa4\x00\x81\x82"
        encoded = encode_submit_tx(6, tx_bytes)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSubmitTx)
        assert decoded.era_id == 6
        assert decoded.tx_bytes == tx_bytes

    def test_accept_tx_round_trip(self) -> None:
        encoded = encode_accept_tx()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgAcceptTx)
        assert decoded == MsgAcceptTx()

    def test_reject_tx_round_trip(self) -> None:
        reason = cbor2.dumps({"error": "insufficient funds", "code": 42})
        encoded = encode_reject_tx(reason)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgRejectTx)
        assert cbor2.loads(decoded.reason) == cbor2.loads(reason)

    def test_done_round_trip(self) -> None:
        encoded = encode_done()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgDone)
        assert decoded == MsgDone()


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestHypothesis:
    """Property-based tests for CBOR round-trip."""

    @given(
        era_id=st.integers(min_value=0, max_value=10),
        tx_bytes=st.binary(min_size=1, max_size=1000),
    )
    @settings(max_examples=200)
    def test_submit_tx_round_trip(self, era_id: int, tx_bytes: bytes) -> None:
        """For any era_id and tx_bytes, encode->decode is identity."""
        encoded = encode_submit_tx(era_id, tx_bytes)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgSubmitTx)
        assert decoded.era_id == era_id
        assert decoded.tx_bytes == tx_bytes

    @given(
        era_id=st.integers(min_value=0, max_value=10),
        tx_bytes=st.binary(min_size=1, max_size=1000),
    )
    @settings(max_examples=200)
    def test_submit_tx_wire_format(self, era_id: int, tx_bytes: bytes) -> None:
        """Wire format is always [0, era_id, tx_bytes]."""
        encoded = encode_submit_tx(era_id, tx_bytes)
        wire = cbor2.loads(encoded)
        assert wire[0] == MSG_SUBMIT_TX
        assert wire[1] == era_id
        assert bytes(wire[2]) == tx_bytes

    def test_accept_tx_wire_format(self) -> None:
        """MsgAcceptTx wire format is always [1]."""
        wire = cbor2.loads(encode_accept_tx())
        assert wire == [MSG_ACCEPT_TX]

    def test_done_wire_format(self) -> None:
        """MsgDone wire format is always [3]."""
        wire = cbor2.loads(encode_done())
        assert wire == [MSG_DONE]

    @given(reason_str=st.text(max_size=200))
    @settings(max_examples=100)
    def test_reject_tx_round_trip(self, reason_str: str) -> None:
        """For any reason string, encode->decode preserves the reason."""
        reason = cbor2.dumps(reason_str)
        encoded = encode_reject_tx(reason)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgRejectTx)
        assert cbor2.loads(decoded.reason) == reason_str


# ---------------------------------------------------------------------------
# Byte size sanity checks
# ---------------------------------------------------------------------------


class TestByteSizes:
    """Verify encoded message sizes are reasonable."""

    def test_accept_tx_is_tiny(self) -> None:
        """MsgAcceptTx should be very small (2 bytes)."""
        assert len(encode_accept_tx()) == 2

    def test_done_is_tiny(self) -> None:
        """MsgDone should be very small (2 bytes)."""
        assert len(encode_done()) == 2

    def test_submit_tx_overhead_is_small(self) -> None:
        """MsgSubmitTx overhead (beyond tx_bytes) should be minimal."""
        tx = b"\x00" * 100
        encoded = encode_submit_tx(6, tx)
        # Overhead: [0, 6, <100 bytes>] -> a few bytes of CBOR framing
        assert len(encoded) < len(tx) + 20
