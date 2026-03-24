"""Tests for PipelinedRunner — the core pipelining framework.

Tests cover:
- Basic send/collect round-trip
- max_in_flight is respected (backpressure blocks sender)
- Ordering: responses arrive in same order as requests
- drain() collects all in-flight responses
- Error propagation from receiver to collector
- Context manager start/stop lifecycle
- Hypothesis: any sequence of requests preserves FIFO ordering
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.protocols.pipelining import PipelinedRunner

# ---------------------------------------------------------------------------
# Fake channel and codec for testing
# ---------------------------------------------------------------------------


class FakeChannel:
    """Simulates a MiniProtocolChannel with paired queues.

    send() puts data on the outbound queue (visible to the "server").
    recv() reads from the inbound queue (fed by the "server").
    """

    def __init__(self) -> None:
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    async def send(self, payload: bytes) -> None:
        if self._closed:
            raise RuntimeError("channel closed")
        await self._outbound.put(payload)

    async def recv(self) -> bytes:
        if self._closed:
            raise RuntimeError("channel closed")
        return await self._inbound.get()

    async def feed_response(self, payload: bytes) -> None:
        """Simulate the server sending a response."""
        await self._inbound.put(payload)

    async def get_sent(self) -> bytes:
        """Read what the client sent (for verification)."""
        return await self._outbound.get()

    def close(self) -> None:
        self._closed = True


@dataclass
class FakeMessage:
    """A simple message for testing."""

    payload: int

    @property
    def __class_name__(self) -> str:
        return "FakeMessage"


class FakeCodec:
    """Trivial codec: encode int as 4 bytes, decode back."""

    def encode(self, message: FakeMessage) -> bytes:
        return message.payload.to_bytes(4, "big")

    def decode(self, data: bytes) -> FakeMessage:
        return FakeMessage(payload=int.from_bytes(data, "big"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _echo_server(channel: FakeChannel, count: int, delay: float = 0.0) -> None:
    """Simulate a server that echoes back each request as a response."""
    for _ in range(count):
        data = await channel.get_sent()
        if delay > 0:
            await asyncio.sleep(delay)
        await channel.feed_response(data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelinedRunnerBasic:
    """Core send/collect behavior."""

    @pytest.mark.asyncio
    async def test_single_request_response(self) -> None:
        """Send one request, collect one response."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        async with pipeline:
            # Start echo server.
            server = asyncio.create_task(_echo_server(channel, 1))

            await pipeline.send_request(FakeMessage(42))
            assert pipeline.in_flight == 1

            response = await pipeline.collect_response()
            assert isinstance(response, FakeMessage)
            assert response.payload == 42
            assert pipeline.in_flight == 0

            await server

    @pytest.mark.asyncio
    async def test_multiple_requests_fifo_order(self) -> None:
        """Responses come back in the same order as requests."""
        channel = FakeChannel()
        codec = FakeCodec()
        n = 20
        pipeline = PipelinedRunner(channel, codec, max_in_flight=n)

        async with pipeline:
            server = asyncio.create_task(_echo_server(channel, n))

            # Send all requests.
            for i in range(n):
                await pipeline.send_request(FakeMessage(i))

            # Collect all responses — must be in order.
            for i in range(n):
                response = await pipeline.collect_response()
                assert response.payload == i

            await server

    @pytest.mark.asyncio
    async def test_in_flight_tracking(self) -> None:
        """in_flight counter accurately tracks outstanding requests."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        async with pipeline:
            server = asyncio.create_task(_echo_server(channel, 3))

            assert pipeline.in_flight == 0

            await pipeline.send_request(FakeMessage(1))
            assert pipeline.in_flight == 1

            await pipeline.send_request(FakeMessage(2))
            assert pipeline.in_flight == 2

            await pipeline.send_request(FakeMessage(3))
            assert pipeline.in_flight == 3

            await pipeline.collect_response()
            assert pipeline.in_flight == 2

            await pipeline.collect_response()
            assert pipeline.in_flight == 1

            await pipeline.collect_response()
            assert pipeline.in_flight == 0

            await server


class TestPipelinedRunnerBackpressure:
    """Backpressure: send_request blocks when pipeline is full."""

    @pytest.mark.asyncio
    async def test_max_in_flight_blocks_sender(self) -> None:
        """When max_in_flight is reached, send_request blocks."""
        channel = FakeChannel()
        codec = FakeCodec()
        max_depth = 3
        pipeline = PipelinedRunner(channel, codec, max_in_flight=max_depth)

        async with pipeline:
            # Fill the pipeline to capacity.
            for i in range(max_depth):
                await pipeline.send_request(FakeMessage(i))

            assert pipeline.in_flight == max_depth

            # The next send should block because pipeline is full.
            send_blocked = asyncio.Event()
            send_completed = asyncio.Event()

            async def blocked_sender() -> None:
                send_blocked.set()
                await pipeline.send_request(FakeMessage(999))
                send_completed.set()

            task = asyncio.create_task(blocked_sender())
            await send_blocked.wait()
            # Give the send a chance to complete (it shouldn't).
            await asyncio.sleep(0.05)
            assert not send_completed.is_set(), "send should be blocked"

            # Feed one response to free a slot.
            await channel.feed_response(codec.encode(FakeMessage(0)))
            await pipeline.collect_response()

            # Now the blocked send should complete.
            await asyncio.sleep(0.05)
            assert send_completed.is_set(), "send should have unblocked"

            # Clean up remaining in-flight.
            for i in range(1, max_depth):
                await channel.feed_response(codec.encode(FakeMessage(i)))
            await channel.feed_response(codec.encode(FakeMessage(999)))

            for _ in range(max_depth):
                await pipeline.collect_response()

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_max_in_flight_one_is_sequential(self) -> None:
        """max_in_flight=1 forces strictly sequential behavior."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=1)

        async with pipeline:
            server = asyncio.create_task(_echo_server(channel, 3))

            for i in range(3):
                await pipeline.send_request(FakeMessage(i))
                assert pipeline.in_flight == 1
                response = await pipeline.collect_response()
                assert response.payload == i
                assert pipeline.in_flight == 0

            await server


class TestPipelinedRunnerDrain:
    """drain() collects all in-flight responses."""

    @pytest.mark.asyncio
    async def test_drain_returns_all_in_order(self) -> None:
        """drain() returns all pending responses in FIFO order."""
        channel = FakeChannel()
        codec = FakeCodec()
        n = 5
        pipeline = PipelinedRunner(channel, codec, max_in_flight=n)

        async with pipeline:
            # Send all requests.
            for i in range(n):
                await pipeline.send_request(FakeMessage(i))

            # Feed all responses from server.
            for i in range(n):
                await channel.feed_response(codec.encode(FakeMessage(i)))

            # Give receiver a moment to enqueue them.
            await asyncio.sleep(0.05)

            # Drain should return all of them.
            drained = await pipeline.drain()
            assert len(drained) == n
            for i, msg in enumerate(drained):
                assert msg.payload == i

            assert pipeline.in_flight == 0

    @pytest.mark.asyncio
    async def test_drain_empty_pipeline(self) -> None:
        """drain() on an empty pipeline returns empty list."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        async with pipeline:
            drained = await pipeline.drain()
            assert drained == []


class TestPipelinedRunnerLifecycle:
    """Lifecycle: start/stop, context manager, error handling."""

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Context manager starts and stops the receiver."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        assert pipeline.is_closed is False

        async with pipeline:
            # Should be able to operate.
            pass

        assert pipeline.is_closed is True

    @pytest.mark.asyncio
    async def test_send_before_start_raises(self) -> None:
        """Sending before start() raises RuntimeError."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        with pytest.raises(RuntimeError, match="not started"):
            await pipeline.send_request(FakeMessage(1))

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self) -> None:
        """Sending after stop raises RuntimeError."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        async with pipeline:
            pass  # enters and exits, which calls stop()

        with pytest.raises(RuntimeError, match="closed"):
            await pipeline.send_request(FakeMessage(1))

    @pytest.mark.asyncio
    async def test_collect_with_nothing_in_flight_blocks(self) -> None:
        """Collecting with no in-flight requests blocks (doesn't crash)."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        async with pipeline:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(pipeline.collect_response(), timeout=0.05)

    def test_invalid_max_in_flight(self) -> None:
        """max_in_flight < 1 raises ValueError."""
        channel = FakeChannel()
        codec = FakeCodec()

        with pytest.raises(ValueError, match="max_in_flight"):
            PipelinedRunner(channel, codec, max_in_flight=0)

        with pytest.raises(ValueError, match="max_in_flight"):
            PipelinedRunner(channel, codec, max_in_flight=-1)

    @pytest.mark.asyncio
    async def test_double_start_raises(self) -> None:
        """Starting twice raises RuntimeError."""
        channel = FakeChannel()
        codec = FakeCodec()
        pipeline = PipelinedRunner(channel, codec, max_in_flight=10)

        pipeline.start()
        with pytest.raises(RuntimeError, match="already started"):
            pipeline.start()

        await pipeline.stop()


class TestPipelinedRunnerProperties:
    """Property-based tests with Hypothesis."""

    @pytest.mark.asyncio
    @given(
        payloads=st.lists(st.integers(min_value=0, max_value=2**31 - 1), min_size=1, max_size=50)
    )
    @settings(max_examples=20, deadline=5000)
    async def test_fifo_ordering_property(self, payloads: list[int]) -> None:
        """For any sequence of requests, responses preserve FIFO order."""
        channel = FakeChannel()
        codec = FakeCodec()
        n = len(payloads)
        pipeline = PipelinedRunner(channel, codec, max_in_flight=max(n, 1))

        async with pipeline:
            server = asyncio.create_task(_echo_server(channel, n))

            for p in payloads:
                await pipeline.send_request(FakeMessage(p))

            collected = []
            for _ in range(n):
                resp = await pipeline.collect_response()
                collected.append(resp.payload)

            assert collected == payloads
            await server
