"""Tests for the tx-submission typed protocol FSM and codec.

Tests state transitions, agency assignments, codec encode/decode via
typed messages, and protocol definition correctness.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.protocols.agency import Agency, Message, ProtocolError
from vibe.core.protocols.codec import CodecError

from vibe.cardano.network.txsubmission_protocol import (
    # States
    TxSubmissionState,
    # Protocol
    TxSubmissionProtocol,
    # Codec
    TxSubmissionCodec,
    # Typed messages
    TsMsgInit,
    TsMsgRequestTxIds,
    TsMsgReplyTxIds,
    TsMsgRequestTxs,
    TsMsgReplyTxs,
    TsMsgDone,
    # Limits
    TX_SUBMISSION_SIZE_LIMITS,
    TX_SUBMISSION_TIME_LIMITS,
)


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------


class TestTxSubmissionProtocol:
    """Test the TxSubmissionProtocol FSM definition."""

    def setup_method(self) -> None:
        self.proto = TxSubmissionProtocol()

    def test_initial_state(self) -> None:
        assert self.proto.initial_state() == TxSubmissionState.StInit

    # -- Agency assignments --

    def test_agency_st_init(self) -> None:
        """StInit: Client has agency (sends MsgInit)."""
        assert self.proto.agency(TxSubmissionState.StInit) == Agency.Client

    def test_agency_st_idle(self) -> None:
        """StIdle: Server has agency (sends MsgRequestTxIds or MsgRequestTxs)."""
        assert self.proto.agency(TxSubmissionState.StIdle) == Agency.Server

    def test_agency_st_tx_ids(self) -> None:
        """StTxIds: Client has agency (sends MsgReplyTxIds or MsgDone)."""
        assert self.proto.agency(TxSubmissionState.StTxIds) == Agency.Client

    def test_agency_st_txs(self) -> None:
        """StTxs: Client has agency (sends MsgReplyTxs)."""
        assert self.proto.agency(TxSubmissionState.StTxs) == Agency.Client

    def test_agency_st_done(self) -> None:
        """StDone: Nobody has agency (terminal)."""
        assert self.proto.agency(TxSubmissionState.StDone) == Agency.Nobody

    # -- Valid messages per state --

    def test_valid_messages_st_init(self) -> None:
        msgs = self.proto.valid_messages(TxSubmissionState.StInit)
        assert TsMsgInit in msgs
        assert len(msgs) == 1

    def test_valid_messages_st_idle(self) -> None:
        msgs = self.proto.valid_messages(TxSubmissionState.StIdle)
        assert TsMsgRequestTxIds in msgs
        assert TsMsgRequestTxs in msgs
        assert len(msgs) == 2

    def test_valid_messages_st_tx_ids(self) -> None:
        msgs = self.proto.valid_messages(TxSubmissionState.StTxIds)
        assert TsMsgReplyTxIds in msgs
        assert TsMsgDone in msgs
        assert len(msgs) == 2

    def test_valid_messages_st_txs(self) -> None:
        msgs = self.proto.valid_messages(TxSubmissionState.StTxs)
        assert TsMsgReplyTxs in msgs
        assert len(msgs) == 1

    def test_valid_messages_st_done(self) -> None:
        msgs = self.proto.valid_messages(TxSubmissionState.StDone)
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Verify that typed messages carry correct from_state/to_state."""

    def test_init_transition(self) -> None:
        msg = TsMsgInit()
        assert msg.from_state == TxSubmissionState.StInit
        assert msg.to_state == TxSubmissionState.StIdle

    def test_request_tx_ids_transition(self) -> None:
        msg = TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=1)
        assert msg.from_state == TxSubmissionState.StIdle
        assert msg.to_state == TxSubmissionState.StTxIds

    def test_reply_tx_ids_transition(self) -> None:
        msg = TsMsgReplyTxIds(txids=[(b"\x01" * 32, 100)])
        assert msg.from_state == TxSubmissionState.StTxIds
        assert msg.to_state == TxSubmissionState.StIdle

    def test_request_txs_transition(self) -> None:
        msg = TsMsgRequestTxs(txids=[b"\x01" * 32])
        assert msg.from_state == TxSubmissionState.StIdle
        assert msg.to_state == TxSubmissionState.StTxs

    def test_reply_txs_transition(self) -> None:
        msg = TsMsgReplyTxs(txs=[b"\x01\x02\x03"])
        assert msg.from_state == TxSubmissionState.StTxs
        assert msg.to_state == TxSubmissionState.StIdle

    def test_done_transition(self) -> None:
        msg = TsMsgDone()
        assert msg.from_state == TxSubmissionState.StTxIds
        assert msg.to_state == TxSubmissionState.StDone


# ---------------------------------------------------------------------------
# Typed message properties
# ---------------------------------------------------------------------------


class TestTypedMessageProperties:
    """Test that typed messages expose inner message data correctly."""

    def test_request_tx_ids_properties(self) -> None:
        msg = TsMsgRequestTxIds(blocking=False, ack_count=5, req_count=10)
        assert msg.blocking is False
        assert msg.ack_count == 5
        assert msg.req_count == 10

    def test_reply_tx_ids_properties(self) -> None:
        txids = [(b"\xab" * 32, 1024)]
        msg = TsMsgReplyTxIds(txids=txids)
        assert msg.txids == txids

    def test_request_txs_properties(self) -> None:
        txids = [b"\xab" * 32, b"\xcd" * 32]
        msg = TsMsgRequestTxs(txids=txids)
        assert msg.txids == txids

    def test_reply_txs_properties(self) -> None:
        txs = [b"\x01\x02\x03"]
        msg = TsMsgReplyTxs(txs=txs)
        assert msg.txs == txs


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class TestTxSubmissionCodec:
    """Test the TxSubmissionCodec encode/decode."""

    def setup_method(self) -> None:
        self.codec = TxSubmissionCodec()

    # -- Encode/decode round-trips for all message types --

    def test_init_round_trip(self) -> None:
        msg = TsMsgInit()
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgInit)
        assert decoded.from_state == TxSubmissionState.StInit
        assert decoded.to_state == TxSubmissionState.StIdle

    def test_request_tx_ids_round_trip(self) -> None:
        msg = TsMsgRequestTxIds(blocking=True, ack_count=3, req_count=10)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxIds)
        assert decoded.blocking is True
        assert decoded.ack_count == 3
        assert decoded.req_count == 10

    def test_reply_tx_ids_round_trip(self) -> None:
        txids = [(b"\xab" * 32, 1024), (b"\xcd" * 32, 2048)]
        msg = TsMsgReplyTxIds(txids=txids)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgReplyTxIds)
        assert len(decoded.txids) == 2
        assert decoded.txids[0] == (b"\xab" * 32, 1024)

    def test_request_txs_round_trip(self) -> None:
        txids = [b"\xab" * 32, b"\xcd" * 32]
        msg = TsMsgRequestTxs(txids=txids)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxs)
        assert decoded.txids == txids

    def test_reply_txs_round_trip(self) -> None:
        txs = [b"\x01\x02\x03", b"\x04\x05\x06"]
        msg = TsMsgReplyTxs(txs=txs)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgReplyTxs)
        assert decoded.txs == txs

    def test_done_round_trip(self) -> None:
        msg = TsMsgDone()
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgDone)
        assert decoded.from_state == TxSubmissionState.StTxIds
        assert decoded.to_state == TxSubmissionState.StDone

    # -- Codec error handling --

    def test_encode_unknown_type(self) -> None:
        """Encoding an unknown message type raises CodecError."""

        class FakeMsg(Message[TxSubmissionState]):
            pass

        fake = FakeMsg(
            from_state=TxSubmissionState.StInit,
            to_state=TxSubmissionState.StIdle,
        )
        with pytest.raises(CodecError, match="Unknown tx-submission"):
            self.codec.encode(fake)

    def test_decode_garbage(self) -> None:
        """Decoding garbage bytes raises CodecError."""
        with pytest.raises(CodecError):
            self.codec.decode(b"\xff\xff\xff")

    def test_decode_unknown_message_id(self) -> None:
        """Decoding a valid CBOR list with unknown message ID raises CodecError."""
        import cbor2

        with pytest.raises(CodecError):
            self.codec.decode(cbor2.dumps([99]))


# ---------------------------------------------------------------------------
# Size and time limits
# ---------------------------------------------------------------------------


class TestLimits:
    """Verify size and time limits are defined for relevant states."""

    def test_size_limits_defined(self) -> None:
        assert TxSubmissionState.StInit in TX_SUBMISSION_SIZE_LIMITS
        assert TxSubmissionState.StIdle in TX_SUBMISSION_SIZE_LIMITS
        assert TxSubmissionState.StTxIds in TX_SUBMISSION_SIZE_LIMITS
        assert TxSubmissionState.StTxs in TX_SUBMISSION_SIZE_LIMITS

    def test_idle_size_limit(self) -> None:
        assert TX_SUBMISSION_SIZE_LIMITS[TxSubmissionState.StIdle] == 65535

    def test_txs_size_limit(self) -> None:
        """StTxs allows larger messages for full transactions."""
        assert TX_SUBMISSION_SIZE_LIMITS[TxSubmissionState.StTxs] == 2500000

    def test_time_limits_defined(self) -> None:
        assert TxSubmissionState.StInit in TX_SUBMISSION_TIME_LIMITS
        assert TxSubmissionState.StIdle in TX_SUBMISSION_TIME_LIMITS
        assert TxSubmissionState.StTxIds in TX_SUBMISSION_TIME_LIMITS
        assert TxSubmissionState.StTxs in TX_SUBMISSION_TIME_LIMITS

    def test_idle_no_timeout(self) -> None:
        """StIdle has no timeout (server drives at own pace)."""
        assert TX_SUBMISSION_TIME_LIMITS[TxSubmissionState.StIdle] is None


# ---------------------------------------------------------------------------
# Hypothesis property-based tests: Codec round-trip
# ---------------------------------------------------------------------------

txid_strategy = st.binary(min_size=1, max_size=64)
size_strategy = st.integers(min_value=0, max_value=2**32 - 1)
txid_size_pair = st.tuples(txid_strategy, size_strategy)
tx_strategy = st.binary(min_size=1, max_size=256)


class TestHypothesisCodecRoundTrip:
    """Property-based codec round-trip tests using Hypothesis."""

    def setup_method(self) -> None:
        self.codec = TxSubmissionCodec()

    @given(
        blocking=st.booleans(),
        ack_count=st.integers(min_value=0, max_value=65535),
        req_count=st.integers(min_value=0, max_value=65535),
    )
    @settings(max_examples=100)
    def test_request_tx_ids_codec_round_trip(
        self, blocking: bool, ack_count: int, req_count: int
    ) -> None:
        msg = TsMsgRequestTxIds(
            blocking=blocking, ack_count=ack_count, req_count=req_count
        )
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxIds)
        assert decoded.blocking == blocking
        assert decoded.ack_count == ack_count
        assert decoded.req_count == req_count

    @given(txids=st.lists(txid_size_pair, max_size=15))
    @settings(max_examples=100)
    def test_reply_tx_ids_codec_round_trip(
        self, txids: list[tuple[bytes, int]]
    ) -> None:
        msg = TsMsgReplyTxIds(txids=txids)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgReplyTxIds)
        assert len(decoded.txids) == len(txids)
        for (orig_id, orig_sz), (dec_id, dec_sz) in zip(
            txids, decoded.txids
        ):
            assert dec_id == orig_id
            assert dec_sz == orig_sz

    @given(txids=st.lists(txid_strategy, max_size=15))
    @settings(max_examples=100)
    def test_request_txs_codec_round_trip(self, txids: list[bytes]) -> None:
        msg = TsMsgRequestTxs(txids=txids)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxs)
        assert decoded.txids == txids

    @given(txs=st.lists(tx_strategy, max_size=15))
    @settings(max_examples=100)
    def test_reply_txs_codec_round_trip(self, txs: list[bytes]) -> None:
        msg = TsMsgReplyTxs(txs=txs)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgReplyTxs)
        assert decoded.txs == txs


# ---------------------------------------------------------------------------
# Full protocol walk-through (state sequence)
# ---------------------------------------------------------------------------


class TestProtocolWalkthrough:
    """Test a complete protocol interaction sequence through the FSM.

    This validates that a realistic sequence of state transitions is
    valid according to the protocol definition.
    """

    def setup_method(self) -> None:
        self.proto = TxSubmissionProtocol()

    def test_happy_path_with_tx_ids_and_txs(self) -> None:
        """Simulate: Init -> RequestTxIds -> ReplyTxIds -> RequestTxs -> ReplyTxs -> Done."""
        state = self.proto.initial_state()
        assert state == TxSubmissionState.StInit

        # Client sends MsgInit
        msg_init = TsMsgInit()
        assert msg_init.from_state == state
        state = msg_init.to_state
        assert state == TxSubmissionState.StIdle

        # Server sends MsgRequestTxIds (blocking)
        msg_req_ids = TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5)
        assert msg_req_ids.from_state == state
        state = msg_req_ids.to_state
        assert state == TxSubmissionState.StTxIds

        # Client replies with tx IDs
        msg_reply_ids = TsMsgReplyTxIds(
            txids=[(b"\x01" * 32, 200), (b"\x02" * 32, 300)]
        )
        assert msg_reply_ids.from_state == state
        state = msg_reply_ids.to_state
        assert state == TxSubmissionState.StIdle

        # Server sends MsgRequestTxs
        msg_req_txs = TsMsgRequestTxs(txids=[b"\x01" * 32])
        assert msg_req_txs.from_state == state
        state = msg_req_txs.to_state
        assert state == TxSubmissionState.StTxs

        # Client replies with transactions
        msg_reply_txs = TsMsgReplyTxs(txs=[b"\xaa\xbb\xcc"])
        assert msg_reply_txs.from_state == state
        state = msg_reply_txs.to_state
        assert state == TxSubmissionState.StIdle

        # Server sends another blocking MsgRequestTxIds
        msg_req_ids2 = TsMsgRequestTxIds(blocking=True, ack_count=1, req_count=5)
        assert msg_req_ids2.from_state == state
        state = msg_req_ids2.to_state
        assert state == TxSubmissionState.StTxIds

        # Client sends MsgDone (no more txs)
        msg_done = TsMsgDone()
        assert msg_done.from_state == state
        state = msg_done.to_state
        assert state == TxSubmissionState.StDone

        # Terminal -- nobody has agency
        assert self.proto.agency(state) == Agency.Nobody

    def test_nonblocking_empty_reply(self) -> None:
        """Non-blocking request can be answered with empty tx ID list."""
        state = self.proto.initial_state()

        # Init
        msg_init = TsMsgInit()
        state = msg_init.to_state

        # Server sends non-blocking request
        msg_req = TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=3)
        assert msg_req.from_state == state
        state = msg_req.to_state

        # Client replies with empty list (valid for non-blocking)
        msg_reply = TsMsgReplyTxIds(txids=[])
        assert msg_reply.from_state == state
        state = msg_reply.to_state
        assert state == TxSubmissionState.StIdle

    def test_multiple_request_reply_cycles(self) -> None:
        """Multiple cycles of request/reply before termination."""
        state = self.proto.initial_state()
        state = TsMsgInit().to_state

        for i in range(5):
            # Server requests tx IDs
            msg = TsMsgRequestTxIds(blocking=False, ack_count=i, req_count=3)
            assert msg.from_state == state
            state = msg.to_state

            # Client replies
            msg2 = TsMsgReplyTxIds(txids=[(b"\x01" * 32, 100)])
            assert msg2.from_state == state
            state = msg2.to_state
            assert state == TxSubmissionState.StIdle

        # Final blocking request -> Done
        msg3 = TsMsgRequestTxIds(blocking=True, ack_count=5, req_count=1)
        state = msg3.to_state
        msg4 = TsMsgDone()
        assert msg4.from_state == state
        state = msg4.to_state
        assert state == TxSubmissionState.StDone
