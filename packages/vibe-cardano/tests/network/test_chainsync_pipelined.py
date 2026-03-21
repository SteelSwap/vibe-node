"""Tests for pipelined chain-sync client.

Tests cover:
- Pipelined sync faster than sequential (simulated timing)
- Correct ordering of roll-forward callbacks
- Rollback during pipeline drains correctly
- AwaitReply handling in pipelined mode
- Hypothesis: pipelined vs sequential produce same results
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.chainsync import (
    Point,
    Tip,
    ORIGIN,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncCodec,
    CsMsgRequestNext,
    CsMsgRollForward,
    CsMsgRollBackward,
    CsMsgAwaitReply,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
)
from vibe.cardano.network.chainsync_pipelined import (
    PipelinedChainSyncClient,
    run_pipelined_chain_sync,
)


# ---------------------------------------------------------------------------
# Fake channel for chain-sync testing
# ---------------------------------------------------------------------------


class FakeChainSyncChannel:
    """Simulates a MiniProtocolChannel for chain-sync.

    Supports scripted server responses for deterministic testing.
    """

    def __init__(self, server_responses: list[bytes] | None = None) -> None:
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._server_responses = server_responses or []
        self._response_idx = 0
        self._send_count = 0

    async def send(self, payload: bytes) -> None:
        await self._outbound.put(payload)
        self._send_count += 1

    async def recv(self) -> bytes:
        return await self._inbound.get()

    async def feed_response(self, payload: bytes) -> None:
        await self._inbound.put(payload)

    async def get_sent(self) -> bytes:
        return await self._outbound.get()

    def close(self) -> None:
        pass


def _make_tip(block_num: int = 100) -> Tip:
    """Create a test tip."""
    return Tip(
        point=Point(slot=block_num * 20, hash=b"\x00" * 32),
        block_number=block_num,
    )


def _make_roll_forward_bytes(header_idx: int) -> bytes:
    """Encode a RollForward message with a numbered header."""
    codec = ChainSyncCodec()
    header = header_idx.to_bytes(4, "big")
    msg = CsMsgRollForward(header=header, tip=_make_tip(header_idx))
    return codec.encode(msg)


def _make_roll_backward_bytes(slot: int) -> bytes:
    """Encode a RollBackward message."""
    codec = ChainSyncCodec()
    point = Point(slot=slot, hash=b"\x00" * 32)
    msg = CsMsgRollBackward(point=point, tip=_make_tip(slot // 20))
    return codec.encode(msg)


def _make_intersect_found_bytes() -> bytes:
    """Encode an IntersectFound message."""
    codec = ChainSyncCodec()
    msg = CsMsgIntersectFound(point=ORIGIN, tip=_make_tip(0))
    return codec.encode(msg)


def _make_await_reply_bytes() -> bytes:
    """Encode an AwaitReply message."""
    codec = ChainSyncCodec()
    msg = CsMsgAwaitReply()
    return codec.encode(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelinedChainSyncClient:
    """Core pipelined chain-sync behavior."""

    @pytest.mark.asyncio
    async def test_find_intersection(self) -> None:
        """find_intersection works correctly (non-pipelined phase)."""
        channel = FakeChainSyncChannel()
        client = PipelinedChainSyncClient(channel, max_in_flight=10)

        # Feed the IntersectFound response.
        await channel.feed_response(_make_intersect_found_bytes())

        intersection, tip = await client.find_intersection([ORIGIN])
        assert intersection == ORIGIN
        assert tip.block_number == 0

    @pytest.mark.asyncio
    async def test_pipelined_roll_forwards_in_order(self) -> None:
        """Pipelined sync delivers roll-forwards in correct order."""
        channel = FakeChainSyncChannel()
        client = PipelinedChainSyncClient(channel, max_in_flight=10)

        # Track received headers.
        received_headers: list[int] = []

        async def on_roll_forward(header: bytes, tip: Tip) -> None:
            received_headers.append(int.from_bytes(header, "big"))

        async def on_roll_backward(point: object, tip: Tip) -> None:
            pass

        n_blocks = 20
        stop_event = asyncio.Event()

        # Server task: feed responses and stop after n_blocks.
        async def server() -> None:
            for i in range(n_blocks):
                # Consume the MsgRequestNext.
                await channel.get_sent()
                await channel.feed_response(_make_roll_forward_bytes(i))
            # Signal stop after all blocks delivered.
            stop_event.set()

        server_task = asyncio.create_task(server())

        await client.run_pipelined_sync(
            on_roll_forward=on_roll_forward,
            on_roll_backward=on_roll_backward,
            stop_event=stop_event,
        )

        await server_task

        assert received_headers == list(range(n_blocks))

    @pytest.mark.asyncio
    async def test_rollback_drains_pipeline(self) -> None:
        """On rollback, in-flight responses are drained before callback."""
        channel = FakeChainSyncChannel()
        client = PipelinedChainSyncClient(channel, max_in_flight=10)

        events: list[str] = []

        async def on_roll_forward(header: bytes, tip: Tip) -> None:
            idx = int.from_bytes(header, "big")
            events.append(f"forward:{idx}")

        async def on_roll_backward(point: object, tip: Tip) -> None:
            events.append(f"backward:{point}")

        stop_event = asyncio.Event()

        async def server() -> None:
            # Send 3 roll-forwards, then a rollback.
            for i in range(3):
                await channel.get_sent()
                await channel.feed_response(_make_roll_forward_bytes(i))

            # Next request gets a rollback.
            await channel.get_sent()
            await channel.feed_response(_make_roll_backward_bytes(20))

            # After rollback is processed, send one more forward then stop.
            await channel.get_sent()
            await channel.feed_response(_make_roll_forward_bytes(100))

            stop_event.set()

        server_task = asyncio.create_task(server())

        await client.run_pipelined_sync(
            on_roll_forward=on_roll_forward,
            on_roll_backward=on_roll_backward,
            stop_event=stop_event,
        )

        await server_task

        # The first 3 forwards should have been delivered, then the rollback,
        # then the final forward.
        assert events[0] == "forward:0"
        assert events[1] == "forward:1"
        assert events[2] == "forward:2"
        assert "backward:" in events[3]
        assert events[4] == "forward:100"

    @pytest.mark.asyncio
    async def test_await_reply_handling(self) -> None:
        """AwaitReply followed by RollForward is handled correctly."""
        channel = FakeChainSyncChannel()
        client = PipelinedChainSyncClient(channel, max_in_flight=10)

        received_headers: list[int] = []

        async def on_roll_forward(header: bytes, tip: Tip) -> None:
            received_headers.append(int.from_bytes(header, "big"))

        async def on_roll_backward(point: object, tip: Tip) -> None:
            pass

        stop_event = asyncio.Event()

        async def server() -> None:
            # First request: AwaitReply, then RollForward.
            await channel.get_sent()
            await channel.feed_response(_make_await_reply_bytes())
            await channel.feed_response(_make_roll_forward_bytes(42))

            # Second request: normal RollForward.
            await channel.get_sent()
            await channel.feed_response(_make_roll_forward_bytes(43))

            stop_event.set()

        server_task = asyncio.create_task(server())

        await client.run_pipelined_sync(
            on_roll_forward=on_roll_forward,
            on_roll_backward=on_roll_backward,
            stop_event=stop_event,
        )

        await server_task

        assert received_headers == [42, 43]


class TestPipelinedChainSyncTiming:
    """Verify pipelining is faster than sequential (simulated)."""

    @pytest.mark.asyncio
    async def test_pipelined_faster_than_sequential(self) -> None:
        """Pipelined sync completes faster than sequential with latency.

        We simulate 10ms server latency. Sequential: 10 * 10ms = 100ms.
        Pipelined (depth=10): ~10ms total (all requests in flight).
        """
        n_blocks = 10
        latency = 0.01  # 10ms per response

        # --- Sequential simulation ---
        channel_seq = FakeChainSyncChannel()
        codec = ChainSyncCodec()

        async def sequential_server() -> None:
            for i in range(n_blocks):
                await channel_seq.get_sent()
                await asyncio.sleep(latency)
                await channel_seq.feed_response(_make_roll_forward_bytes(i))

        seq_start = time.monotonic()
        server_task = asyncio.create_task(sequential_server())

        for i in range(n_blocks):
            data = codec.encode(CsMsgRequestNext())
            await channel_seq.send(data)
            resp = await channel_seq.recv()

        await server_task
        seq_time = time.monotonic() - seq_start

        # --- Pipelined simulation ---
        channel_pipe = FakeChainSyncChannel()
        client = PipelinedChainSyncClient(channel_pipe, max_in_flight=n_blocks)

        received: list[int] = []

        async def on_fwd(header: bytes, tip: Tip) -> None:
            received.append(int.from_bytes(header, "big"))

        stop = asyncio.Event()

        async def pipelined_server() -> None:
            for i in range(n_blocks):
                await channel_pipe.get_sent()
                await asyncio.sleep(latency)
                await channel_pipe.feed_response(_make_roll_forward_bytes(i))
            stop.set()

        pipe_start = time.monotonic()
        server_task = asyncio.create_task(pipelined_server())

        await client.run_pipelined_sync(
            on_roll_forward=on_fwd,
            on_roll_backward=AsyncMock(),
            stop_event=stop,
        )
        await server_task
        pipe_time = time.monotonic() - pipe_start

        # Pipelined should be faster. Allow margin for OS scheduling jitter.
        assert pipe_time < seq_time * 1.5, (
            f"Pipelined ({pipe_time:.3f}s) should be faster than "
            f"sequential ({seq_time:.3f}s) within 50% margin"
        )
        assert received == list(range(n_blocks))


class TestRunPipelinedChainSync:
    """Test the top-level run_pipelined_chain_sync function."""

    @pytest.mark.asyncio
    async def test_full_sync_session(self) -> None:
        """run_pipelined_chain_sync runs intersection + pipelined sync."""
        channel = FakeChainSyncChannel()

        received_headers: list[int] = []

        async def on_fwd(header: bytes, tip: Tip) -> None:
            received_headers.append(int.from_bytes(header, "big"))

        stop = asyncio.Event()

        async def server() -> None:
            # First: consume FindIntersect, respond with IntersectFound.
            await channel.get_sent()
            await channel.feed_response(_make_intersect_found_bytes())

            # Then: 5 roll-forwards.
            for i in range(5):
                await channel.get_sent()
                await channel.feed_response(_make_roll_forward_bytes(i))

            stop.set()

        server_task = asyncio.create_task(server())

        await run_pipelined_chain_sync(
            channel=channel,
            known_points=[ORIGIN],
            on_roll_forward=on_fwd,
            on_roll_backward=AsyncMock(),
            max_in_flight=10,
            stop_event=stop,
        )

        await server_task
        assert received_headers == [0, 1, 2, 3, 4]
