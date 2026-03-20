"""Tests for Block-Fetch miniprotocol typed protocol FSM, codec, and client.

Covers state machine transitions, agency assignments, codec roundtrips,
size/time limits, and BlockFetchClient methods.

Derived from test specifications:
- test_block_fetch_state_machine_idle_to_busy_transition
- test_block_fetch_state_machine_idle_to_done_transition
- test_block_fetch_busy_start_batch_to_streaming
- test_block_fetch_busy_no_blocks_returns_to_idle
- test_block_fetch_streaming_batch_done_returns_to_idle
- test_block_fetch_agency_correctness
- test_block_fetch_size_limits_per_state
- test_block_fetch_time_limits_structure_matches_all_states
- test_block_fetch_idle_state_has_no_timeout
- test_block_fetch_busy_state_timeout_is_60s
- test_block_fetch_streaming_state_timeout_is_60s
- test_block_fetch_all_requested_blocks_delivered
- test_block_fetch_client_server_round_trip_empty_range
- test_block_fetch_client_server_round_trip_with_blocks
- test_block_fetch_any_message_respects_state_limit

Spec reference: Ouroboros network spec, Section 3.3 "Block Fetch Mini-Protocol"
Haskell reference: Ouroboros/Network/Protocol/BlockFetch/Type.hs
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from vibe.core.protocols.agency import Agency, PeerRole, ProtocolError, Message
from vibe.core.protocols.codec import CodecError
from vibe.cardano.network.chainsync import (
    Point,
    Origin,
    ORIGIN,
)
from vibe.cardano.network.blockfetch import (
    MsgRequestRange,
    MsgClientDone,
    MsgStartBatch,
    MsgNoBlocks,
    MsgBlock,
    MsgBatchDone,
    encode_request_range,
    encode_client_done,
    encode_start_batch,
    encode_no_blocks,
    encode_block,
    encode_batch_done,
)
from vibe.cardano.network.blockfetch_protocol import (
    BlockFetchState,
    BlockFetchProtocol,
    BlockFetchCodec,
    BlockFetchClient,
    BfMsgRequestRange,
    BfMsgClientDone,
    BfMsgStartBatch,
    BfMsgNoBlocks,
    BfMsgBlock,
    BfMsgBatchDone,
    BLOCK_FETCH_SIZE_LIMITS,
    BLOCK_FETCH_TIME_LIMITS,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

HASH_32 = b"\xab" * 32
HASH_32_ALT = b"\xcd" * 32

SAMPLE_POINT = Point(slot=42, hash=HASH_32)
SAMPLE_POINT_ALT = Point(slot=1000, hash=HASH_32_ALT)
SAMPLE_BLOCK = b"\xde\xad\xbe\xef" * 100


# ---------------------------------------------------------------------------
# Protocol state machine
# ---------------------------------------------------------------------------


class TestProtocolStates:
    """Verify BlockFetchProtocol state machine definition."""

    def setup_method(self) -> None:
        self.protocol = BlockFetchProtocol()

    def test_initial_state_is_idle(self) -> None:
        assert self.protocol.initial_state() == BlockFetchState.BFIdle

    def test_idle_agency_is_client(self) -> None:
        assert self.protocol.agency(BlockFetchState.BFIdle) == Agency.Client

    def test_busy_agency_is_server(self) -> None:
        assert self.protocol.agency(BlockFetchState.BFBusy) == Agency.Server

    def test_streaming_agency_is_server(self) -> None:
        assert self.protocol.agency(BlockFetchState.BFStreaming) == Agency.Server

    def test_done_agency_is_nobody(self) -> None:
        assert self.protocol.agency(BlockFetchState.BFDone) == Agency.Nobody

    def test_idle_valid_messages(self) -> None:
        valid = self.protocol.valid_messages(BlockFetchState.BFIdle)
        assert BfMsgRequestRange in valid
        assert BfMsgClientDone in valid
        assert len(valid) == 2

    def test_busy_valid_messages(self) -> None:
        valid = self.protocol.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgStartBatch in valid
        assert BfMsgNoBlocks in valid
        assert len(valid) == 2

    def test_streaming_valid_messages(self) -> None:
        valid = self.protocol.valid_messages(BlockFetchState.BFStreaming)
        assert BfMsgBlock in valid
        assert BfMsgBatchDone in valid
        assert len(valid) == 2

    def test_done_no_valid_messages(self) -> None:
        valid = self.protocol.valid_messages(BlockFetchState.BFDone)
        assert len(valid) == 0


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Verify typed message state transitions match the spec.

    test_block_fetch_state_machine_idle_to_busy_transition
    test_block_fetch_state_machine_idle_to_done_transition
    test_block_fetch_busy_start_batch_to_streaming
    test_block_fetch_busy_no_blocks_returns_to_idle
    test_block_fetch_streaming_batch_done_returns_to_idle
    """

    def test_request_range_idle_to_busy(self) -> None:
        """MsgRequestRange: BFIdle -> BFBusy."""
        msg = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert msg.from_state == BlockFetchState.BFIdle
        assert msg.to_state == BlockFetchState.BFBusy

    def test_client_done_idle_to_done(self) -> None:
        """MsgClientDone: BFIdle -> BFDone."""
        msg = BfMsgClientDone()
        assert msg.from_state == BlockFetchState.BFIdle
        assert msg.to_state == BlockFetchState.BFDone

    def test_start_batch_busy_to_streaming(self) -> None:
        """MsgStartBatch: BFBusy -> BFStreaming."""
        msg = BfMsgStartBatch()
        assert msg.from_state == BlockFetchState.BFBusy
        assert msg.to_state == BlockFetchState.BFStreaming

    def test_no_blocks_busy_to_idle(self) -> None:
        """MsgNoBlocks: BFBusy -> BFIdle."""
        msg = BfMsgNoBlocks()
        assert msg.from_state == BlockFetchState.BFBusy
        assert msg.to_state == BlockFetchState.BFIdle

    def test_block_streaming_self_loop(self) -> None:
        """MsgBlock: BFStreaming -> BFStreaming."""
        msg = BfMsgBlock(block_cbor=SAMPLE_BLOCK)
        assert msg.from_state == BlockFetchState.BFStreaming
        assert msg.to_state == BlockFetchState.BFStreaming

    def test_batch_done_streaming_to_idle(self) -> None:
        """MsgBatchDone: BFStreaming -> BFIdle."""
        msg = BfMsgBatchDone()
        assert msg.from_state == BlockFetchState.BFStreaming
        assert msg.to_state == BlockFetchState.BFIdle


# ---------------------------------------------------------------------------
# Agency correctness
# ---------------------------------------------------------------------------


class TestAgencyCorrectness:
    """test_block_fetch_agency_correctness: verify that client-agency states
    only allow client messages and server-agency states only allow server
    messages.
    """

    def setup_method(self) -> None:
        self.protocol = BlockFetchProtocol()

    def test_idle_only_allows_client_messages(self) -> None:
        """BFIdle (client agency) allows only MsgRequestRange and MsgClientDone."""
        valid = self.protocol.valid_messages(BlockFetchState.BFIdle)
        # No server messages in idle
        assert BfMsgStartBatch not in valid
        assert BfMsgNoBlocks not in valid
        assert BfMsgBlock not in valid
        assert BfMsgBatchDone not in valid

    def test_busy_only_allows_server_messages(self) -> None:
        """BFBusy (server agency) allows only MsgStartBatch and MsgNoBlocks."""
        valid = self.protocol.valid_messages(BlockFetchState.BFBusy)
        assert BfMsgRequestRange not in valid
        assert BfMsgClientDone not in valid
        assert BfMsgBlock not in valid
        assert BfMsgBatchDone not in valid

    def test_streaming_only_allows_server_messages(self) -> None:
        """BFStreaming (server agency) allows only MsgBlock and MsgBatchDone."""
        valid = self.protocol.valid_messages(BlockFetchState.BFStreaming)
        assert BfMsgRequestRange not in valid
        assert BfMsgClientDone not in valid
        assert BfMsgStartBatch not in valid
        assert BfMsgNoBlocks not in valid


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------


class TestSizeLimits:
    """test_block_fetch_size_limits_per_state: verify size limits match spec."""

    def test_idle_size_limit(self) -> None:
        assert BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFIdle] == 65535

    def test_busy_size_limit(self) -> None:
        assert BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFBusy] == 65535

    def test_streaming_size_limit(self) -> None:
        assert BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFStreaming] == 2500000

    def test_all_states_covered(self) -> None:
        """Size limits cover exactly the three non-terminal states."""
        expected_states = {
            BlockFetchState.BFIdle,
            BlockFetchState.BFBusy,
            BlockFetchState.BFStreaming,
        }
        assert set(BLOCK_FETCH_SIZE_LIMITS.keys()) == expected_states


# ---------------------------------------------------------------------------
# Time limits
# ---------------------------------------------------------------------------


class TestTimeLimits:
    """test_block_fetch_time_limits_structure_matches_all_states,
    test_block_fetch_idle_state_has_no_timeout,
    test_block_fetch_busy_state_timeout_is_60s,
    test_block_fetch_streaming_state_timeout_is_60s.
    """

    def test_idle_no_timeout(self) -> None:
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFIdle] is None

    def test_busy_timeout_60s(self) -> None:
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFBusy] == 60.0

    def test_streaming_timeout_60s(self) -> None:
        assert BLOCK_FETCH_TIME_LIMITS[BlockFetchState.BFStreaming] == 60.0

    def test_all_states_covered(self) -> None:
        """Time limits cover exactly the three non-terminal states."""
        expected_states = {
            BlockFetchState.BFIdle,
            BlockFetchState.BFBusy,
            BlockFetchState.BFStreaming,
        }
        assert set(BLOCK_FETCH_TIME_LIMITS.keys()) == expected_states

    def test_golden_time_limits(self) -> None:
        """Golden test vector: {BFIdle: None, BFBusy: 60, BFStreaming: 60}."""
        expected = {
            BlockFetchState.BFIdle: None,
            BlockFetchState.BFBusy: 60.0,
            BlockFetchState.BFStreaming: 60.0,
        }
        assert BLOCK_FETCH_TIME_LIMITS == expected


# ---------------------------------------------------------------------------
# Codec roundtrip
# ---------------------------------------------------------------------------


class TestCodecRoundtrip:
    """Verify BlockFetchCodec encode/decode roundtrip for all messages."""

    def setup_method(self) -> None:
        self.codec = BlockFetchCodec()

    def test_request_range_roundtrip(self) -> None:
        msg = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT)
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgRequestRange)
        assert decoded.point_from == SAMPLE_POINT
        assert decoded.point_to == SAMPLE_POINT_ALT

    def test_client_done_roundtrip(self) -> None:
        msg = BfMsgClientDone()
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgClientDone)

    def test_start_batch_roundtrip(self) -> None:
        msg = BfMsgStartBatch()
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgStartBatch)

    def test_no_blocks_roundtrip(self) -> None:
        msg = BfMsgNoBlocks()
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgNoBlocks)

    def test_block_roundtrip(self) -> None:
        msg = BfMsgBlock(block_cbor=SAMPLE_BLOCK)
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgBlock)
        assert decoded.block_cbor == SAMPLE_BLOCK

    def test_batch_done_roundtrip(self) -> None:
        msg = BfMsgBatchDone()
        encoded = self.codec.encode(msg)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, BfMsgBatchDone)

    def test_unknown_message_type_raises(self) -> None:
        """Codec raises CodecError for unknown message types."""

        class FakeMsg(Message[BlockFetchState]):
            pass

        fake = FakeMsg(
            from_state=BlockFetchState.BFIdle,
            to_state=BlockFetchState.BFBusy,
        )
        with pytest.raises(CodecError, match="Unknown block-fetch message type"):
            self.codec.encode(fake)

    def test_decode_garbage_raises(self) -> None:
        """Codec raises CodecError for garbage bytes."""
        with pytest.raises(CodecError):
            self.codec.decode(b"\xff\xff\xff")


# ---------------------------------------------------------------------------
# Typed message properties
# ---------------------------------------------------------------------------


class TestTypedMessageProperties:
    """Verify typed message wrappers expose inner data correctly."""

    def test_request_range_properties(self) -> None:
        msg = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert msg.point_from == SAMPLE_POINT
        assert msg.point_to == SAMPLE_POINT_ALT
        assert msg.inner.msg_id == 0

    def test_block_property(self) -> None:
        msg = BfMsgBlock(block_cbor=SAMPLE_BLOCK)
        assert msg.block_cbor == SAMPLE_BLOCK
        assert msg.inner.msg_id == 4

    def test_client_done_inner(self) -> None:
        msg = BfMsgClientDone()
        assert msg.inner.msg_id == 1


# ---------------------------------------------------------------------------
# Client -- mocked runner tests
# ---------------------------------------------------------------------------


class TestBlockFetchClient:
    """Test BlockFetchClient with mocked ProtocolRunner."""

    def _make_client(self) -> tuple[BlockFetchClient, AsyncMock]:
        runner = AsyncMock()
        runner.state = BlockFetchState.BFIdle
        runner.is_done = False
        client = BlockFetchClient(runner)
        return client, runner

    @pytest.mark.asyncio
    async def test_request_range_with_blocks(self) -> None:
        """test_block_fetch_client_server_round_trip_with_blocks:
        Client requests a range, server responds with StartBatch,
        blocks, then BatchDone.
        """
        client, runner = self._make_client()

        block1 = b"block1"
        block2 = b"block2"
        block3 = b"block3"

        runner.recv_message.side_effect = [
            BfMsgStartBatch(),
            BfMsgBlock(block_cbor=block1),
            BfMsgBlock(block_cbor=block2),
            BfMsgBlock(block_cbor=block3),
            BfMsgBatchDone(),
        ]

        blocks = await client.request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert blocks is not None
        assert len(blocks) == 3
        assert blocks == [block1, block2, block3]

        # Verify send_message was called with the right type
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, BfMsgRequestRange)
        assert sent.point_from == SAMPLE_POINT
        assert sent.point_to == SAMPLE_POINT_ALT

    @pytest.mark.asyncio
    async def test_request_range_no_blocks(self) -> None:
        """test_block_fetch_client_server_round_trip_empty_range:
        Client requests a range, server responds with NoBlocks.
        """
        client, runner = self._make_client()
        runner.recv_message.return_value = BfMsgNoBlocks()

        blocks = await client.request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert blocks is None

    @pytest.mark.asyncio
    async def test_request_range_unexpected_response(self) -> None:
        """Unexpected response to RequestRange raises ProtocolError."""
        client, runner = self._make_client()
        runner.recv_message.return_value = BfMsgBatchDone()

        with pytest.raises(ProtocolError, match="Unexpected response"):
            await client.request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)

    @pytest.mark.asyncio
    async def test_streaming_unexpected_message(self) -> None:
        """Unexpected message during streaming raises ProtocolError."""
        client, runner = self._make_client()
        runner.recv_message.side_effect = [
            BfMsgStartBatch(),
            BfMsgNoBlocks(),  # Wrong -- should be Block or BatchDone
        ]

        with pytest.raises(ProtocolError, match="Unexpected message during streaming"):
            await client.request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)

    @pytest.mark.asyncio
    async def test_done(self) -> None:
        """Client.done() sends BfMsgClientDone."""
        client, runner = self._make_client()
        await client.done()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, BfMsgClientDone)

    def test_state_property(self) -> None:
        client, runner = self._make_client()
        runner.state = BlockFetchState.BFBusy
        assert client.state == BlockFetchState.BFBusy

    def test_is_done_property(self) -> None:
        client, runner = self._make_client()
        runner.is_done = True
        assert client.is_done is True

    @pytest.mark.asyncio
    async def test_all_requested_blocks_delivered(self) -> None:
        """test_block_fetch_all_requested_blocks_delivered:
        For a list of blocks, client receives exactly those blocks in
        order via MsgBlock messages before MsgBatchDone.
        """
        client, runner = self._make_client()

        expected_blocks = [f"block_{i}".encode() for i in range(50)]

        responses = [BfMsgStartBatch()]
        for b in expected_blocks:
            responses.append(BfMsgBlock(block_cbor=b))
        responses.append(BfMsgBatchDone())

        runner.recv_message.side_effect = responses

        blocks = await client.request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert blocks is not None
        assert len(blocks) == 50
        assert blocks == expected_blocks


# ---------------------------------------------------------------------------
# Full FSM walk-through
# ---------------------------------------------------------------------------


class TestFSMWalkthrough:
    """Walk through complete protocol state sequences manually."""

    def test_idle_request_noblock_done_path(self) -> None:
        """Idle -> Busy -> Idle -> Done (no blocks path)."""
        protocol = BlockFetchProtocol()

        state = protocol.initial_state()
        assert state == BlockFetchState.BFIdle
        assert protocol.agency(state) == Agency.Client

        # Client sends RequestRange
        msg1 = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert msg1.from_state == state
        state = msg1.to_state
        assert state == BlockFetchState.BFBusy
        assert protocol.agency(state) == Agency.Server

        # Server sends NoBlocks
        msg2 = BfMsgNoBlocks()
        assert msg2.from_state == state
        state = msg2.to_state
        assert state == BlockFetchState.BFIdle
        assert protocol.agency(state) == Agency.Client

        # Client sends Done
        msg3 = BfMsgClientDone()
        assert msg3.from_state == state
        state = msg3.to_state
        assert state == BlockFetchState.BFDone
        assert protocol.agency(state) == Agency.Nobody

    def test_idle_request_batch_stream_done_path(self) -> None:
        """Idle -> Busy -> Streaming -> Streaming -> Idle -> Done."""
        protocol = BlockFetchProtocol()

        state = protocol.initial_state()
        assert state == BlockFetchState.BFIdle

        # RequestRange
        msg1 = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT)
        state = msg1.to_state
        assert state == BlockFetchState.BFBusy

        # StartBatch
        msg2 = BfMsgStartBatch()
        state = msg2.to_state
        assert state == BlockFetchState.BFStreaming

        # Block (self-loop)
        msg3 = BfMsgBlock(block_cbor=b"block1")
        assert msg3.from_state == state
        state = msg3.to_state
        assert state == BlockFetchState.BFStreaming

        # Another block
        msg4 = BfMsgBlock(block_cbor=b"block2")
        state = msg4.to_state
        assert state == BlockFetchState.BFStreaming

        # BatchDone
        msg5 = BfMsgBatchDone()
        state = msg5.to_state
        assert state == BlockFetchState.BFIdle

        # ClientDone
        msg6 = BfMsgClientDone()
        state = msg6.to_state
        assert state == BlockFetchState.BFDone

    def test_multiple_ranges_path(self) -> None:
        """Multiple RequestRange/batch cycles before Done."""
        protocol = BlockFetchProtocol()
        state = protocol.initial_state()

        # First range: has blocks
        state = BfMsgRequestRange(SAMPLE_POINT, SAMPLE_POINT_ALT).to_state
        assert state == BlockFetchState.BFBusy
        state = BfMsgStartBatch().to_state
        assert state == BlockFetchState.BFStreaming
        state = BfMsgBlock(block_cbor=b"b1").to_state
        assert state == BlockFetchState.BFStreaming
        state = BfMsgBatchDone().to_state
        assert state == BlockFetchState.BFIdle

        # Second range: no blocks
        state = BfMsgRequestRange(SAMPLE_POINT_ALT, SAMPLE_POINT).to_state
        assert state == BlockFetchState.BFBusy
        state = BfMsgNoBlocks().to_state
        assert state == BlockFetchState.BFIdle

        # Done
        state = BfMsgClientDone().to_state
        assert state == BlockFetchState.BFDone


# ---------------------------------------------------------------------------
# Message size limit checks against protocol state
# ---------------------------------------------------------------------------


class TestMessageSizeLimitChecks:
    """test_block_fetch_any_message_respects_state_limit:
    Verify message sizes against per-state limits.
    """

    def test_request_range_under_idle_limit(self) -> None:
        raw = encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFIdle]

    def test_client_done_under_idle_limit(self) -> None:
        raw = encode_client_done()
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFIdle]

    def test_start_batch_under_busy_limit(self) -> None:
        raw = encode_start_batch()
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFBusy]

    def test_no_blocks_under_busy_limit(self) -> None:
        raw = encode_no_blocks()
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFBusy]

    def test_reasonable_block_under_streaming_limit(self) -> None:
        """A 2MB block fits within the 2.5MB streaming limit."""
        raw = encode_block(b"\x42" * 2_000_000)
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFStreaming]

    def test_batch_done_under_streaming_limit(self) -> None:
        raw = encode_batch_done()
        assert len(raw) <= BLOCK_FETCH_SIZE_LIMITS[BlockFetchState.BFStreaming]
