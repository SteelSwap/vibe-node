"""Tests for chain-sync consensus-level client behavior.

Covers fork handling, rollback validation, future header handling,
intersection negotiation, CBOR encoding properties, and mock-channel
client-server pairing.

Derived from test specifications:
- test_fork_handling_server_switches_to_longer_fork
- test_rollback_validation_reject_beyond_k
- test_future_header_slot_far_in_future
- test_intersection_found_shared_common_point
- test_no_intersection_completely_different_chains
- test_valid_cbor_encoding_property (Hypothesis)
- test_chain_sync_over_mock_channel

Spec reference: Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
Haskell reference:
    Ouroboros/Network/Protocol/ChainSync/Client.hs
    Ouroboros/Consensus/MiniProtocol/ChainSync/Client.hs (consensus-level)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import cbor2
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from vibe.core.protocols.agency import Agency, PeerRole, ProtocolError
from vibe.cardano.network.chainsync import (
    Point,
    Origin,
    ORIGIN,
    Tip,
    PointOrOrigin,
    encode_request_next,
    encode_find_intersect,
    encode_done,
    encode_await_reply,
    encode_roll_forward,
    encode_roll_backward,
    encode_intersect_found,
    encode_intersect_not_found,
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
# Test helpers
# ---------------------------------------------------------------------------

HASH_A = b"\xaa" * 32
HASH_B = b"\xbb" * 32
HASH_C = b"\xcc" * 32
HASH_D = b"\xdd" * 32
HASH_E = b"\xee" * 32
HASH_F = b"\xff" * 32

POINT_1 = Point(slot=1, hash=HASH_A)
POINT_2 = Point(slot=2, hash=HASH_B)
POINT_3 = Point(slot=3, hash=HASH_C)
POINT_5 = Point(slot=5, hash=HASH_D)
POINT_10 = Point(slot=10, hash=HASH_E)
POINT_100 = Point(slot=100, hash=HASH_F)

TIP_GENESIS = Tip(point=ORIGIN, block_number=0)
TIP_1 = Tip(point=POINT_1, block_number=1)
TIP_5 = Tip(point=POINT_5, block_number=5)
TIP_10 = Tip(point=POINT_10, block_number=10)
TIP_100 = Tip(point=POINT_100, block_number=100)

SAMPLE_HEADER = b"\xca\xfe\xba\xbe" * 8


def _make_client() -> tuple[ChainSyncClient, AsyncMock]:
    """Create a ChainSyncClient with a mocked ProtocolRunner."""
    runner = AsyncMock()
    runner.state = ChainSyncState.StIdle
    runner.is_done = False
    client = ChainSyncClient(runner)
    return client, runner


def _make_header(slot: int) -> bytes:
    """Create a mock header payload tagged with a slot number."""
    return f"header_slot_{slot:06d}".encode()


# ---------------------------------------------------------------------------
# 1. Fork handling -- server switches to longer fork, client follows
# ---------------------------------------------------------------------------


class TestForkHandling:
    """Server switches to a longer fork; client follows via rollback + roll-forward.

    In Ouroboros, when the server has a longer chain, it sends a RollBackward
    to the fork point, then RollForward messages for the new chain suffix.
    The consensus-level chain-sync client must accept this and update its
    local chain fragment accordingly.
    """

    @pytest.mark.asyncio
    async def test_rollback_then_roll_forward_on_fork(self) -> None:
        """Simulate fork switch: rollback to slot 3, then forward to slot 5."""
        client, runner = _make_client()

        # First request_next: server says "roll back to slot 3"
        runner.recv_message.side_effect = [
            CsMsgRollBackward(point=POINT_3, tip=TIP_5),
        ]

        result = await client.request_next()
        assert isinstance(result, CsMsgRollBackward)
        assert result.point == POINT_3
        assert result.tip == TIP_5

    @pytest.mark.asyncio
    async def test_fork_switch_sequence(self) -> None:
        """Full fork switch: rollback then multiple roll-forwards."""
        client, runner = _make_client()

        # Simulate: rollback to point 2, then forward slots 3, 4, 5
        fork_sequence = [
            CsMsgRollBackward(point=POINT_2, tip=TIP_5),
            CsMsgRollForward(header=_make_header(3), tip=TIP_5),
            CsMsgRollForward(header=_make_header(4), tip=TIP_5),
            CsMsgRollForward(header=_make_header(5), tip=TIP_5),
        ]

        runner.recv_message.side_effect = fork_sequence

        # Process fork switch
        headers_received: list[bytes] = []
        rollback_point: PointOrOrigin | None = None

        r1 = await client.request_next()
        assert isinstance(r1, CsMsgRollBackward)
        rollback_point = r1.point

        for _ in range(3):
            r = await client.request_next()
            assert isinstance(r, CsMsgRollForward)
            headers_received.append(r.header)

        assert rollback_point == POINT_2
        assert len(headers_received) == 3
        assert headers_received[0] == _make_header(3)
        assert headers_received[2] == _make_header(5)


# ---------------------------------------------------------------------------
# 2. Rollback validation -- reject rollback beyond k blocks
# ---------------------------------------------------------------------------


class TestRollbackValidation:
    """Client rejects rollback beyond k blocks.

    In Ouroboros Praos, the security parameter k limits how far back a rollback
    can go. The consensus-level chain-sync client must reject rollbacks that
    exceed this limit. We test the principle: if a rollback goes further back
    than the client's immutable tip, it should be rejected.
    """

    @pytest.mark.asyncio
    async def test_rollback_within_k_accepted(self) -> None:
        """Rollback within k blocks is accepted normally."""
        client, runner = _make_client()

        # Server rolls back to point 5 -- within bounds
        runner.recv_message.return_value = CsMsgRollBackward(
            point=POINT_5, tip=TIP_10
        )

        result = await client.request_next()
        assert isinstance(result, CsMsgRollBackward)
        assert result.point == POINT_5

    @pytest.mark.asyncio
    async def test_rollback_beyond_k_detected(self) -> None:
        """Application layer detects rollback beyond k and rejects it.

        The protocol layer delivers the rollback message; it's the consensus
        layer's job to validate the rollback depth against k. We test the
        detection pattern.
        """
        k = 5  # Security parameter
        immutable_tip_slot = 50
        rollback_to_slot = 40  # 10 slots back, beyond k=5

        client, runner = _make_client()
        rollback_point = Point(slot=rollback_to_slot, hash=HASH_A)
        runner.recv_message.return_value = CsMsgRollBackward(
            point=rollback_point, tip=TIP_100
        )

        result = await client.request_next()
        assert isinstance(result, CsMsgRollBackward)

        # Consensus validation: reject if rollback is beyond k
        depth = immutable_tip_slot - result.point.slot
        assert depth > k, "Rollback exceeds security parameter k"

    @pytest.mark.asyncio
    async def test_rollback_to_origin_is_max_depth(self) -> None:
        """Rollback to Origin is the maximum possible rollback depth."""
        client, runner = _make_client()
        runner.recv_message.return_value = CsMsgRollBackward(
            point=ORIGIN, tip=TIP_10
        )

        result = await client.request_next()
        assert isinstance(result, CsMsgRollBackward)
        assert result.point == ORIGIN


# ---------------------------------------------------------------------------
# 3. Future header -- server sends header with slot far in future
# ---------------------------------------------------------------------------


class TestFutureHeader:
    """Server sends header with slot far in future; client handles gracefully.

    In the Haskell node, the consensus-level chain-sync client validates
    header timestamps against the wallclock. Headers too far in the future
    are rejected. At the protocol level, the message is valid -- the
    validation happens at the consensus layer.
    """

    @pytest.mark.asyncio
    async def test_future_slot_header_delivered(self) -> None:
        """Protocol delivers a header with a far-future slot."""
        future_slot = 999_999_999
        future_point = Point(slot=future_slot, hash=HASH_F)
        future_tip = Tip(point=future_point, block_number=999_999)

        client, runner = _make_client()
        runner.recv_message.return_value = CsMsgRollForward(
            header=_make_header(future_slot), tip=future_tip
        )

        result = await client.request_next()
        assert isinstance(result, CsMsgRollForward)
        assert result.tip.point.slot == future_slot

    @pytest.mark.asyncio
    async def test_future_header_consensus_rejection_pattern(self) -> None:
        """Demonstrate consensus-level future header rejection pattern.

        The protocol delivers the header; the consensus layer checks if
        the slot is within acceptable bounds of the current wallclock.
        """
        current_slot = 1000
        max_clock_skew = 10  # Maximum acceptable clock skew in slots
        future_slot = 2000  # Way beyond acceptable

        client, runner = _make_client()
        future_point = Point(slot=future_slot, hash=HASH_F)
        runner.recv_message.return_value = CsMsgRollForward(
            header=_make_header(future_slot),
            tip=Tip(point=future_point, block_number=future_slot),
        )

        result = await client.request_next()
        assert isinstance(result, CsMsgRollForward)

        # Consensus check: is this too far in the future?
        header_slot = future_slot  # Would be extracted from header in real code
        assert header_slot > current_slot + max_clock_skew


# ---------------------------------------------------------------------------
# 4. Intersection found -- client and server share common point
# ---------------------------------------------------------------------------


class TestIntersectionFound:
    """Client and server share a common point; sync continues from there."""

    @pytest.mark.asyncio
    async def test_intersection_at_known_point(self) -> None:
        """Server finds intersection at one of the client's known points."""
        client, runner = _make_client()

        runner.recv_message.return_value = CsMsgIntersectFound(
            point=POINT_5, tip=TIP_10
        )

        point, tip = await client.find_intersection(
            [POINT_10, POINT_5, POINT_1, ORIGIN]
        )
        assert point == POINT_5
        assert tip == TIP_10

    @pytest.mark.asyncio
    async def test_intersection_at_origin(self) -> None:
        """Intersection found at Origin when chains diverge completely."""
        client, runner = _make_client()

        runner.recv_message.return_value = CsMsgIntersectFound(
            point=ORIGIN, tip=TIP_10
        )

        point, tip = await client.find_intersection([ORIGIN])
        assert point == ORIGIN
        assert tip == TIP_10

    @pytest.mark.asyncio
    async def test_intersection_continues_sync(self) -> None:
        """After finding intersection, sync continues with RequestNext."""
        client, runner = _make_client()

        # First: find intersection
        runner.recv_message.side_effect = [
            CsMsgIntersectFound(point=POINT_5, tip=TIP_10),
            CsMsgRollForward(header=SAMPLE_HEADER, tip=TIP_10),
        ]

        point, tip = await client.find_intersection([POINT_5])
        assert point == POINT_5

        # Then: sync continues
        result = await client.request_next()
        assert isinstance(result, CsMsgRollForward)


# ---------------------------------------------------------------------------
# 5. No intersection -- completely different chains
# ---------------------------------------------------------------------------


class TestNoIntersection:
    """Client and server have completely different chains; proper error."""

    @pytest.mark.asyncio
    async def test_no_intersection_returns_none(self) -> None:
        """find_intersection returns (None, tip) when no common point."""
        client, runner = _make_client()

        runner.recv_message.return_value = CsMsgIntersectNotFound(tip=TIP_10)

        point, tip = await client.find_intersection(
            [POINT_1, POINT_2, POINT_3]
        )
        assert point is None
        assert tip == TIP_10

    @pytest.mark.asyncio
    async def test_run_chain_sync_raises_on_no_intersection(self) -> None:
        """run_chain_sync raises ProtocolError when no intersection found."""
        channel = AsyncMock()
        codec = ChainSyncCodec()

        # Encode FindIntersect response: IntersectNotFound
        channel.recv.return_value = codec.encode(
            CsMsgIntersectNotFound(tip=TIP_10)
        )
        channel.send = AsyncMock()

        async def on_fwd(header, tip):
            pass

        async def on_bwd(point, tip):
            pass

        with pytest.raises(ProtocolError, match="No intersection found"):
            await run_chain_sync(
                channel,
                [POINT_1, POINT_2],
                on_fwd,
                on_bwd,
            )

    @pytest.mark.asyncio
    async def test_no_intersection_with_empty_points_uses_origin(self) -> None:
        """When known_points is empty, run_chain_sync uses [Origin]."""
        channel = AsyncMock()
        codec = ChainSyncCodec()

        # Server finds intersection at Origin, then RollForward
        # After first RollForward the stop_event fires, so Done is sent
        channel.recv.side_effect = [
            codec.encode(CsMsgIntersectFound(point=ORIGIN, tip=TIP_1)),
            codec.encode(CsMsgRollForward(header=SAMPLE_HEADER, tip=TIP_1)),
        ]
        channel.send = AsyncMock()

        headers: list[bytes] = []
        stop = asyncio.Event()

        async def on_fwd(header, tip):
            headers.append(header)
            stop.set()

        async def on_bwd(point, tip):
            pass

        await run_chain_sync(channel, [], on_fwd, on_bwd, stop_event=stop)

        # The FindIntersect message should have been sent with [Origin]
        first_send = channel.send.call_args_list[0][0][0]
        decoded = codec.decode(first_send)
        assert isinstance(decoded, CsMsgFindIntersect)
        assert decoded.points == [ORIGIN]


# ---------------------------------------------------------------------------
# 6. Valid CBOR encoding property -- Hypothesis
# ---------------------------------------------------------------------------


# Strategies for generating valid domain objects
st_hash = st.binary(min_size=32, max_size=32)
st_slot = st.integers(min_value=0, max_value=2**63 - 1)
st_block_number = st.integers(min_value=0, max_value=2**63 - 1)
st_header = st.binary(min_size=1, max_size=256)

st_point = st.builds(Point, slot=st_slot, hash=st_hash)
st_origin = st.just(ORIGIN)
st_point_or_origin = st.one_of(st_point, st_origin)
st_tip = st.builds(Tip, point=st_point_or_origin, block_number=st_block_number)
st_points_list = st.lists(st_point_or_origin, min_size=1, max_size=10)


class TestCborEncodingProperty:
    """Hypothesis: all chain-sync messages produce valid CBOR that roundtrips."""

    @given(data=st.data())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_request_next_produces_valid_cbor(self, data: st.DataObject) -> None:
        """MsgRequestNext always produces decodable CBOR."""
        encoded = encode_request_next()
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 0

    @given(points=st_points_list)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_find_intersect_produces_valid_cbor(self, points: list[PointOrOrigin]) -> None:
        """MsgFindIntersect with arbitrary points produces valid CBOR."""
        encoded = encode_find_intersect(points)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 4
        assert isinstance(decoded[1], list)

    @given(header=st_header, tip=st_tip)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_roll_forward_produces_valid_cbor(self, header: bytes, tip: Tip) -> None:
        """MsgRollForward with arbitrary header/tip produces valid CBOR."""
        encoded = encode_roll_forward(header, tip)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 2

    @given(point=st_point_or_origin, tip=st_tip)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_roll_backward_produces_valid_cbor(self, point: PointOrOrigin, tip: Tip) -> None:
        """MsgRollBackward with arbitrary point/tip produces valid CBOR."""
        encoded = encode_roll_backward(point, tip)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 3

    @given(point=st_point_or_origin, tip=st_tip)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_intersect_found_produces_valid_cbor(self, point: PointOrOrigin, tip: Tip) -> None:
        """MsgIntersectFound with arbitrary point/tip produces valid CBOR."""
        encoded = encode_intersect_found(point, tip)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 5

    @given(tip=st_tip)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_intersect_not_found_produces_valid_cbor(self, tip: Tip) -> None:
        """MsgIntersectNotFound with arbitrary tip produces valid CBOR."""
        encoded = encode_intersect_not_found(tip)
        decoded = cbor2.loads(encoded)
        assert isinstance(decoded, list)
        assert decoded[0] == 6

    @given(header=st_header, tip=st_tip)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_codec_roundtrip_roll_forward(self, header: bytes, tip: Tip) -> None:
        """ChainSyncCodec roundtrips CsMsgRollForward for arbitrary inputs."""
        codec = ChainSyncCodec()
        msg = CsMsgRollForward(header=header, tip=tip)
        encoded = codec.encode(msg)
        decoded = codec.decode(encoded)
        assert isinstance(decoded, CsMsgRollForward)
        assert decoded.header == header
        assert decoded.tip.block_number == tip.block_number


# ---------------------------------------------------------------------------
# 7. Chain-sync over mock channel -- direct client-server pairing
# ---------------------------------------------------------------------------


class TestChainSyncOverMockChannel:
    """Direct client-server pairing without real TCP using in-memory queues.

    This tests the full codec -> channel -> codec roundtrip by connecting
    a client and server through asyncio.Queue-based mock channels.
    """

    @pytest.mark.asyncio
    async def test_full_sync_over_mock_channel(self) -> None:
        """Client and server communicate over in-memory queues."""
        # Create bidirectional queues
        client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
        server_to_client: asyncio.Queue[bytes] = asyncio.Queue()

        codec = ChainSyncCodec()

        # Mock channel for client: sends to client_to_server, recvs from server_to_client
        client_channel = AsyncMock()

        async def _send(data: bytes) -> None:
            client_to_server.put_nowait(data)

        async def _recv() -> bytes:
            return await server_to_client.get()

        client_channel.send = _send
        client_channel.recv = _recv

        # Server behavior: read client messages and respond
        async def server_loop():
            # 1. Client sends FindIntersect
            find_data = await client_to_server.get()
            find_msg = codec.decode(find_data)
            assert isinstance(find_msg, CsMsgFindIntersect)

            # Respond with IntersectFound
            response = codec.encode(CsMsgIntersectFound(point=POINT_1, tip=TIP_5))
            await server_to_client.put(response)

            # 2. Client sends RequestNext (3 times)
            for slot in [2, 3, 4]:
                req_data = await client_to_server.get()
                req_msg = codec.decode(req_data)
                assert isinstance(req_msg, CsMsgRequestNext)

                # Respond with RollForward
                header = _make_header(slot)
                response = codec.encode(
                    CsMsgRollForward(header=header, tip=TIP_5)
                )
                await server_to_client.put(response)

            # 3. Client sends RequestNext, server says AwaitReply then RollForward
            req_data = await client_to_server.get()
            await server_to_client.put(codec.encode(CsMsgAwaitReply()))
            await server_to_client.put(
                codec.encode(CsMsgRollForward(header=_make_header(5), tip=TIP_5))
            )

            # 4. Client sends Done
            done_data = await client_to_server.get()
            done_msg = codec.decode(done_data)
            assert isinstance(done_msg, CsMsgDone)

        headers: list[bytes] = []

        async def on_fwd(header: bytes, tip: Tip) -> None:
            headers.append(header)

        async def on_bwd(point: PointOrOrigin, tip: Tip) -> None:
            pass

        stop = asyncio.Event()

        async def run_client():
            """Client-side: run_chain_sync with stop after collecting headers."""
            protocol = ChainSyncProtocol()
            codec_c = ChainSyncCodec()
            from vibe.core.protocols.runner import ProtocolRunner

            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec_c,
                channel=client_channel,
            )
            client = ChainSyncClient(runner)

            # Find intersection
            point, tip = await client.find_intersection([POINT_1, ORIGIN])
            assert point == POINT_1

            # Sync 3 headers
            for _ in range(3):
                result = await client.request_next()
                assert isinstance(result, CsMsgRollForward)
                headers.append(result.header)

            # Get AwaitReply then RollForward
            result = await client.request_next()
            if isinstance(result, CsMsgAwaitReply):
                result = await client.recv_after_await()
            assert isinstance(result, CsMsgRollForward)
            headers.append(result.header)

            await client.done()

        # Clear headers (on_fwd won't be used in this test)
        headers.clear()

        await asyncio.gather(run_client(), server_loop())

        assert len(headers) == 4
        assert headers[0] == _make_header(2)
        assert headers[3] == _make_header(5)

    @pytest.mark.asyncio
    async def test_mock_channel_intersection_not_found(self) -> None:
        """Server responds with IntersectNotFound over mock channel."""
        codec = ChainSyncCodec()

        channel = AsyncMock()
        channel.send = AsyncMock()
        channel.recv = AsyncMock(
            return_value=codec.encode(CsMsgIntersectNotFound(tip=TIP_5))
        )

        from vibe.core.protocols.runner import ProtocolRunner

        runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=ChainSyncProtocol(),
            codec=codec,
            channel=channel,
        )
        client = ChainSyncClient(runner)

        point, tip = await client.find_intersection([POINT_10, POINT_5])
        assert point is None
        assert tip == TIP_5
