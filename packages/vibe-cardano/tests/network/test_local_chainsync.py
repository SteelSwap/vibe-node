"""Tests for Local Chain-Sync (N2C) miniprotocol.

Covers:
- N2C message CBOR encode/decode roundtrips (N2CMsgRollForward with full block)
- Shared message roundtrips (messages identical to N2N)
- LocalChainSyncProtocol FSM state transitions and agency
- LocalChainSyncCodec encode/decode for all message types
- LocalChainSyncServer find_intersect with known/unknown points
- LocalChainSyncServer roll_forward with mock ChainDB
- LocalChainSyncServer roll_backward on fork
- Codec split tests (2-chunk, 3-chunk)

Spec reference: Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
Haskell reference: Ouroboros/Network/Protocol/ChainSync/Server.hs
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import cbor2
import pytest

from vibe.core.protocols.agency import Agency, PeerRole, ProtocolError, Message
from vibe.core.protocols.codec import CodecError
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.chainsync import (
    MSG_REQUEST_NEXT,
    MSG_AWAIT_REPLY,
    MSG_ROLL_FORWARD,
    MSG_ROLL_BACKWARD,
    MSG_FIND_INTERSECT,
    MSG_INTERSECT_FOUND,
    MSG_INTERSECT_NOT_FOUND,
    MSG_DONE,
    CHAIN_SYNC_N2C_ID,
    ORIGIN,
    Origin,
    Point,
    Tip,
    encode_request_next,
    encode_find_intersect,
    encode_done,
    encode_await_reply,
    encode_roll_backward,
    encode_intersect_found,
    encode_intersect_not_found,
)
from vibe.cardano.network.local_chainsync import (
    N2CMsgRollForward,
    encode_n2c_roll_forward,
    decode_n2c_server_message,
)
from vibe.cardano.network.local_chainsync_protocol import (
    LocalChainSyncState,
    LocalChainSyncProtocol,
    LocalChainSyncCodec,
    LocalChainSyncServer,
    LcsMsgRequestNext,
    LcsMsgAwaitReply,
    LcsMsgRollForward,
    LcsMsgRollBackward,
    LcsMsgFindIntersect,
    LcsMsgIntersectFound,
    LcsMsgIntersectNotFound,
    LcsMsgDone,
    create_local_chainsync_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HASH_A = b"\xaa" * 32
HASH_B = b"\xbb" * 32
HASH_C = b"\xcc" * 32

POINT_A = Point(slot=100, hash=HASH_A)
POINT_B = Point(slot=200, hash=HASH_B)
POINT_C = Point(slot=300, hash=HASH_C)

TIP_A = Tip(point=POINT_A, block_number=10)
TIP_B = Tip(point=POINT_B, block_number=20)
TIP_C = Tip(point=POINT_C, block_number=30)
GENESIS_TIP = Tip(point=ORIGIN, block_number=0)

# Simulate a CBOR-encoded full block (what N2C sends instead of a header)
SAMPLE_BLOCK = cbor2.dumps([0, {"slot": 100, "txs": [b"\x01", b"\x02"]}])
SAMPLE_BLOCK_B = cbor2.dumps([0, {"slot": 200, "txs": [b"\x03"]}])


@pytest.fixture
def protocol():
    return LocalChainSyncProtocol()


@pytest.fixture
def codec():
    return LocalChainSyncCodec()


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
        """Inject a message into the inbound queue (simulates client)."""
        await self._inbound.put(payload)

    async def drain(self) -> bytes:
        """Read one message from the outbound queue."""
        return await self._outbound.get()


@pytest.fixture
def channel():
    return FakeChannel()


class MockChainDB:
    """Mock ChainDB for testing the server.

    Simulates a chain as an ordered list of (point, block_cbor) tuples.
    """

    def __init__(
        self,
        chain: list[tuple[Point, bytes]] | None = None,
        tip: Tip | None = None,
    ) -> None:
        self._chain: list[tuple[Point, bytes]] = chain or []
        self._tip = tip or GENESIS_TIP
        self._new_block_event = asyncio.Event()
        self._fork_point: dict[Point, Point | Origin] = {}

    def get_tip(self) -> Tip:
        return self._tip

    def find_intersect(self, points: list) -> Point | Origin | None:
        chain_points = {p for p, _ in self._chain}
        for p in points:
            if isinstance(p, Origin):
                return ORIGIN
            if p in chain_points:
                return p
        return None

    def read_block_after(self, point) -> tuple[bytes, Point] | None:
        if isinstance(point, Origin):
            if self._chain:
                return (self._chain[0][1], self._chain[0][0])
            return None
        for i, (p, _block) in enumerate(self._chain):
            if p == point:
                if i + 1 < len(self._chain):
                    next_point, next_block = self._chain[i + 1]
                    return (next_block, next_point)
                return None
        return None

    def read_block_at(self, point) -> bytes | None:
        for p, block in self._chain:
            if p == point:
                return block
        return None

    async def wait_for_new_block(self) -> None:
        self._new_block_event.clear()
        await self._new_block_event.wait()

    def get_fork_point(self, client_point) -> Point | Origin | None:
        if isinstance(client_point, Origin):
            return None
        if isinstance(client_point, Point) and client_point in self._fork_point:
            return self._fork_point[client_point]
        return None

    def add_block(self, point: Point, block_cbor: bytes, new_tip: Tip) -> None:
        """Add a block and notify waiters."""
        self._chain.append((point, block_cbor))
        self._tip = new_tip
        self._new_block_event.set()

    def set_fork(self, old_point: Point, fork_to: Point | Origin) -> None:
        """Simulate a fork: old_point is no longer on chain, roll back to fork_to."""
        self._fork_point[old_point] = fork_to


# ---------------------------------------------------------------------------
# N2C Protocol ID
# ---------------------------------------------------------------------------


class TestProtocolID:
    def test_n2c_chainsync_id_is_5(self) -> None:
        """N2C chain-sync is miniprotocol ID 5."""
        assert CHAIN_SYNC_N2C_ID == 5


# ---------------------------------------------------------------------------
# N2C MsgRollForward — the key difference from N2N
# ---------------------------------------------------------------------------


class TestN2CMsgRollForward:
    """Test the N2C-specific MsgRollForward that carries a full block."""

    def test_msg_id(self) -> None:
        msg = N2CMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        assert msg.msg_id == MSG_ROLL_FORWARD

    def test_frozen(self) -> None:
        msg = N2CMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        with pytest.raises(AttributeError):
            msg.block = b""  # type: ignore[misc]

    def test_block_is_full_block(self) -> None:
        """Verify block contains full block data, not just a header."""
        msg = N2CMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        decoded = cbor2.loads(msg.block)
        assert "txs" in decoded[1]  # Full block has transactions

    def test_encode_roundtrip(self) -> None:
        """Encode then decode N2C MsgRollForward with full block."""
        raw = encode_n2c_roll_forward(SAMPLE_BLOCK, TIP_A)
        msg = decode_n2c_server_message(raw)
        assert isinstance(msg, N2CMsgRollForward)
        assert msg.block == SAMPLE_BLOCK
        assert msg.tip == TIP_A

    def test_encode_cbor_structure(self) -> None:
        """CBOR structure is [2, block_bytes, [point, blockno]]."""
        raw = encode_n2c_roll_forward(SAMPLE_BLOCK, TIP_A)
        parsed = cbor2.loads(raw)
        assert parsed[0] == MSG_ROLL_FORWARD
        assert parsed[1] == SAMPLE_BLOCK
        assert parsed[2][0] == [100, HASH_A]
        assert parsed[2][1] == 10

    def test_large_block_roundtrip(self) -> None:
        """Roundtrip with a realistically-sized block (~64KB)."""
        large_block = cbor2.dumps([0, {"txs": [b"\xff" * 1000] * 60}])
        raw = encode_n2c_roll_forward(large_block, TIP_A)
        msg = decode_n2c_server_message(raw)
        assert isinstance(msg, N2CMsgRollForward)
        assert msg.block == large_block

    def test_genesis_tip_roundtrip(self) -> None:
        """RollForward with genesis tip."""
        raw = encode_n2c_roll_forward(SAMPLE_BLOCK, GENESIS_TIP)
        msg = decode_n2c_server_message(raw)
        assert isinstance(msg, N2CMsgRollForward)
        assert msg.tip.point == ORIGIN
        assert msg.tip.block_number == 0


# ---------------------------------------------------------------------------
# N2C server message decode — other messages
# ---------------------------------------------------------------------------


class TestN2CServerMessageDecode:
    """Decode shared server messages through the N2C decoder."""

    def test_await_reply(self) -> None:
        raw = encode_await_reply()
        msg = decode_n2c_server_message(raw)
        assert isinstance(msg, type(msg))  # MsgAwaitReply

    def test_roll_backward(self) -> None:
        raw = encode_roll_backward(POINT_A, TIP_B)
        msg = decode_n2c_server_message(raw)
        from vibe.cardano.network.chainsync import MsgRollBackward
        assert isinstance(msg, MsgRollBackward)
        assert msg.point == POINT_A
        assert msg.tip == TIP_B

    def test_intersect_found(self) -> None:
        raw = encode_intersect_found(POINT_A, TIP_A)
        msg = decode_n2c_server_message(raw)
        from vibe.cardano.network.chainsync import MsgIntersectFound
        assert isinstance(msg, MsgIntersectFound)
        assert msg.point == POINT_A

    def test_intersect_not_found(self) -> None:
        raw = encode_intersect_not_found(TIP_A)
        msg = decode_n2c_server_message(raw)
        from vibe.cardano.network.chainsync import MsgIntersectNotFound
        assert isinstance(msg, MsgIntersectNotFound)

    def test_unknown_msg_id(self) -> None:
        raw = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown N2C server message ID"):
            decode_n2c_server_message(raw)

    def test_not_a_list(self) -> None:
        raw = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_n2c_server_message(raw)

    def test_roll_forward_wrong_length(self) -> None:
        raw = cbor2.dumps([2, b"\xde\xad"])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_n2c_server_message(raw)


# ---------------------------------------------------------------------------
# FSM state transitions
# ---------------------------------------------------------------------------


class TestLocalChainSyncProtocol:
    """Test the LocalChainSyncProtocol state machine definition."""

    def test_initial_state(self, protocol: LocalChainSyncProtocol) -> None:
        assert protocol.initial_state() == LocalChainSyncState.StIdle

    # --- Agency assignments ---

    def test_agency_st_idle_is_client(self, protocol: LocalChainSyncProtocol) -> None:
        assert protocol.agency(LocalChainSyncState.StIdle) == Agency.Client

    def test_agency_st_next_is_server(self, protocol: LocalChainSyncProtocol) -> None:
        assert protocol.agency(LocalChainSyncState.StNext) == Agency.Server

    def test_agency_st_intersect_is_server(self, protocol: LocalChainSyncProtocol) -> None:
        assert protocol.agency(LocalChainSyncState.StIntersect) == Agency.Server

    def test_agency_st_done_is_nobody(self, protocol: LocalChainSyncProtocol) -> None:
        assert protocol.agency(LocalChainSyncState.StDone) == Agency.Nobody

    # --- Valid messages per state ---

    def test_idle_valid_messages(self, protocol: LocalChainSyncProtocol) -> None:
        valid = protocol.valid_messages(LocalChainSyncState.StIdle)
        assert LcsMsgRequestNext in valid
        assert LcsMsgFindIntersect in valid
        assert LcsMsgDone in valid
        assert len(valid) == 3

    def test_next_valid_messages(self, protocol: LocalChainSyncProtocol) -> None:
        valid = protocol.valid_messages(LocalChainSyncState.StNext)
        assert LcsMsgAwaitReply in valid
        assert LcsMsgRollForward in valid
        assert LcsMsgRollBackward in valid
        assert len(valid) == 3

    def test_intersect_valid_messages(self, protocol: LocalChainSyncProtocol) -> None:
        valid = protocol.valid_messages(LocalChainSyncState.StIntersect)
        assert LcsMsgIntersectFound in valid
        assert LcsMsgIntersectNotFound in valid
        assert len(valid) == 2

    def test_done_valid_messages(self, protocol: LocalChainSyncProtocol) -> None:
        valid = protocol.valid_messages(LocalChainSyncState.StDone)
        assert len(valid) == 0

    # --- State transitions ---

    def test_request_next_transition(self) -> None:
        msg = LcsMsgRequestNext()
        assert msg.from_state == LocalChainSyncState.StIdle
        assert msg.to_state == LocalChainSyncState.StNext

    def test_await_reply_transition(self) -> None:
        msg = LcsMsgAwaitReply()
        assert msg.from_state == LocalChainSyncState.StNext
        assert msg.to_state == LocalChainSyncState.StNext

    def test_roll_forward_transition(self) -> None:
        msg = LcsMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        assert msg.from_state == LocalChainSyncState.StNext
        assert msg.to_state == LocalChainSyncState.StIdle

    def test_roll_backward_transition(self) -> None:
        msg = LcsMsgRollBackward(point=POINT_A, tip=TIP_A)
        assert msg.from_state == LocalChainSyncState.StNext
        assert msg.to_state == LocalChainSyncState.StIdle

    def test_find_intersect_transition(self) -> None:
        msg = LcsMsgFindIntersect(points=[POINT_A])
        assert msg.from_state == LocalChainSyncState.StIdle
        assert msg.to_state == LocalChainSyncState.StIntersect

    def test_intersect_found_transition(self) -> None:
        msg = LcsMsgIntersectFound(point=POINT_A, tip=TIP_A)
        assert msg.from_state == LocalChainSyncState.StIntersect
        assert msg.to_state == LocalChainSyncState.StIdle

    def test_intersect_not_found_transition(self) -> None:
        msg = LcsMsgIntersectNotFound(tip=TIP_A)
        assert msg.from_state == LocalChainSyncState.StIntersect
        assert msg.to_state == LocalChainSyncState.StIdle

    def test_done_transition(self) -> None:
        msg = LcsMsgDone()
        assert msg.from_state == LocalChainSyncState.StIdle
        assert msg.to_state == LocalChainSyncState.StDone


# ---------------------------------------------------------------------------
# Codec roundtrip tests
# ---------------------------------------------------------------------------


class TestLocalChainSyncCodec:
    """Test LocalChainSyncCodec encode/decode roundtrips."""

    def test_request_next_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgRequestNext()
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgRequestNext)

    def test_find_intersect_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgFindIntersect(points=[POINT_A, ORIGIN])
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgFindIntersect)
        assert decoded.points == [POINT_A, ORIGIN]

    def test_done_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgDone()
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgDone)

    def test_await_reply_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgAwaitReply()
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgAwaitReply)

    def test_roll_forward_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        """N2C RollForward carries a full block."""
        msg = LcsMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgRollForward)
        assert decoded.block == SAMPLE_BLOCK
        assert decoded.tip == TIP_A

    def test_roll_backward_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgRollBackward(point=POINT_A, tip=TIP_B)
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgRollBackward)
        assert decoded.point == POINT_A
        assert decoded.tip == TIP_B

    def test_intersect_found_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgIntersectFound(point=POINT_B, tip=TIP_C)
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgIntersectFound)
        assert decoded.point == POINT_B
        assert decoded.tip == TIP_C

    def test_intersect_not_found_roundtrip(self, codec: LocalChainSyncCodec) -> None:
        msg = LcsMsgIntersectNotFound(tip=TIP_A)
        data = codec.encode(msg)
        decoded = codec.decode(data)
        assert isinstance(decoded, LcsMsgIntersectNotFound)
        assert decoded.tip == TIP_A

    def test_unknown_message_type_raises(self, codec: LocalChainSyncCodec) -> None:
        """Encoding an unknown message type raises CodecError."""

        class FakeMsg(Message[LocalChainSyncState]):
            pass

        msg = FakeMsg(
            from_state=LocalChainSyncState.StIdle,
            to_state=LocalChainSyncState.StIdle,
        )
        with pytest.raises(CodecError, match="Unknown local chain-sync"):
            codec.encode(msg)

    def test_decode_garbage_raises(self, codec: LocalChainSyncCodec) -> None:
        with pytest.raises(CodecError, match="Failed to decode"):
            codec.decode(b"\xff\xff\xff")

    def test_full_message_cycle(self, codec: LocalChainSyncCodec) -> None:
        """Encode all message types, decode, re-encode — bytes must match."""
        messages = [
            LcsMsgRequestNext(),
            LcsMsgFindIntersect(points=[POINT_A, POINT_B, ORIGIN]),
            LcsMsgDone(),
            LcsMsgAwaitReply(),
            LcsMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A),
            LcsMsgRollBackward(point=POINT_A, tip=TIP_B),
            LcsMsgRollBackward(point=ORIGIN, tip=GENESIS_TIP),
            LcsMsgIntersectFound(point=POINT_B, tip=TIP_C),
            LcsMsgIntersectFound(point=ORIGIN, tip=GENESIS_TIP),
            LcsMsgIntersectNotFound(tip=TIP_A),
        ]
        for msg in messages:
            encoded1 = codec.encode(msg)
            decoded = codec.decode(encoded1)
            encoded2 = codec.encode(decoded)
            assert encoded1 == encoded2, (
                f"Roundtrip failed for {type(msg).__name__}: "
                f"{encoded1.hex()} != {encoded2.hex()}"
            )


# ---------------------------------------------------------------------------
# Codec split tests — verify decode handles fragmented CBOR
# ---------------------------------------------------------------------------


class TestCodecSplitDecode:
    """Test that encoded messages can be decoded from reassembled chunks.

    In real usage, CBOR messages may arrive across multiple mux segments.
    The codec receives the fully reassembled bytes, but we verify that
    concatenating chunks and decoding works correctly.
    """

    def test_two_chunk_roll_forward(self, codec: LocalChainSyncCodec) -> None:
        """Split a RollForward into 2 chunks, reassemble, decode."""
        msg = LcsMsgRollForward(block=SAMPLE_BLOCK, tip=TIP_A)
        data = codec.encode(msg)
        mid = len(data) // 2
        chunk1, chunk2 = data[:mid], data[mid:]
        reassembled = chunk1 + chunk2
        decoded = codec.decode(reassembled)
        assert isinstance(decoded, LcsMsgRollForward)
        assert decoded.block == SAMPLE_BLOCK

    def test_three_chunk_find_intersect(self, codec: LocalChainSyncCodec) -> None:
        """Split a FindIntersect into 3 chunks, reassemble, decode."""
        msg = LcsMsgFindIntersect(points=[POINT_A, POINT_B, POINT_C])
        data = codec.encode(msg)
        third = len(data) // 3
        chunks = [data[:third], data[third : 2 * third], data[2 * third :]]
        reassembled = b"".join(chunks)
        decoded = codec.decode(reassembled)
        assert isinstance(decoded, LcsMsgFindIntersect)
        assert len(decoded.points) == 3

    def test_two_chunk_intersect_found(self, codec: LocalChainSyncCodec) -> None:
        """Split IntersectFound into 2 chunks."""
        msg = LcsMsgIntersectFound(point=POINT_A, tip=TIP_B)
        data = codec.encode(msg)
        mid = len(data) // 2
        reassembled = data[:mid] + data[mid:]
        decoded = codec.decode(reassembled)
        assert isinstance(decoded, LcsMsgIntersectFound)
        assert decoded.point == POINT_A

    def test_two_chunk_roll_backward(self, codec: LocalChainSyncCodec) -> None:
        """Split RollBackward into 2 chunks."""
        msg = LcsMsgRollBackward(point=POINT_B, tip=TIP_C)
        data = codec.encode(msg)
        mid = len(data) // 2
        reassembled = data[:mid] + data[mid:]
        decoded = codec.decode(reassembled)
        assert isinstance(decoded, LcsMsgRollBackward)
        assert decoded.point == POINT_B


# ---------------------------------------------------------------------------
# Server tests — find_intersect
# ---------------------------------------------------------------------------


class TestServerFindIntersect:
    """Test LocalChainSyncServer.handle_find_intersect."""

    @pytest.mark.asyncio
    async def test_intersect_found_known_point(self) -> None:
        """Server finds intersection with a known point."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK), (POINT_B, SAMPLE_BLOCK_B)],
            tip=TIP_B,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        # Client sends FindIntersect with known points
        await channel.inject(encode_find_intersect([POINT_B, POINT_A]))
        msg = await runner.recv_message()
        assert isinstance(msg, LcsMsgFindIntersect)

        await server.handle_find_intersect(msg.points)

        # Server should respond with IntersectFound
        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgIntersectFound)
        assert response.point == POINT_B
        assert response.tip == TIP_B

        # Server should have updated client_point
        assert server.client_point == POINT_B

    @pytest.mark.asyncio
    async def test_intersect_not_found(self) -> None:
        """Server responds IntersectNotFound for unknown points."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK)],
            tip=TIP_A,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        # Client sends FindIntersect with unknown points (no Origin)
        unknown_point = Point(slot=999, hash=b"\xff" * 32)
        await channel.inject(encode_find_intersect([unknown_point]))
        msg = await runner.recv_message()

        await server.handle_find_intersect(msg.points)

        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgIntersectNotFound)
        assert response.tip == TIP_A

    @pytest.mark.asyncio
    async def test_intersect_at_origin(self) -> None:
        """Origin always intersects (genesis is always on chain)."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK)],
            tip=TIP_A,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        await channel.inject(encode_find_intersect([ORIGIN]))
        msg = await runner.recv_message()

        await server.handle_find_intersect(msg.points)

        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgIntersectFound)
        assert response.point == ORIGIN


# ---------------------------------------------------------------------------
# Server tests — request_next (roll forward)
# ---------------------------------------------------------------------------


class TestServerRollForward:
    """Test LocalChainSyncServer.handle_request_next serving blocks."""

    @pytest.mark.asyncio
    async def test_roll_forward_from_origin(self) -> None:
        """Server rolls forward from origin to the first block."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK), (POINT_B, SAMPLE_BLOCK_B)],
            tip=TIP_B,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)
        # client_point starts at Origin

        # Client sends RequestNext
        await channel.inject(encode_request_next())
        msg = await runner.recv_message()
        assert isinstance(msg, LcsMsgRequestNext)

        await server.handle_request_next()

        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgRollForward)
        assert response.block == SAMPLE_BLOCK
        assert response.tip == TIP_B
        assert server.client_point == POINT_A

    @pytest.mark.asyncio
    async def test_sequential_roll_forward(self) -> None:
        """Server serves blocks sequentially."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK), (POINT_B, SAMPLE_BLOCK_B)],
            tip=TIP_B,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        # First request: should get block A
        await channel.inject(encode_request_next())
        msg = await runner.recv_message()
        await server.handle_request_next()
        response_bytes = await channel.drain()
        r1 = codec.decode(response_bytes)
        assert isinstance(r1, LcsMsgRollForward)
        assert r1.block == SAMPLE_BLOCK

        # Second request: should get block B
        await channel.inject(encode_request_next())
        msg = await runner.recv_message()
        await server.handle_request_next()
        response_bytes = await channel.drain()
        r2 = codec.decode(response_bytes)
        assert isinstance(r2, LcsMsgRollForward)
        assert r2.block == SAMPLE_BLOCK_B

    @pytest.mark.asyncio
    async def test_await_reply_at_tip(self) -> None:
        """Server sends AwaitReply when client is at the tip."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK)],
            tip=TIP_A,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        # Advance client to tip
        server._client_point = POINT_A

        # Client sends RequestNext — but we're at the tip
        await channel.inject(encode_request_next())
        msg = await runner.recv_message()

        # Run handle_request_next in background (it will block on wait_for_new_block)
        task = asyncio.create_task(server.handle_request_next())

        # Should get AwaitReply first
        response_bytes = await asyncio.wait_for(channel.drain(), timeout=1.0)
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgAwaitReply)

        # Add a new block — this should unblock the server
        chaindb.add_block(POINT_B, SAMPLE_BLOCK_B, TIP_B)

        # Now we should get RollForward with the new block
        response_bytes = await asyncio.wait_for(channel.drain(), timeout=1.0)
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgRollForward)
        assert response.block == SAMPLE_BLOCK_B

        await asyncio.wait_for(task, timeout=1.0)


# ---------------------------------------------------------------------------
# Server tests — roll backward on fork
# ---------------------------------------------------------------------------


class TestServerRollBackward:
    """Test LocalChainSyncServer rollback behavior on chain forks."""

    @pytest.mark.asyncio
    async def test_roll_backward_on_fork(self) -> None:
        """Server rolls backward when client's point is no longer on chain."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK), (POINT_C, SAMPLE_BLOCK_B)],
            tip=TIP_C,
        )
        # Simulate fork: POINT_B is no longer on chain, roll back to POINT_A
        chaindb.set_fork(POINT_B, POINT_A)

        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)
        server._client_point = POINT_B  # Client thinks it's at B

        # Client sends RequestNext
        await channel.inject(encode_request_next())
        msg = await runner.recv_message()

        await server.handle_request_next()

        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgRollBackward)
        assert response.point == POINT_A
        assert response.tip == TIP_C

        # Client point should be updated to fork point
        assert server.client_point == POINT_A

    @pytest.mark.asyncio
    async def test_roll_backward_to_origin(self) -> None:
        """Fork all the way back to origin."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_C, SAMPLE_BLOCK_B)],
            tip=TIP_C,
        )
        chaindb.set_fork(POINT_A, ORIGIN)

        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)
        server._client_point = POINT_A

        await channel.inject(encode_request_next())
        msg = await runner.recv_message()

        await server.handle_request_next()

        response_bytes = await channel.drain()
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgRollBackward)
        assert response.point == ORIGIN


# ---------------------------------------------------------------------------
# Server run loop test
# ---------------------------------------------------------------------------


class TestServerRunLoop:
    """Test the full server run loop."""

    @pytest.mark.asyncio
    async def test_run_find_intersect_then_request_next_then_done(self) -> None:
        """Full lifecycle: FindIntersect -> RequestNext -> Done."""
        channel = FakeChannel()
        chaindb = MockChainDB(
            chain=[(POINT_A, SAMPLE_BLOCK)],
            tip=TIP_A,
        )
        protocol = LocalChainSyncProtocol()
        codec = LocalChainSyncCodec()
        runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=protocol,
            codec=codec,
            channel=channel,
        )
        server = LocalChainSyncServer(runner=runner, chaindb=chaindb)

        # Run server in background
        server_task = asyncio.create_task(server.run())

        # 1. Client sends FindIntersect
        await channel.inject(encode_find_intersect([ORIGIN]))
        response_bytes = await asyncio.wait_for(channel.drain(), timeout=1.0)
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgIntersectFound)

        # 2. Client sends RequestNext
        await channel.inject(encode_request_next())
        response_bytes = await asyncio.wait_for(channel.drain(), timeout=1.0)
        response = codec.decode(response_bytes)
        assert isinstance(response, LcsMsgRollForward)
        assert response.block == SAMPLE_BLOCK

        # 3. Client sends Done
        await channel.inject(encode_done())
        await asyncio.wait_for(server_task, timeout=1.0)

        assert server.is_done


# ---------------------------------------------------------------------------
# Factory helper test
# ---------------------------------------------------------------------------


class TestCreateServer:
    """Test the create_local_chainsync_server factory."""

    def test_creates_server_with_responder_role(self) -> None:
        channel = FakeChannel()
        chaindb = MockChainDB()
        server = create_local_chainsync_server(channel, chaindb)
        assert isinstance(server, LocalChainSyncServer)
        assert server.state == LocalChainSyncState.StIdle
        assert server.client_point == ORIGIN
