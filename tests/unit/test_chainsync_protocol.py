"""Tests for Chain-Sync miniprotocol typed protocol FSM, codec, and client.

Covers state machine transitions, agency assignments, codec roundtrips,
ChainSyncClient methods, and callback invocation in the sync loop.

Derived from test specifications:
- test_chainsync_state_transitions: all valid state transitions
- test_server_agency_after_msg_await_reply: AwaitReply -> MustReply state
- test_tokcanawait_vs_tokmustreply_distinction: sub-state behavior
- test_msg_await_reply_state_transition: AwaitReply is StNext -> StNext
- test_msg_await_reply_codec_roundtrip: AwaitReply encode/decode
- test_msg_await_reply_followed_by_roll_forward: AwaitReply then RollForward
- test_await_reply_followed_by_roll_backward: AwaitReply then RollBackward
- test_await_always_followed_by_must_reply: no double AwaitReply
- test_msg_roll_forward_available_from_both_can_await_and_must_reply
- test_intersection_found_for_any_fork_depth
- test_msg_request_next_await_reply_then_response
- test_await_reply_local_action_executes
- test_request_next_at_tip_triggers_await_reply

Spec reference: Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
Haskell reference: Ouroboros/Network/Protocol/ChainSync/Type.hs
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from vibe.core.protocols.agency import Agency, PeerRole, ProtocolError, Message
from vibe.core.protocols.codec import CodecError
from vibe.cardano.network.chainsync import (
    MsgRequestNext,
    MsgAwaitReply,
    MsgRollForward,
    MsgRollBackward,
    MsgFindIntersect,
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgDone,
    Point,
    Origin,
    ORIGIN,
    Tip,
    encode_request_next,
    encode_await_reply,
    encode_roll_forward,
    encode_roll_backward,
    encode_find_intersect,
    encode_intersect_found,
    encode_intersect_not_found,
    encode_done,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncState,
    ChainSyncProtocol,
    ChainSyncCodec,
    ChainSyncClient,
    CsMsgRequestNext,
    CsMsgAwaitReply,
    CsMsgRollForward,
    CsMsgRollBackward,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
    CsMsgIntersectNotFound,
    CsMsgDone,
    run_chain_sync,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_HASH = b"\xab" * 32
SAMPLE_POINT = Point(slot=100, hash=SAMPLE_HASH)
SAMPLE_TIP = Tip(point=SAMPLE_POINT, block_number=42)
GENESIS_TIP = Tip(point=ORIGIN, block_number=0)


@pytest.fixture
def protocol():
    return ChainSyncProtocol()


@pytest.fixture
def codec():
    return ChainSyncCodec()


class FakeChannel:
    """Fake MiniProtocolChannel for testing without a real mux."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue()

    async def send(self, payload: bytes) -> None:
        await self._outbound.put(payload)

    async def recv(self) -> bytes:
        return await self._inbound.get()

    async def inject(self, payload: bytes) -> None:
        """Inject a message into the inbound queue (simulates server)."""
        await self._inbound.put(payload)

    async def drain(self) -> bytes:
        """Read one message from the outbound queue."""
        return await self._outbound.get()


@pytest.fixture
def channel():
    return FakeChannel()


# ---------------------------------------------------------------------------
# State machine transition tests
# ---------------------------------------------------------------------------


class TestChainSyncProtocol:
    """Test the ChainSyncProtocol state machine definition."""

    def test_initial_state(self, protocol: ChainSyncProtocol):
        assert protocol.initial_state() == ChainSyncState.StIdle

    # --- Agency assignments ---

    def test_agency_st_idle_is_client(self, protocol: ChainSyncProtocol):
        """StIdle -> Client has agency."""
        assert protocol.agency(ChainSyncState.StIdle) == Agency.Client

    def test_agency_st_next_is_server(self, protocol: ChainSyncProtocol):
        """StNext -> Server has agency."""
        assert protocol.agency(ChainSyncState.StNext) == Agency.Server

    def test_agency_st_intersect_is_server(self, protocol: ChainSyncProtocol):
        """StIntersect -> Server has agency."""
        assert protocol.agency(ChainSyncState.StIntersect) == Agency.Server

    def test_agency_st_done_is_nobody(self, protocol: ChainSyncProtocol):
        """StDone -> Nobody has agency (terminal)."""
        assert protocol.agency(ChainSyncState.StDone) == Agency.Nobody

    # --- Valid messages per state ---

    def test_idle_valid_messages(self, protocol: ChainSyncProtocol):
        valid = protocol.valid_messages(ChainSyncState.StIdle)
        assert CsMsgRequestNext in valid
        assert CsMsgFindIntersect in valid
        assert CsMsgDone in valid
        assert len(valid) == 3

    def test_next_valid_messages(self, protocol: ChainSyncProtocol):
        valid = protocol.valid_messages(ChainSyncState.StNext)
        assert CsMsgAwaitReply in valid
        assert CsMsgRollForward in valid
        assert CsMsgRollBackward in valid
        assert len(valid) == 3

    def test_intersect_valid_messages(self, protocol: ChainSyncProtocol):
        valid = protocol.valid_messages(ChainSyncState.StIntersect)
        assert CsMsgIntersectFound in valid
        assert CsMsgIntersectNotFound in valid
        assert len(valid) == 2

    def test_done_no_valid_messages(self, protocol: ChainSyncProtocol):
        valid = protocol.valid_messages(ChainSyncState.StDone)
        assert len(valid) == 0

    # --- State transitions ---

    def test_request_next_transition(self):
        msg = CsMsgRequestNext()
        assert msg.from_state == ChainSyncState.StIdle
        assert msg.to_state == ChainSyncState.StNext

    def test_await_reply_transition(self):
        """AwaitReply is a self-transition within StNext.

        test_msg_await_reply_state_transition: AwaitReply transitions
        from StNext to StNext (TokCanAwait -> TokMustReply collapsed).
        """
        msg = CsMsgAwaitReply()
        assert msg.from_state == ChainSyncState.StNext
        assert msg.to_state == ChainSyncState.StNext

    def test_roll_forward_transition(self):
        msg = CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
        assert msg.from_state == ChainSyncState.StNext
        assert msg.to_state == ChainSyncState.StIdle

    def test_roll_backward_transition(self):
        msg = CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.from_state == ChainSyncState.StNext
        assert msg.to_state == ChainSyncState.StIdle

    def test_find_intersect_transition(self):
        msg = CsMsgFindIntersect(points=[SAMPLE_POINT])
        assert msg.from_state == ChainSyncState.StIdle
        assert msg.to_state == ChainSyncState.StIntersect

    def test_intersect_found_transition(self):
        msg = CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.from_state == ChainSyncState.StIntersect
        assert msg.to_state == ChainSyncState.StIdle

    def test_intersect_not_found_transition(self):
        msg = CsMsgIntersectNotFound(tip=SAMPLE_TIP)
        assert msg.from_state == ChainSyncState.StIntersect
        assert msg.to_state == ChainSyncState.StIdle

    def test_done_transition(self):
        msg = CsMsgDone()
        assert msg.from_state == ChainSyncState.StIdle
        assert msg.to_state == ChainSyncState.StDone

    # --- Full valid state paths ---

    def test_full_path_request_next_roll_forward(self, protocol):
        """StIdle -> StNext -> StIdle via RequestNext then RollForward."""
        state = protocol.initial_state()
        assert state == ChainSyncState.StIdle

        msg1 = CsMsgRequestNext()
        assert msg1.from_state == state
        state = msg1.to_state
        assert state == ChainSyncState.StNext

        msg2 = CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
        assert msg2.from_state == state
        state = msg2.to_state
        assert state == ChainSyncState.StIdle

    def test_full_path_request_next_await_then_roll_forward(self, protocol):
        """StIdle -> StNext -> StNext(AwaitReply) -> StIdle.

        test_msg_await_reply_followed_by_roll_forward: After AwaitReply,
        the eventual RollForward brings us back to StIdle.
        """
        state = protocol.initial_state()

        msg1 = CsMsgRequestNext()
        state = msg1.to_state
        assert state == ChainSyncState.StNext

        msg2 = CsMsgAwaitReply()
        assert msg2.from_state == state
        state = msg2.to_state
        assert state == ChainSyncState.StNext  # still StNext

        msg3 = CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
        assert msg3.from_state == state
        state = msg3.to_state
        assert state == ChainSyncState.StIdle

    def test_full_path_request_next_await_then_roll_backward(self, protocol):
        """test_await_reply_followed_by_roll_backward."""
        state = protocol.initial_state()

        msg1 = CsMsgRequestNext()
        state = msg1.to_state

        msg2 = CsMsgAwaitReply()
        state = msg2.to_state

        msg3 = CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg3.from_state == state
        state = msg3.to_state
        assert state == ChainSyncState.StIdle

    def test_full_path_find_intersect_found(self, protocol):
        """StIdle -> StIntersect -> StIdle via FindIntersect then Found."""
        state = protocol.initial_state()

        msg1 = CsMsgFindIntersect(points=[SAMPLE_POINT, ORIGIN])
        state = msg1.to_state
        assert state == ChainSyncState.StIntersect

        msg2 = CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        state = msg2.to_state
        assert state == ChainSyncState.StIdle

    def test_full_path_find_intersect_not_found(self, protocol):
        """StIdle -> StIntersect -> StIdle via FindIntersect then NotFound."""
        state = protocol.initial_state()

        msg1 = CsMsgFindIntersect(points=[SAMPLE_POINT])
        state = msg1.to_state

        msg2 = CsMsgIntersectNotFound(tip=SAMPLE_TIP)
        state = msg2.to_state
        assert state == ChainSyncState.StIdle

    def test_full_path_to_done(self, protocol):
        """StIdle -> StDone via Done."""
        state = protocol.initial_state()

        msg = CsMsgDone()
        state = msg.to_state
        assert state == ChainSyncState.StDone
        assert protocol.agency(state) == Agency.Nobody

    def test_roll_forward_from_both_can_await_and_must_reply(self, protocol):
        """test_msg_roll_forward_available_from_both_can_await_and_must_reply.

        RollForward can be received directly after RequestNext (CanAwait)
        or after AwaitReply (MustReply). Both paths go StNext -> StIdle.
        """
        # Path 1: Direct RollForward
        msg_direct = CsMsgRollForward(header=b"\x01", tip=SAMPLE_TIP)
        assert msg_direct.from_state == ChainSyncState.StNext
        assert msg_direct.to_state == ChainSyncState.StIdle

        # Path 2: After AwaitReply
        msg_await = CsMsgAwaitReply()
        assert msg_await.to_state == ChainSyncState.StNext
        msg_after_await = CsMsgRollForward(header=b"\x02", tip=SAMPLE_TIP)
        assert msg_after_await.from_state == ChainSyncState.StNext
        assert msg_after_await.to_state == ChainSyncState.StIdle


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


class TestChainSyncCodec:
    """Test ChainSyncCodec encode/decode roundtrips."""

    def test_encode_request_next(self, codec: ChainSyncCodec):
        msg = CsMsgRequestNext()
        data = codec.encode(msg)
        assert data == encode_request_next()

    def test_encode_find_intersect(self, codec: ChainSyncCodec):
        msg = CsMsgFindIntersect(points=[SAMPLE_POINT, ORIGIN])
        data = codec.encode(msg)
        assert data == encode_find_intersect([SAMPLE_POINT, ORIGIN])

    def test_encode_done(self, codec: ChainSyncCodec):
        msg = CsMsgDone()
        data = codec.encode(msg)
        assert data == encode_done()

    def test_encode_await_reply(self, codec: ChainSyncCodec):
        msg = CsMsgAwaitReply()
        data = codec.encode(msg)
        assert data == encode_await_reply()

    def test_encode_roll_forward(self, codec: ChainSyncCodec):
        msg = CsMsgRollForward(header=b"\xde\xad", tip=SAMPLE_TIP)
        data = codec.encode(msg)
        assert data == encode_roll_forward(b"\xde\xad", SAMPLE_TIP)

    def test_encode_roll_backward(self, codec: ChainSyncCodec):
        msg = CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        data = codec.encode(msg)
        assert data == encode_roll_backward(SAMPLE_POINT, SAMPLE_TIP)

    def test_encode_intersect_found(self, codec: ChainSyncCodec):
        msg = CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        data = codec.encode(msg)
        assert data == encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)

    def test_encode_intersect_not_found(self, codec: ChainSyncCodec):
        msg = CsMsgIntersectNotFound(tip=SAMPLE_TIP)
        data = codec.encode(msg)
        assert data == encode_intersect_not_found(SAMPLE_TIP)

    # --- Roundtrip tests ---

    def test_roundtrip_request_next(self, codec: ChainSyncCodec):
        original = CsMsgRequestNext()
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgRequestNext)
        assert decoded.from_state == original.from_state
        assert decoded.to_state == original.to_state

    def test_roundtrip_find_intersect(self, codec: ChainSyncCodec):
        original = CsMsgFindIntersect(points=[SAMPLE_POINT, ORIGIN])
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgFindIntersect)
        assert len(decoded.points) == 2
        assert decoded.points[0] == SAMPLE_POINT
        assert decoded.points[1] == ORIGIN

    def test_roundtrip_done(self, codec: ChainSyncCodec):
        original = CsMsgDone()
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgDone)

    def test_roundtrip_await_reply(self, codec: ChainSyncCodec):
        """test_msg_await_reply_codec_roundtrip: AwaitReply has no payload."""
        original = CsMsgAwaitReply()
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgAwaitReply)
        assert decoded.from_state == ChainSyncState.StNext
        assert decoded.to_state == ChainSyncState.StNext

    def test_roundtrip_roll_forward(self, codec: ChainSyncCodec):
        original = CsMsgRollForward(header=b"\xca\xfe", tip=SAMPLE_TIP)
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgRollForward)
        assert decoded.header == b"\xca\xfe"
        assert decoded.tip == SAMPLE_TIP

    def test_roundtrip_roll_backward(self, codec: ChainSyncCodec):
        original = CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgRollBackward)
        assert decoded.point == SAMPLE_POINT
        assert decoded.tip == SAMPLE_TIP

    def test_roundtrip_intersect_found(self, codec: ChainSyncCodec):
        original = CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgIntersectFound)
        assert decoded.point == SAMPLE_POINT
        assert decoded.tip == SAMPLE_TIP

    def test_roundtrip_intersect_not_found(self, codec: ChainSyncCodec):
        original = CsMsgIntersectNotFound(tip=GENESIS_TIP)
        data = codec.encode(original)
        decoded = codec.decode(data)
        assert isinstance(decoded, CsMsgIntersectNotFound)
        assert decoded.tip == GENESIS_TIP

    def test_decode_unknown_raises_codec_error(self, codec: ChainSyncCodec):
        """Garbage bytes should raise CodecError."""
        with pytest.raises(CodecError):
            codec.decode(b"\xff\xff\xff")

    def test_encode_unknown_type_raises_codec_error(self, codec: ChainSyncCodec):
        """A non-chain-sync message type should raise CodecError."""

        class FakeMsg(Message[ChainSyncState]):
            pass

        with pytest.raises(CodecError):
            codec.encode(FakeMsg(ChainSyncState.StIdle, ChainSyncState.StDone))


# ---------------------------------------------------------------------------
# ChainSyncClient tests
# ---------------------------------------------------------------------------


class TestChainSyncClient:
    """Test the high-level ChainSyncClient over a fake channel."""

    @pytest.fixture
    def setup(self, channel: FakeChannel):
        """Create a client with a fake channel."""
        from vibe.core.protocols.runner import ProtocolRunner

        protocol = ChainSyncProtocol()
        codec = ChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        client = ChainSyncClient(runner)
        return client, channel

    @pytest.mark.asyncio
    async def test_find_intersection_found(self, setup):
        """Client sends FindIntersect, server responds with IntersectFound."""
        client, channel = setup

        # Server will respond with IntersectFound
        async def server():
            _sent = await channel.drain()  # client's FindIntersect
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        server_task = asyncio.create_task(server())
        point, tip = await client.find_intersection([SAMPLE_POINT, ORIGIN])
        await server_task

        assert point == SAMPLE_POINT
        assert tip == SAMPLE_TIP

    @pytest.mark.asyncio
    async def test_find_intersection_not_found(self, setup):
        """Client sends FindIntersect, server responds with IntersectNotFound."""
        client, channel = setup

        async def server():
            await channel.drain()
            await channel.inject(encode_intersect_not_found(GENESIS_TIP))

        server_task = asyncio.create_task(server())
        point, tip = await client.find_intersection([SAMPLE_POINT])
        await server_task

        assert point is None
        assert tip == GENESIS_TIP

    @pytest.mark.asyncio
    async def test_request_next_roll_forward(self, setup):
        """Client sends RequestNext, server responds with RollForward."""
        client, channel = setup

        # First do FindIntersect to stay in valid state
        async def do_intersect():
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        t = asyncio.create_task(do_intersect())
        await client.find_intersection([SAMPLE_POINT])
        await t

        # Now request_next
        async def server():
            await channel.drain()
            await channel.inject(
                encode_roll_forward(b"\xbe\xef", SAMPLE_TIP)
            )

        server_task = asyncio.create_task(server())
        response = await client.request_next()
        await server_task

        assert isinstance(response, CsMsgRollForward)
        assert response.header == b"\xbe\xef"
        assert response.tip == SAMPLE_TIP

    @pytest.mark.asyncio
    async def test_request_next_roll_backward(self, setup):
        """Client sends RequestNext, server responds with RollBackward."""
        client, channel = setup

        async def do_intersect():
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        t = asyncio.create_task(do_intersect())
        await client.find_intersection([SAMPLE_POINT])
        await t

        async def server():
            await channel.drain()
            await channel.inject(
                encode_roll_backward(ORIGIN, GENESIS_TIP)
            )

        server_task = asyncio.create_task(server())
        response = await client.request_next()
        await server_task

        assert isinstance(response, CsMsgRollBackward)
        assert response.point == ORIGIN
        assert response.tip == GENESIS_TIP

    @pytest.mark.asyncio
    async def test_request_next_await_reply(self, setup):
        """test_msg_await_reply_is_valid_response_to_request_next."""
        client, channel = setup

        async def do_intersect():
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        t = asyncio.create_task(do_intersect())
        await client.find_intersection([SAMPLE_POINT])
        await t

        async def server():
            await channel.drain()
            await channel.inject(encode_await_reply())

        server_task = asyncio.create_task(server())
        response = await client.request_next()
        await server_task

        assert isinstance(response, CsMsgAwaitReply)

    @pytest.mark.asyncio
    async def test_recv_after_await_roll_forward(self, setup):
        """test_await_reply_followed_by_roll_forward:
        After AwaitReply, server sends RollForward."""
        client, channel = setup

        # Intersect
        async def do_intersect():
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        t = asyncio.create_task(do_intersect())
        await client.find_intersection([SAMPLE_POINT])
        await t

        # RequestNext -> AwaitReply
        async def server_await():
            await channel.drain()
            await channel.inject(encode_await_reply())

        t2 = asyncio.create_task(server_await())
        response = await client.request_next()
        await t2
        assert isinstance(response, CsMsgAwaitReply)

        # Now recv_after_await -> RollForward
        async def server_roll():
            await channel.inject(
                encode_roll_forward(b"\xca\xfe", SAMPLE_TIP)
            )

        t3 = asyncio.create_task(server_roll())
        response = await client.recv_after_await()
        await t3

        assert isinstance(response, CsMsgRollForward)
        assert response.header == b"\xca\xfe"

    @pytest.mark.asyncio
    async def test_recv_after_await_roll_backward(self, setup):
        """test_await_reply_followed_by_roll_backward."""
        client, channel = setup

        async def do_intersect():
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

        t = asyncio.create_task(do_intersect())
        await client.find_intersection([SAMPLE_POINT])
        await t

        async def server_await():
            await channel.drain()
            await channel.inject(encode_await_reply())

        t2 = asyncio.create_task(server_await())
        await client.request_next()
        await t2

        async def server_roll():
            await channel.inject(
                encode_roll_backward(ORIGIN, GENESIS_TIP)
            )

        t3 = asyncio.create_task(server_roll())
        response = await client.recv_after_await()
        await t3

        assert isinstance(response, CsMsgRollBackward)
        assert response.point == ORIGIN

    @pytest.mark.asyncio
    async def test_done(self, setup):
        """Client sends Done and protocol reaches terminal state."""
        client, channel = setup

        await client.done()
        assert client.is_done

        # Verify Done was sent on the wire
        sent_bytes = await channel.drain()
        assert sent_bytes == encode_done()

    @pytest.mark.asyncio
    async def test_state_tracks_correctly(self, setup):
        """Verify client.state reflects the protocol state after each op."""
        client, channel = setup
        assert client.state == ChainSyncState.StIdle

        # After done, should be StDone
        await client.done()
        assert client.state == ChainSyncState.StDone


# ---------------------------------------------------------------------------
# run_chain_sync integration tests
# ---------------------------------------------------------------------------


class TestRunChainSync:
    """Test the high-level run_chain_sync loop."""

    @pytest.mark.asyncio
    async def test_sync_loop_callbacks_invoked(self):
        """Callbacks are invoked on RollForward and RollBackward."""
        channel = FakeChannel()
        stop = asyncio.Event()

        forward_calls: list[tuple[bytes, Tip]] = []
        backward_calls: list[tuple[object, Tip]] = []

        async def on_fwd(header: bytes, tip: Tip) -> None:
            forward_calls.append((header, tip))

        async def on_bwd(point: object, tip: Tip) -> None:
            backward_calls.append((point, tip))
            # Stop after rollback
            stop.set()

        async def fake_server():
            # Expect FindIntersect
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

            # Expect RequestNext #1 -> RollForward
            await channel.drain()
            await channel.inject(
                encode_roll_forward(b"\x01", SAMPLE_TIP)
            )

            # Expect RequestNext #2 -> RollBackward
            await channel.drain()
            await channel.inject(
                encode_roll_backward(ORIGIN, GENESIS_TIP)
            )

            # Expect RequestNext #3 — but stop_event should be set
            # The loop will send Done instead of requesting next
            await channel.drain()  # Done message

        server = asyncio.create_task(fake_server())

        await run_chain_sync(
            channel=channel,
            known_points=[SAMPLE_POINT],
            on_roll_forward=on_fwd,
            on_roll_backward=on_bwd,
            stop_event=stop,
        )

        await server

        assert len(forward_calls) == 1
        assert forward_calls[0] == (b"\x01", SAMPLE_TIP)
        assert len(backward_calls) == 1
        assert backward_calls[0] == (ORIGIN, GENESIS_TIP)

    @pytest.mark.asyncio
    async def test_sync_loop_handles_await_reply(self):
        """test_msg_request_next_await_reply_then_response:
        The sync loop handles AwaitReply followed by RollForward."""
        channel = FakeChannel()
        stop = asyncio.Event()

        forward_calls: list[tuple[bytes, Tip]] = []

        async def on_fwd(header: bytes, tip: Tip) -> None:
            forward_calls.append((header, tip))
            stop.set()

        async def on_bwd(point: object, tip: Tip) -> None:
            pass

        async def fake_server():
            # FindIntersect
            await channel.drain()
            await channel.inject(
                encode_intersect_found(SAMPLE_POINT, SAMPLE_TIP)
            )

            # RequestNext -> AwaitReply
            await channel.drain()
            await channel.inject(encode_await_reply())

            # Then RollForward (must-reply after await)
            await channel.inject(
                encode_roll_forward(b"\x42", SAMPLE_TIP)
            )

            # Done
            await channel.drain()

        server = asyncio.create_task(fake_server())

        await run_chain_sync(
            channel=channel,
            known_points=[SAMPLE_POINT],
            on_roll_forward=on_fwd,
            on_roll_backward=on_bwd,
            stop_event=stop,
        )

        await server

        assert len(forward_calls) == 1
        assert forward_calls[0][0] == b"\x42"

    @pytest.mark.asyncio
    async def test_sync_loop_no_intersection_raises(self):
        """When no intersection is found, ProtocolError is raised."""
        channel = FakeChannel()

        async def on_fwd(h, t):
            pass

        async def on_bwd(p, t):
            pass

        async def fake_server():
            await channel.drain()
            await channel.inject(encode_intersect_not_found(GENESIS_TIP))

        server = asyncio.create_task(fake_server())

        with pytest.raises(ProtocolError, match="No intersection found"):
            await run_chain_sync(
                channel=channel,
                known_points=[SAMPLE_POINT],
                on_roll_forward=on_fwd,
                on_roll_backward=on_bwd,
            )

        await server

    @pytest.mark.asyncio
    async def test_sync_loop_empty_points_uses_origin(self):
        """When known_points is empty, Origin is used for intersection."""
        channel = FakeChannel()
        stop = asyncio.Event()
        stop.set()  # stop immediately after intersection

        async def on_fwd(h, t):
            pass

        async def on_bwd(p, t):
            pass

        async def fake_server():
            # Should receive FindIntersect with Origin
            sent = await channel.drain()
            await channel.inject(
                encode_intersect_found(ORIGIN, GENESIS_TIP)
            )
            # Will get Done since stop is already set
            await channel.drain()

        server = asyncio.create_task(fake_server())

        await run_chain_sync(
            channel=channel,
            known_points=[],
            on_roll_forward=on_fwd,
            on_roll_backward=on_bwd,
            stop_event=stop,
        )

        await server


# ---------------------------------------------------------------------------
# Message property access tests
# ---------------------------------------------------------------------------


class TestMessageProperties:
    """Test that typed message wrappers expose inner message data."""

    def test_roll_forward_properties(self):
        msg = CsMsgRollForward(header=b"\xde\xad", tip=SAMPLE_TIP)
        assert msg.header == b"\xde\xad"
        assert msg.tip == SAMPLE_TIP

    def test_roll_backward_properties(self):
        msg = CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.point == SAMPLE_POINT
        assert msg.tip == SAMPLE_TIP

    def test_find_intersect_properties(self):
        msg = CsMsgFindIntersect(points=[SAMPLE_POINT, ORIGIN])
        assert len(msg.points) == 2
        assert msg.points[0] == SAMPLE_POINT
        assert msg.points[1] == ORIGIN

    def test_intersect_found_properties(self):
        msg = CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        assert msg.point == SAMPLE_POINT
        assert msg.tip == SAMPLE_TIP

    def test_intersect_not_found_properties(self):
        msg = CsMsgIntersectNotFound(tip=GENESIS_TIP)
        assert msg.tip == GENESIS_TIP
