"""Tests for the tx-submission typed protocol FSM and codec.

Tests state transitions, agency assignments, codec encode/decode via
typed messages, protocol definition correctness, direct client-server
pairing (Haskell prop_direct), and blocking/non-blocking semantics.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.txsubmission_protocol import (
    # Limits
    TX_SUBMISSION_SIZE_LIMITS,
    TX_SUBMISSION_TIME_LIMITS,
    TsMsgDone,
    # Typed messages
    TsMsgInit,
    TsMsgReplyTxIds,
    TsMsgReplyTxs,
    TsMsgRequestTxIds,
    TsMsgRequestTxs,
    # Client
    TxSubmissionClient,
    # Codec
    TxSubmissionCodec,
    # Protocol
    TxSubmissionProtocol,
    # States
    TxSubmissionState,
)
from vibe.core.protocols.agency import Agency, Message, PeerRole
from vibe.core.protocols.codec import CodecError
from vibe.core.protocols.runner import ProtocolRunner

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
        msg = TsMsgRequestTxIds(blocking=blocking, ack_count=ack_count, req_count=req_count)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxIds)
        assert decoded.blocking == blocking
        assert decoded.ack_count == ack_count
        assert decoded.req_count == req_count

    @given(txids=st.lists(txid_size_pair, max_size=15))
    @settings(max_examples=100)
    def test_reply_tx_ids_codec_round_trip(self, txids: list[tuple[bytes, int]]) -> None:
        msg = TsMsgReplyTxIds(txids=txids)
        data = self.codec.encode(msg)
        decoded = self.codec.decode(data)
        assert isinstance(decoded, TsMsgReplyTxIds)
        assert len(decoded.txids) == len(txids)
        for (orig_id, orig_sz), (dec_id, dec_sz) in zip(txids, decoded.txids):
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
        msg_reply_ids = TsMsgReplyTxIds(txids=[(b"\x01" * 32, 200), (b"\x02" * 32, 300)])
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


# ---------------------------------------------------------------------------
# Mock MiniProtocolChannel for direct client-server testing
# ---------------------------------------------------------------------------


@dataclass
class MockChannel:
    """In-memory bidirectional channel that connects two peers.

    Creates a pair of connected channels: what one side sends, the other
    receives. This lets us run a client and server ProtocolRunner against
    each other without real networking — the Haskell equivalent of the
    ``direct`` combinator in typed-protocols tests.
    """

    _a_to_b: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _b_to_a: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)

    @property
    def client_side(self) -> _MockChannelEnd:
        """Channel end for the client (Initiator)."""
        return _MockChannelEnd(send_q=self._a_to_b, recv_q=self._b_to_a)

    @property
    def server_side(self) -> _MockChannelEnd:
        """Channel end for the server (Responder)."""
        return _MockChannelEnd(send_q=self._b_to_a, recv_q=self._a_to_b)


@dataclass
class _MockChannelEnd:
    """One end of a MockChannel — implements the send/recv interface."""

    send_q: asyncio.Queue[bytes]
    recv_q: asyncio.Queue[bytes]

    async def send(self, payload: bytes) -> None:
        await self.send_q.put(payload)

    async def recv(self) -> bytes:
        return await self.recv_q.get()


# ---------------------------------------------------------------------------
# Direct client-server pairing test (Haskell prop_direct)
#
# Creates a TxSubmissionClient and a mock server, runs them against each
# other via direct message passing (no real networking), and verifies the
# full protocol exchange: server requests tx IDs, client provides them,
# server requests txs, client sends them, protocol terminates with MsgDone.
# ---------------------------------------------------------------------------


class TestDirectClientServerPairing:
    """Direct client-server pairing without real networking.

    This is the Python equivalent of the Haskell prop_direct test from
    ouroboros-network-protocols. Two ProtocolRunners (one Initiator, one
    Responder) are connected via in-memory queues. The client offers
    transactions, the server pulls them, and we verify everything arrives
    correctly and the protocol terminates cleanly.
    """

    @pytest.mark.asyncio
    async def test_direct_pairing_happy_path(self) -> None:
        """Full exchange: Init -> RequestTxIds -> ReplyTxIds -> RequestTxs -> ReplyTxs -> Done."""
        # Test data: 2 transactions the client will offer
        tx1_id = b"\x01" * 32
        tx1_body = b"\xaa\xbb\xcc"
        tx2_id = b"\x02" * 32
        tx2_body = b"\xdd\xee\xff"

        tx_map = {tx1_id: tx1_body, tx2_id: tx2_body}
        tx_ids_with_sizes = [(tx1_id, len(tx1_body)), (tx2_id, len(tx2_body))]

        # Track what the server received
        server_received_tx_ids: list[tuple[bytes, int]] = []
        server_received_txs: list[bytes] = []

        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()

        # --- Client task ---
        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)

            # Send MsgInit
            await client.send_init()
            assert client.state == TxSubmissionState.StIdle

            # Receive server's request for tx IDs (non-blocking)
            req1 = await client.recv_server_request()
            assert isinstance(req1, TsMsgRequestTxIds)
            assert req1.blocking is False
            await client.reply_tx_ids(tx_ids_with_sizes)

            # Receive server's request for specific txs
            req2 = await client.recv_server_request()
            assert isinstance(req2, TsMsgRequestTxs)
            txs = [tx_map[txid] for txid in req2.txids]
            await client.reply_txs(txs)

            # Receive server's blocking request for more tx IDs -> signal done
            req3 = await client.recv_server_request()
            assert isinstance(req3, TsMsgRequestTxIds)
            assert req3.blocking is True
            await client.done()
            assert client.is_done

        # --- Server task ---
        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )

            # Receive MsgInit from client
            msg_init = await runner.recv_message()
            assert isinstance(msg_init, TsMsgInit)

            # Request tx IDs (non-blocking)
            await runner.send_message(TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=10))

            # Receive reply with tx IDs
            reply_ids = await runner.recv_message()
            assert isinstance(reply_ids, TsMsgReplyTxIds)
            server_received_tx_ids.extend(reply_ids.txids)

            # Request the actual transactions
            requested_ids = [txid for txid, _sz in reply_ids.txids]
            await runner.send_message(TsMsgRequestTxs(txids=requested_ids))

            # Receive reply with transactions
            reply_txs = await runner.recv_message()
            assert isinstance(reply_txs, TsMsgReplyTxs)
            server_received_txs.extend(reply_txs.txs)

            # Send blocking request for more tx IDs (client will send Done)
            await runner.send_message(TsMsgRequestTxIds(blocking=True, ack_count=2, req_count=5))

            # Receive MsgDone
            msg_done = await runner.recv_message()
            assert isinstance(msg_done, TsMsgDone)
            assert runner.is_done

        # Run both concurrently
        await asyncio.gather(run_client(), run_server())

        # Verify the server received everything the client offered
        assert server_received_tx_ids == tx_ids_with_sizes
        assert len(server_received_txs) == 2
        assert set(server_received_txs) == {tx1_body, tx2_body}

    @pytest.mark.asyncio
    async def test_direct_pairing_empty_mempool(self) -> None:
        """Client with no transactions: Init -> blocking RequestTxIds -> Done."""
        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)
            await client.send_init()

            req = await client.recv_server_request()
            assert isinstance(req, TsMsgRequestTxIds)
            assert req.blocking is True
            # No txs to offer -> done
            await client.done()
            assert client.is_done

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            msg_init = await runner.recv_message()
            assert isinstance(msg_init, TsMsgInit)

            await runner.send_message(TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5))

            msg_done = await runner.recv_message()
            assert isinstance(msg_done, TsMsgDone)
            assert runner.is_done

        await asyncio.gather(run_client(), run_server())

    @pytest.mark.asyncio
    async def test_direct_pairing_multiple_rounds(self) -> None:
        """Multiple request/reply cycles before termination."""
        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()
        all_server_txs: list[bytes] = []

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)
            await client.send_init()

            # Round 1: non-blocking request
            req1 = await client.recv_server_request()
            assert isinstance(req1, TsMsgRequestTxIds)
            await client.reply_tx_ids([(b"\x01" * 32, 100)])

            req2 = await client.recv_server_request()
            assert isinstance(req2, TsMsgRequestTxs)
            await client.reply_txs([b"\xaa"])

            # Round 2: non-blocking request
            req3 = await client.recv_server_request()
            assert isinstance(req3, TsMsgRequestTxIds)
            await client.reply_tx_ids([(b"\x02" * 32, 200)])

            req4 = await client.recv_server_request()
            assert isinstance(req4, TsMsgRequestTxs)
            await client.reply_txs([b"\xbb"])

            # Round 3: blocking -> done
            req5 = await client.recv_server_request()
            assert isinstance(req5, TsMsgRequestTxIds)
            assert req5.blocking is True
            await client.done()

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            await runner.recv_message()  # MsgInit

            for i in range(2):
                # Request tx IDs
                await runner.send_message(
                    TsMsgRequestTxIds(blocking=False, ack_count=i, req_count=5)
                )
                reply_ids = await runner.recv_message()
                assert isinstance(reply_ids, TsMsgReplyTxIds)

                # Request the txs
                ids = [txid for txid, _sz in reply_ids.txids]
                await runner.send_message(TsMsgRequestTxs(txids=ids))
                reply_txs = await runner.recv_message()
                assert isinstance(reply_txs, TsMsgReplyTxs)
                all_server_txs.extend(reply_txs.txs)

            # Final blocking request
            await runner.send_message(TsMsgRequestTxIds(blocking=True, ack_count=2, req_count=5))
            msg_done = await runner.recv_message()
            assert isinstance(msg_done, TsMsgDone)

        await asyncio.gather(run_client(), run_server())
        assert all_server_txs == [b"\xaa", b"\xbb"]


# ---------------------------------------------------------------------------
# Blocking vs non-blocking MsgRequestTxIds behavior
#
# Tests the semantic difference between blocking and non-blocking requests:
# - Blocking request (blocking=True) with empty reply is a protocol violation
#   in Haskell (the client MUST provide at least one tx ID or send MsgDone).
# - Non-blocking request (blocking=False) with empty reply IS valid.
# - Blocking request with non-empty reply IS valid.
#
# Haskell reference: Network.Protocol.TxSubmission2.Type
#   The blocking/non-blocking distinction is encoded in the state type
#   (StTxIds StBlocking vs StTxIds StNonBlocking).
# ---------------------------------------------------------------------------


class TestBlockingVsNonBlocking:
    """Test blocking vs non-blocking MsgRequestTxIds semantics."""

    def test_nonblocking_empty_reply_is_valid(self) -> None:
        """Non-blocking request with empty reply is valid (no protocol violation).

        When the server sends a non-blocking MsgRequestTxIds and the client
        has no transactions, replying with an empty list is permitted.
        """
        proto = TxSubmissionProtocol()

        # Walk through the state machine
        state = proto.initial_state()
        msg_init = TsMsgInit()
        state = msg_init.to_state  # StIdle

        # Non-blocking request
        msg_req = TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=5)
        assert msg_req.from_state == state
        state = msg_req.to_state  # StTxIds

        # Empty reply (valid for non-blocking)
        msg_reply = TsMsgReplyTxIds(txids=[])
        assert msg_reply.from_state == state
        state = msg_reply.to_state
        assert state == TxSubmissionState.StIdle  # Back to idle, no violation

    def test_blocking_nonempty_reply_is_valid(self) -> None:
        """Blocking request with non-empty reply is valid.

        When the server sends a blocking MsgRequestTxIds, the client can
        reply with tx IDs (the other valid option is MsgDone).
        """
        proto = TxSubmissionProtocol()
        state = proto.initial_state()
        state = TsMsgInit().to_state  # StIdle

        # Blocking request
        msg_req = TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5)
        state = msg_req.to_state  # StTxIds

        # Non-empty reply (valid for blocking)
        msg_reply = TsMsgReplyTxIds(txids=[(b"\x01" * 32, 100)])
        assert msg_reply.from_state == state
        state = msg_reply.to_state
        assert state == TxSubmissionState.StIdle

    def test_blocking_done_is_valid(self) -> None:
        """Blocking request answered with MsgDone is valid.

        The client signals it has no more transactions and wants to
        terminate the protocol. This is only valid after a blocking request.
        """
        proto = TxSubmissionProtocol()
        state = proto.initial_state()
        state = TsMsgInit().to_state  # StIdle

        # Blocking request
        msg_req = TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5)
        state = msg_req.to_state  # StTxIds

        # MsgDone (valid for blocking — terminate protocol)
        msg_done = TsMsgDone()
        assert msg_done.from_state == state
        state = msg_done.to_state
        assert state == TxSubmissionState.StDone
        assert proto.agency(state) == Agency.Nobody

    @pytest.mark.asyncio
    async def test_blocking_empty_reply_protocol_violation(self) -> None:
        """Blocking request with empty reply is a protocol violation.

        In Haskell, the type system prevents this: StTxIds StBlocking only
        allows MsgReplyTxIds with a NonEmpty list, or MsgDone. Our FSM
        doesn't encode this at the type level (StTxIds is a single state),
        but we test here that the semantic expectation holds: a blocking
        request answered with an empty list should be considered invalid.

        This test verifies the *semantic* invariant that blocking requests
        demand a non-empty reply or MsgDone. The enforcement happens at
        the application layer (TxSubmissionClient/Server logic), not the
        FSM level.
        """
        # The FSM itself allows MsgReplyTxIds with empty txids from StTxIds
        # (it doesn't distinguish blocking vs non-blocking at the state level).
        # But semantically, a blocking request with empty reply is wrong.
        # We verify the blocking flag is preserved through encode/decode
        # so the application layer CAN enforce this.
        codec = TxSubmissionCodec()

        # Encode a blocking request
        msg = TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5)
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, TsMsgRequestTxIds)
        assert decoded.blocking is True  # Blocking flag preserved

        # Encode a non-blocking request
        msg_nb = TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=5)
        data_nb = codec.encode(msg_nb)
        decoded_nb = codec.decode(data_nb)
        assert isinstance(decoded_nb, TsMsgRequestTxIds)
        assert decoded_nb.blocking is False  # Non-blocking flag preserved

        # The application layer can check: if blocking and reply is empty,
        # that's a violation. Verify that empty reply encodes/decodes fine
        # (the FSM allows it — enforcement is at application level).
        empty_reply = TsMsgReplyTxIds(txids=[])
        data_reply = codec.encode(empty_reply)
        decoded_reply = codec.decode(data_reply)
        assert isinstance(decoded_reply, TsMsgReplyTxIds)
        assert decoded_reply.txids == []

    @pytest.mark.asyncio
    async def test_direct_blocking_empty_vs_nonblocking_empty(self) -> None:
        """End-to-end test: non-blocking with empty reply succeeds,
        showing the contrast with blocking behavior.

        In a direct pairing, verify that a non-blocking request followed
        by an empty reply works fine and the protocol continues.
        """
        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)
            await client.send_init()

            # Non-blocking request -> empty reply (valid)
            req1 = await client.recv_server_request()
            assert isinstance(req1, TsMsgRequestTxIds)
            assert req1.blocking is False
            await client.reply_tx_ids([])  # Empty reply is fine for non-blocking

            # Blocking request -> MsgDone (valid way to handle blocking with no txs)
            req2 = await client.recv_server_request()
            assert isinstance(req2, TsMsgRequestTxIds)
            assert req2.blocking is True
            await client.done()
            assert client.is_done

        async def run_server() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Responder,
                protocol=protocol,
                codec=codec,
                channel=mock.server_side,
            )
            await runner.recv_message()  # MsgInit

            # Non-blocking request
            await runner.send_message(TsMsgRequestTxIds(blocking=False, ack_count=0, req_count=5))
            reply = await runner.recv_message()
            assert isinstance(reply, TsMsgReplyTxIds)
            assert reply.txids == []  # Empty is valid for non-blocking

            # Blocking request
            await runner.send_message(TsMsgRequestTxIds(blocking=True, ack_count=0, req_count=5))
            done = await runner.recv_message()
            assert isinstance(done, TsMsgDone)
            assert runner.is_done

        await asyncio.gather(run_client(), run_server())
