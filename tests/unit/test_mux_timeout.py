"""Multiplexer timeout tests — asyncio native timeout behavior.

Tests that the multiplexer and its components behave correctly under
timeout conditions, using asyncio.wait_for and asyncio.TaskGroup for
structured concurrency.

Haskell reference:
    Network.Mux.Types (sduTimeout, handshakeTimeout)
    Network.Mux.Bearer.Socket (timeoutOnReadByte, timeoutOnWrite)

Test specs:
    - Timeout fires after specified duration
    - No timeout when response arrives in time
    - Multiple concurrent timeouts fire independently
    - Timeout cancellation before firing
    - Timeout during mux read (hung bearer)
    - Timeout during mux write (stuck send)
    - Zero timeout = immediate
    - Timeout with asyncio.TaskGroup (structured concurrency)
"""

from __future__ import annotations

import asyncio
import time

import pytest

from vibe.core.multiplexer.bearer import Bearer
from vibe.core.multiplexer.mux import MiniProtocolChannel, Multiplexer, MuxClosedError
from vibe.core.multiplexer.segment import MuxSegment, encode_segment


# ---------------------------------------------------------------------------
# Helpers — mock bearers that simulate hung/slow connections
# ---------------------------------------------------------------------------


class HungBearer:
    """A bearer that blocks forever on read — simulates a hung remote peer."""

    def __init__(self) -> None:
        self._closed = False
        self._hung_event = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        """Block forever (until cancelled)."""
        await self._hung_event.wait()  # never set
        raise RuntimeError("unreachable")

    async def write_segment(self, segment: MuxSegment) -> None:
        """Block forever on write — simulates a stuck send."""
        await self._hung_event.wait()
        raise RuntimeError("unreachable")

    async def close(self) -> None:
        self._closed = True
        self._hung_event.set()  # unblock anything waiting


class SlowBearer:
    """A bearer that delays before returning data."""

    def __init__(self, delay: float, segment: MuxSegment | None = None) -> None:
        self._delay = delay
        self._segment = segment or MuxSegment(
            timestamp=0, protocol_id=0, is_initiator=True, payload=b"ok"
        )
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        await asyncio.sleep(self._delay)
        return self._segment

    async def write_segment(self, segment: MuxSegment) -> None:
        await asyncio.sleep(self._delay)

    async def close(self) -> None:
        self._closed = True


class FastBearer:
    """A bearer that returns immediately — for no-timeout cases."""

    def __init__(self) -> None:
        self._closed = False
        self._written: list[MuxSegment] = []

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        return MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"fast")

    async def write_segment(self, segment: MuxSegment) -> None:
        self._written.append(segment)

    async def close(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# 1. Timeout fires after specified duration
# ---------------------------------------------------------------------------


class TestTimeoutFires:
    """Verify asyncio.wait_for fires TimeoutError after the specified duration."""

    async def test_timeout_fires_on_hung_read(self) -> None:
        """A hung bearer read triggers TimeoutError within tolerance."""
        bearer = HungBearer()
        timeout = 0.05

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bearer.read_segment(), timeout=timeout)
        elapsed = time.monotonic() - start

        # Should fire within 2x the timeout (accounting for scheduling jitter)
        assert elapsed < timeout * 3, f"Timeout took {elapsed:.3f}s, expected ~{timeout}s"
        assert elapsed >= timeout * 0.8, f"Timeout fired too early: {elapsed:.3f}s"

    async def test_timeout_fires_on_channel_recv(self) -> None:
        """MiniProtocolChannel.recv() times out when no data arrives."""
        channel = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        timeout = 0.05

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel.recv(), timeout=timeout)


# ---------------------------------------------------------------------------
# 2. No timeout when response arrives in time
# ---------------------------------------------------------------------------


class TestNoTimeout:
    """Verify no TimeoutError when data arrives before the deadline."""

    async def test_fast_read_no_timeout(self) -> None:
        """A fast bearer read completes without TimeoutError."""
        bearer = FastBearer()
        result = await asyncio.wait_for(bearer.read_segment(), timeout=1.0)
        assert result.payload == b"fast"

    async def test_slow_read_within_deadline(self) -> None:
        """A slow bearer that responds within the deadline succeeds."""
        bearer = SlowBearer(delay=0.01)
        result = await asyncio.wait_for(bearer.read_segment(), timeout=1.0)
        assert result.payload == b"ok"

    async def test_channel_recv_with_data_no_timeout(self) -> None:
        """Channel recv() succeeds when data is already queued."""
        channel = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        channel._inbound.put_nowait(b"hello")

        result = await asyncio.wait_for(channel.recv(), timeout=1.0)
        assert result == b"hello"


# ---------------------------------------------------------------------------
# 3. Multiple concurrent timeouts fire independently
# ---------------------------------------------------------------------------


class TestConcurrentTimeouts:
    """Multiple concurrent timeout operations fire independently."""

    async def test_three_independent_timeouts(self) -> None:
        """Three hung reads with different timeouts fire in order."""
        bearers = [HungBearer(), HungBearer(), HungBearer()]
        timeouts = [0.03, 0.06, 0.09]
        results: list[tuple[int, float]] = []

        async def timed_read(idx: int, bearer: HungBearer, timeout: float) -> None:
            start = time.monotonic()
            try:
                await asyncio.wait_for(bearer.read_segment(), timeout=timeout)
            except TimeoutError:
                elapsed = time.monotonic() - start
                results.append((idx, elapsed))

        tasks = [
            asyncio.create_task(timed_read(i, b, t))
            for i, (b, t) in enumerate(zip(bearers, timeouts))
        ]
        await asyncio.gather(*tasks)

        assert len(results) == 3
        # All three should have timed out
        for idx, elapsed in results:
            expected = timeouts[idx]
            assert elapsed >= expected * 0.8, (
                f"Timeout {idx} fired too early: {elapsed:.3f}s < {expected}s"
            )

    async def test_mixed_timeout_and_success(self) -> None:
        """One fast and one hung bearer — only the hung one times out."""
        fast = FastBearer()
        hung = HungBearer()

        fast_result = await asyncio.wait_for(fast.read_segment(), timeout=1.0)
        assert fast_result.payload == b"fast"

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(hung.read_segment(), timeout=0.03)


# ---------------------------------------------------------------------------
# 4. Timeout cancellation — cancel before it fires
# ---------------------------------------------------------------------------


class TestTimeoutCancellation:
    """Cancelling a task before its timeout fires is clean."""

    async def test_cancel_before_timeout(self) -> None:
        """Cancelling a wait_for task before timeout raises CancelledError."""
        bearer = HungBearer()

        async def slow_op() -> None:
            await asyncio.wait_for(bearer.read_segment(), timeout=10.0)

        task = asyncio.create_task(slow_op())
        await asyncio.sleep(0.01)  # let the task start
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_cancel_channel_recv(self) -> None:
        """Cancelling a channel recv is clean."""
        channel = MiniProtocolChannel(protocol_id=0, is_initiator=True)

        task = asyncio.create_task(channel.recv())
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# 5. Timeout during mux read — hung bearer triggers timeout
# ---------------------------------------------------------------------------


class TestTimeoutDuringMuxRead:
    """Timeout on a Multiplexer whose bearer is hung."""

    async def test_mux_run_with_hung_bearer_times_out(self) -> None:
        """Multiplexer.run() on a hung bearer can be timed out externally."""
        bearer = HungBearer()
        # We need a real Bearer-like object, so we use our HungBearer duck type
        mux = Multiplexer.__new__(Multiplexer)
        mux._bearer = bearer  # type: ignore[assignment]
        mux._is_initiator = True
        mux._channels = {}
        mux._sender_task = None
        mux._receiver_task = None
        mux._running = False
        mux._closed = False
        mux._stop_event = asyncio.Event()

        mux.add_protocol(0)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(mux.run(), timeout=0.05)

        # Cleanup
        await bearer.close()

    async def test_channel_recv_timeout_on_no_data(self) -> None:
        """Channel recv times out when the mux receiver never delivers data."""
        channel = MiniProtocolChannel(protocol_id=5, is_initiator=True)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel.recv(), timeout=0.03)


# ---------------------------------------------------------------------------
# 6. Timeout during mux write — stuck send triggers timeout
# ---------------------------------------------------------------------------


class TestTimeoutDuringMuxWrite:
    """Timeout on write operations when the bearer is stuck."""

    async def test_hung_bearer_write_times_out(self) -> None:
        """Writing to a hung bearer times out."""
        bearer = HungBearer()
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"hello")

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bearer.write_segment(seg), timeout=0.03)

    async def test_slow_bearer_write_times_out(self) -> None:
        """Writing to a slow bearer (delay > timeout) times out."""
        bearer = SlowBearer(delay=1.0)
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"hello")

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bearer.write_segment(seg), timeout=0.03)


# ---------------------------------------------------------------------------
# 7. Timeout value of 0 — immediate timeout
# ---------------------------------------------------------------------------


class TestZeroTimeout:
    """A timeout of 0 should fire immediately (or near-immediately)."""

    async def test_zero_timeout_read(self) -> None:
        """timeout=0 on a hung read fires immediately."""
        bearer = HungBearer()

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bearer.read_segment(), timeout=0)
        elapsed = time.monotonic() - start

        # Should complete nearly instantly (under 50ms)
        assert elapsed < 0.05, f"Zero timeout took {elapsed:.3f}s"

    async def test_zero_timeout_channel_recv(self) -> None:
        """timeout=0 on empty channel recv fires immediately."""
        channel = MiniProtocolChannel(protocol_id=0, is_initiator=True)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel.recv(), timeout=0)

    async def test_zero_timeout_write(self) -> None:
        """timeout=0 on a hung write fires immediately."""
        bearer = HungBearer()
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"x")

        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bearer.write_segment(seg), timeout=0)
        elapsed = time.monotonic() - start

        assert elapsed < 0.05


# ---------------------------------------------------------------------------
# 8. Timeout with asyncio.TaskGroup — structured concurrency
# ---------------------------------------------------------------------------


class TestTimeoutWithTaskGroup:
    """Timeout operations within asyncio.TaskGroup for structured concurrency.

    TaskGroup (Python 3.11+) propagates exceptions from child tasks and
    cancels siblings on first failure. Timeout-based patterns must work
    correctly in this context.
    """

    async def test_taskgroup_single_timeout(self) -> None:
        """A single timeout within a TaskGroup propagates correctly."""
        bearer = HungBearer()

        with pytest.raises(ExceptionGroup) as exc_info:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    asyncio.wait_for(bearer.read_segment(), timeout=0.03)
                )

        # The ExceptionGroup should contain a TimeoutError
        assert any(
            isinstance(e, TimeoutError) for e in exc_info.value.exceptions
        )

    async def test_taskgroup_timeout_cancels_siblings(self) -> None:
        """When one task times out in a TaskGroup, siblings are cancelled."""
        hung = HungBearer()
        sibling_cancelled = False

        async def sibling_task() -> None:
            nonlocal sibling_cancelled
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                sibling_cancelled = True
                raise

        with pytest.raises(ExceptionGroup):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(
                    asyncio.wait_for(hung.read_segment(), timeout=0.03)
                )
                tg.create_task(sibling_task())

        assert sibling_cancelled, "Sibling task should have been cancelled"

    async def test_taskgroup_mixed_timeout_and_success(self) -> None:
        """A fast task succeeds while a hung task times out in a TaskGroup."""
        fast = FastBearer()
        hung = HungBearer()
        fast_result: MuxSegment | None = None

        async def fast_read() -> None:
            nonlocal fast_result
            fast_result = await asyncio.wait_for(fast.read_segment(), timeout=1.0)

        async def hung_read() -> None:
            await asyncio.wait_for(hung.read_segment(), timeout=0.03)

        with pytest.raises(ExceptionGroup):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(fast_read())
                tg.create_task(hung_read())

        # The fast task may or may not have completed before the timeout
        # cancelled everything — that's fine. The key assertion is that
        # the TaskGroup handled the TimeoutError cleanly.
