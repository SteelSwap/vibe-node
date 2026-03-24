"""Tests for local tx-monitor miniprotocol CBOR message types and codec.

Tests cover:
- Message construction and field access
- CBOR encoding produces expected wire format
- CBOR decoding recovers the original message
- Round-trip property: decode(encode(msg)) == msg for all message types
- Edge cases: malformed CBOR, unknown message IDs, Nothing/Just encoding
- Hypothesis property tests for CBOR round-trip
"""

from __future__ import annotations

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.local_txmonitor import (
    LOCAL_TX_MONITOR_ID,
    MSG_ACQUIRE,
    MSG_ACQUIRED,
    MSG_AWAIT_ACQUIRE,
    MSG_DONE,
    MSG_GET_SIZES,
    MSG_HAS_TX,
    MSG_NEXT_TX,
    MSG_RELEASE,
    MSG_REPLY_GET_SIZES,
    MSG_REPLY_HAS_TX,
    MSG_REPLY_NEXT_TX,
    MsgAcquire,
    MsgAcquired,
    MsgAwaitAcquire,
    MsgDone,
    MsgGetSizes,
    MsgHasTx,
    MsgNextTx,
    MsgRelease,
    MsgReplyGetSizes,
    MsgReplyHasTx,
    MsgReplyNextTx,
    decode_client_message,
    decode_message,
    decode_server_message,
    encode_acquire,
    encode_acquired,
    encode_await_acquire,
    encode_done,
    encode_get_sizes,
    encode_has_tx,
    encode_next_tx,
    encode_release,
    encode_reply_get_sizes,
    encode_reply_has_tx,
    encode_reply_next_tx,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify protocol constants match the spec."""

    def test_protocol_id(self) -> None:
        assert LOCAL_TX_MONITOR_ID == 9

    def test_message_ids(self) -> None:
        assert MSG_ACQUIRE == 0
        assert MSG_ACQUIRED == 1
        assert MSG_AWAIT_ACQUIRE == 2
        assert MSG_RELEASE == 3
        assert MSG_NEXT_TX == 4
        assert MSG_REPLY_NEXT_TX == 5
        assert MSG_HAS_TX == 6
        assert MSG_REPLY_HAS_TX == 7
        assert MSG_GET_SIZES == 8
        assert MSG_REPLY_GET_SIZES == 9
        assert MSG_DONE == 10


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMessageConstruction:
    """Test construction of all message types."""

    def test_msg_acquire(self) -> None:
        msg = MsgAcquire()
        assert msg.msg_id == MSG_ACQUIRE

    def test_msg_acquired(self) -> None:
        msg = MsgAcquired(slot=12345)
        assert msg.slot == 12345
        assert msg.msg_id == MSG_ACQUIRED

    def test_msg_await_acquire(self) -> None:
        msg = MsgAwaitAcquire()
        assert msg.msg_id == MSG_AWAIT_ACQUIRE

    def test_msg_release(self) -> None:
        msg = MsgRelease()
        assert msg.msg_id == MSG_RELEASE

    def test_msg_next_tx(self) -> None:
        msg = MsgNextTx()
        assert msg.msg_id == MSG_NEXT_TX

    def test_msg_reply_next_tx_nothing(self) -> None:
        msg = MsgReplyNextTx(tx=None)
        assert msg.tx is None
        assert msg.msg_id == MSG_REPLY_NEXT_TX

    def test_msg_reply_next_tx_just(self) -> None:
        msg = MsgReplyNextTx(tx=(6, b"\x01\x02"))
        assert msg.tx == (6, b"\x01\x02")

    def test_msg_has_tx(self) -> None:
        tx_id = b"\xab" * 32
        msg = MsgHasTx(tx_id=tx_id)
        assert msg.tx_id == tx_id

    def test_msg_reply_has_tx(self) -> None:
        msg = MsgReplyHasTx(has_tx=True)
        assert msg.has_tx is True

    def test_msg_get_sizes(self) -> None:
        msg = MsgGetSizes()
        assert msg.msg_id == MSG_GET_SIZES

    def test_msg_reply_get_sizes(self) -> None:
        msg = MsgReplyGetSizes(num_txs=10, total_size=5000, num_bytes=6000)
        assert msg.num_txs == 10
        assert msg.total_size == 5000
        assert msg.num_bytes == 6000

    def test_msg_done(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == MSG_DONE

    def test_frozen(self) -> None:
        msg = MsgAcquired(slot=100)
        with pytest.raises(AttributeError):
            msg.slot = 200  # type: ignore[misc]

    def test_equality(self) -> None:
        assert MsgAcquire() == MsgAcquire()
        assert MsgAcquired(slot=100) == MsgAcquired(slot=100)
        assert MsgAcquired(slot=100) != MsgAcquired(slot=200)
        assert MsgReplyNextTx(tx=None) == MsgReplyNextTx(tx=None)
        assert MsgReplyHasTx(has_tx=True) == MsgReplyHasTx(has_tx=True)
        assert MsgReplyHasTx(has_tx=True) != MsgReplyHasTx(has_tx=False)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestEncoding:
    """CBOR encoding produces the correct wire format."""

    def test_encode_acquire(self) -> None:
        wire = cbor2.loads(encode_acquire())
        assert wire == [MSG_ACQUIRE]

    def test_encode_acquired(self) -> None:
        wire = cbor2.loads(encode_acquired(12345))
        assert wire == [MSG_ACQUIRED, 12345]

    def test_encode_await_acquire(self) -> None:
        wire = cbor2.loads(encode_await_acquire())
        assert wire == [MSG_AWAIT_ACQUIRE]

    def test_encode_release(self) -> None:
        wire = cbor2.loads(encode_release())
        assert wire == [MSG_RELEASE]

    def test_encode_next_tx(self) -> None:
        wire = cbor2.loads(encode_next_tx())
        assert wire == [MSG_NEXT_TX]

    def test_encode_reply_next_tx_nothing(self) -> None:
        wire = cbor2.loads(encode_reply_next_tx(None))
        assert wire == [MSG_REPLY_NEXT_TX, []]

    def test_encode_reply_next_tx_just(self) -> None:
        wire = cbor2.loads(encode_reply_next_tx((6, b"\x01")))
        assert wire[0] == MSG_REPLY_NEXT_TX
        assert wire[1][0] == 6
        assert bytes(wire[1][1]) == b"\x01"

    def test_encode_has_tx(self) -> None:
        tx_id = b"\xab" * 32
        wire = cbor2.loads(encode_has_tx(tx_id))
        assert wire[0] == MSG_HAS_TX
        assert bytes(wire[1]) == tx_id

    def test_encode_reply_has_tx_true(self) -> None:
        wire = cbor2.loads(encode_reply_has_tx(True))
        assert wire == [MSG_REPLY_HAS_TX, True]

    def test_encode_reply_has_tx_false(self) -> None:
        wire = cbor2.loads(encode_reply_has_tx(False))
        assert wire == [MSG_REPLY_HAS_TX, False]

    def test_encode_get_sizes(self) -> None:
        wire = cbor2.loads(encode_get_sizes())
        assert wire == [MSG_GET_SIZES]

    def test_encode_reply_get_sizes(self) -> None:
        wire = cbor2.loads(encode_reply_get_sizes(10, 5000, 6000))
        assert wire == [MSG_REPLY_GET_SIZES, 10, 5000, 6000]

    def test_encode_done(self) -> None:
        wire = cbor2.loads(encode_done())
        assert wire == [MSG_DONE]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


class TestDecoding:
    """CBOR decoding recovers the original message."""

    def test_decode_acquire(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_ACQUIRE]))
        assert isinstance(msg, MsgAcquire)

    def test_decode_acquired(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_ACQUIRED, 42000]))
        assert isinstance(msg, MsgAcquired)
        assert msg.slot == 42000

    def test_decode_await_acquire(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_AWAIT_ACQUIRE]))
        assert isinstance(msg, MsgAwaitAcquire)

    def test_decode_release(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_RELEASE]))
        assert isinstance(msg, MsgRelease)

    def test_decode_next_tx(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_NEXT_TX]))
        assert isinstance(msg, MsgNextTx)

    def test_decode_reply_next_tx_nothing(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_REPLY_NEXT_TX, []]))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is None

    def test_decode_reply_next_tx_just(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_REPLY_NEXT_TX, [6, b"\x01"]]))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is not None
        assert msg.tx[0] == 6
        assert msg.tx[1] == b"\x01"

    def test_decode_has_tx(self) -> None:
        tx_id = b"\xab" * 32
        msg = decode_message(cbor2.dumps([MSG_HAS_TX, tx_id]))
        assert isinstance(msg, MsgHasTx)
        assert msg.tx_id == tx_id

    def test_decode_reply_has_tx(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_REPLY_HAS_TX, True]))
        assert isinstance(msg, MsgReplyHasTx)
        assert msg.has_tx is True

    def test_decode_get_sizes(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_GET_SIZES]))
        assert isinstance(msg, MsgGetSizes)

    def test_decode_reply_get_sizes(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_REPLY_GET_SIZES, 10, 5000, 6000]))
        assert isinstance(msg, MsgReplyGetSizes)
        assert msg.num_txs == 10
        assert msg.total_size == 5000
        assert msg.num_bytes == 6000

    def test_decode_done(self) -> None:
        msg = decode_message(cbor2.dumps([MSG_DONE]))
        assert isinstance(msg, MsgDone)

    def test_decode_unknown_message_id(self) -> None:
        with pytest.raises(ValueError, match="Unknown local tx-monitor"):
            decode_message(cbor2.dumps([99]))

    def test_decode_not_a_list(self) -> None:
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor2.dumps(42))

    def test_decode_empty_list(self) -> None:
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor2.dumps([]))

    def test_decode_acquired_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor2.dumps([MSG_ACQUIRED]))

    def test_decode_acquired_slot_not_int(self) -> None:
        with pytest.raises(ValueError, match="slot must be int"):
            decode_message(cbor2.dumps([MSG_ACQUIRED, "abc"]))

    def test_decode_acquired_slot_is_bool(self) -> None:
        with pytest.raises(ValueError, match="slot must be int"):
            decode_message(cbor2.dumps([MSG_ACQUIRED, True]))

    def test_decode_reply_next_tx_wrong_inner_length(self) -> None:
        with pytest.raises(ValueError, match="0 or 2 elements"):
            decode_message(cbor2.dumps([MSG_REPLY_NEXT_TX, [1]]))

    def test_decode_reply_next_tx_inner_not_list(self) -> None:
        with pytest.raises(ValueError, match="inner must be list"):
            decode_message(cbor2.dumps([MSG_REPLY_NEXT_TX, 42]))

    def test_decode_has_tx_not_bytes(self) -> None:
        with pytest.raises(ValueError, match="tx_id must be bytes"):
            decode_message(cbor2.dumps([MSG_HAS_TX, 42]))

    def test_decode_reply_has_tx_not_bool(self) -> None:
        with pytest.raises(ValueError, match="has_tx must be bool"):
            decode_message(cbor2.dumps([MSG_REPLY_HAS_TX, 1]))

    def test_decode_reply_get_sizes_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 4 elements"):
            decode_message(cbor2.dumps([MSG_REPLY_GET_SIZES, 10]))

    def test_decode_reply_get_sizes_not_int(self) -> None:
        with pytest.raises(ValueError, match="must be int"):
            decode_message(cbor2.dumps([MSG_REPLY_GET_SIZES, "ten", 5000, 6000]))

    def test_decode_reply_get_sizes_bool_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be int"):
            decode_message(cbor2.dumps([MSG_REPLY_GET_SIZES, True, 5000, 6000]))


# ---------------------------------------------------------------------------
# Typed decode helpers
# ---------------------------------------------------------------------------


class TestTypedDecode:
    """decode_client_message and decode_server_message."""

    def test_decode_client_acquire(self) -> None:
        msg = decode_client_message(encode_acquire())
        assert isinstance(msg, MsgAcquire)

    def test_decode_client_await_acquire(self) -> None:
        msg = decode_client_message(encode_await_acquire())
        assert isinstance(msg, MsgAwaitAcquire)

    def test_decode_client_release(self) -> None:
        msg = decode_client_message(encode_release())
        assert isinstance(msg, MsgRelease)

    def test_decode_client_next_tx(self) -> None:
        msg = decode_client_message(encode_next_tx())
        assert isinstance(msg, MsgNextTx)

    def test_decode_client_has_tx(self) -> None:
        msg = decode_client_message(encode_has_tx(b"\xab" * 32))
        assert isinstance(msg, MsgHasTx)

    def test_decode_client_get_sizes(self) -> None:
        msg = decode_client_message(encode_get_sizes())
        assert isinstance(msg, MsgGetSizes)

    def test_decode_client_done(self) -> None:
        msg = decode_client_message(encode_done())
        assert isinstance(msg, MsgDone)

    def test_decode_client_rejects_server_msg(self) -> None:
        with pytest.raises(ValueError, match="Expected client message"):
            decode_client_message(encode_acquired(100))

    def test_decode_server_acquired(self) -> None:
        msg = decode_server_message(encode_acquired(100))
        assert isinstance(msg, MsgAcquired)

    def test_decode_server_reply_next_tx(self) -> None:
        msg = decode_server_message(encode_reply_next_tx(None))
        assert isinstance(msg, MsgReplyNextTx)

    def test_decode_server_reply_has_tx(self) -> None:
        msg = decode_server_message(encode_reply_has_tx(True))
        assert isinstance(msg, MsgReplyHasTx)

    def test_decode_server_reply_get_sizes(self) -> None:
        msg = decode_server_message(encode_reply_get_sizes(5, 1000, 2000))
        assert isinstance(msg, MsgReplyGetSizes)

    def test_decode_server_rejects_client_msg(self) -> None:
        with pytest.raises(ValueError, match="Expected server message"):
            decode_server_message(encode_acquire())


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Encode then decode recovers the original message."""

    def test_acquire_round_trip(self) -> None:
        msg = decode_message(encode_acquire())
        assert isinstance(msg, MsgAcquire)

    def test_acquired_round_trip(self) -> None:
        msg = decode_message(encode_acquired(12345))
        assert isinstance(msg, MsgAcquired)
        assert msg.slot == 12345

    def test_await_acquire_round_trip(self) -> None:
        msg = decode_message(encode_await_acquire())
        assert isinstance(msg, MsgAwaitAcquire)

    def test_release_round_trip(self) -> None:
        msg = decode_message(encode_release())
        assert isinstance(msg, MsgRelease)

    def test_next_tx_round_trip(self) -> None:
        msg = decode_message(encode_next_tx())
        assert isinstance(msg, MsgNextTx)

    def test_reply_next_tx_nothing_round_trip(self) -> None:
        msg = decode_message(encode_reply_next_tx(None))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is None

    def test_reply_next_tx_just_round_trip(self) -> None:
        tx = (6, b"\x84\xa4\x00")
        msg = decode_message(encode_reply_next_tx(tx))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is not None
        assert msg.tx[0] == 6
        assert msg.tx[1] == b"\x84\xa4\x00"

    def test_has_tx_round_trip(self) -> None:
        tx_id = b"\xcd" * 32
        msg = decode_message(encode_has_tx(tx_id))
        assert isinstance(msg, MsgHasTx)
        assert msg.tx_id == tx_id

    def test_reply_has_tx_round_trip(self) -> None:
        for val in [True, False]:
            msg = decode_message(encode_reply_has_tx(val))
            assert isinstance(msg, MsgReplyHasTx)
            assert msg.has_tx == val

    def test_get_sizes_round_trip(self) -> None:
        msg = decode_message(encode_get_sizes())
        assert isinstance(msg, MsgGetSizes)

    def test_reply_get_sizes_round_trip(self) -> None:
        msg = decode_message(encode_reply_get_sizes(42, 10000, 12000))
        assert isinstance(msg, MsgReplyGetSizes)
        assert msg.num_txs == 42
        assert msg.total_size == 10000
        assert msg.num_bytes == 12000

    def test_done_round_trip(self) -> None:
        msg = decode_message(encode_done())
        assert isinstance(msg, MsgDone)


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestHypothesis:
    """Property-based tests for CBOR round-trip."""

    @given(slot=st.integers(min_value=0, max_value=2**63))
    @settings(max_examples=200)
    def test_acquired_round_trip(self, slot: int) -> None:
        msg = decode_message(encode_acquired(slot))
        assert isinstance(msg, MsgAcquired)
        assert msg.slot == slot

    @given(tx_id=st.binary(min_size=32, max_size=32))
    @settings(max_examples=200)
    def test_has_tx_round_trip(self, tx_id: bytes) -> None:
        msg = decode_message(encode_has_tx(tx_id))
        assert isinstance(msg, MsgHasTx)
        assert msg.tx_id == tx_id

    @given(has_tx=st.booleans())
    @settings(max_examples=50)
    def test_reply_has_tx_round_trip(self, has_tx: bool) -> None:
        msg = decode_message(encode_reply_has_tx(has_tx))
        assert isinstance(msg, MsgReplyHasTx)
        assert msg.has_tx == has_tx

    @given(
        num_txs=st.integers(min_value=0, max_value=10000),
        total_size=st.integers(min_value=0, max_value=2**32),
        num_bytes=st.integers(min_value=0, max_value=2**32),
    )
    @settings(max_examples=200)
    def test_reply_get_sizes_round_trip(
        self, num_txs: int, total_size: int, num_bytes: int
    ) -> None:
        msg = decode_message(encode_reply_get_sizes(num_txs, total_size, num_bytes))
        assert isinstance(msg, MsgReplyGetSizes)
        assert msg.num_txs == num_txs
        assert msg.total_size == total_size
        assert msg.num_bytes == num_bytes

    @given(
        era_id=st.integers(min_value=0, max_value=10),
        tx_bytes=st.binary(min_size=1, max_size=500),
    )
    @settings(max_examples=200)
    def test_reply_next_tx_just_round_trip(self, era_id: int, tx_bytes: bytes) -> None:
        msg = decode_message(encode_reply_next_tx((era_id, tx_bytes)))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is not None
        assert msg.tx[0] == era_id
        assert msg.tx[1] == tx_bytes

    def test_reply_next_tx_nothing_round_trip(self) -> None:
        msg = decode_message(encode_reply_next_tx(None))
        assert isinstance(msg, MsgReplyNextTx)
        assert msg.tx is None

    @given(slot=st.integers(min_value=0, max_value=2**63))
    @settings(max_examples=100)
    def test_acquired_wire_format(self, slot: int) -> None:
        wire = cbor2.loads(encode_acquired(slot))
        assert wire == [MSG_ACQUIRED, slot]


# ---------------------------------------------------------------------------
# Byte size sanity checks
# ---------------------------------------------------------------------------


class TestByteSizes:
    """Verify encoded message sizes are reasonable."""

    def test_simple_messages_are_tiny(self) -> None:
        """Parameterless messages should be 2 bytes each."""
        assert len(encode_acquire()) == 2
        assert len(encode_await_acquire()) == 2
        assert len(encode_release()) == 2
        assert len(encode_next_tx()) == 2
        assert len(encode_get_sizes()) == 2

    def test_done_is_tiny(self) -> None:
        """MsgDone [10] needs 2 bytes."""
        assert len(encode_done()) == 2

    def test_reply_next_tx_nothing_is_small(self) -> None:
        """MsgReplyNextTx Nothing [5, []] is small."""
        assert len(encode_reply_next_tx(None)) < 10
