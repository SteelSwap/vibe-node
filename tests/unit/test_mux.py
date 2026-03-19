"""Unit tests for the Ouroboros multiplexer/demultiplexer.

Tests the Multiplexer and MiniProtocolChannel classes using a MockBearer
that uses in-memory queues instead of TCP, verifying:
- Single protocol send/receive
- Two protocols multiplexed on the same bearer
- Fair scheduling (no starvation)
- Unknown protocol ID handling
- Bearer disconnect propagation
- Channel close

Test specs consulted (from test_specifications DB):
- test_multiplexed_messages_preserve_protocol_isolation
- test_mux_fairness_all_protocols_get_scheduled
- test_mux_bearer_closed_shuts_down_peer_only
- test_mux_unknown_miniprotocol_shuts_down_node (we drop instead)
- test_mux_mini_protocol_keyed_by_num_and_dir
- test_mux_full_duplex_initiator_and_responder_same_protocol
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from vibe.core.multiplexer.bearer import BearerClosedError
from vibe.core.multiplexer.mux import (
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
    _CHANNEL_CLOSED,
)
from vibe.core.multiplexer.segment import MuxSegment


# ---------------------------------------------------------------------------
# MockBearer — in-memory bearer for testing without TCP
# ---------------------------------------------------------------------------


class MockBearer:
    """In-memory bearer that uses asyncio queues for segment transport.

    Segments written via write_segment() are placed on the outbound queue.
    Segments placed on the inbound queue are returned by read_segment().
    This lets tests inject inbound segments and inspect outbound ones
    without any network I/O.
    """

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[MuxSegment | None] = asyncio.Queue()
        self.outbound: asyncio.Queue[MuxSegment] = asyncio.Queue()
        self._closed = False
        self._disconnect_event = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        if self._closed:
            raise BearerClosedError("mock bearer is closed")
        # Race between getting a segment and a disconnect signal.
        get_task = asyncio.ensure_future(self.inbound.get())
        disconnect_task = asyncio.ensure_future(self._disconnect_event.wait())
        done, pending = await asyncio.wait(
            [get_task, disconnect_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        if disconnect_task in done:
            self._closed = True
            raise ConnectionError("mock bearer disconnected")

        result = get_task.result()
        if result is None:
            self._closed = True
            raise ConnectionError("mock bearer disconnected")
        return result

    async def write_segment(self, segment: MuxSegment) -> None:
        if self._closed:
            raise BearerClosedError("mock bearer is closed")
        if self._disconnect_event.is_set():
            self._closed = True
            raise ConnectionError("mock bearer disconnected")
        await self.outbound.put(segment)

    async def close(self) -> None:
        self._closed = True
        self._disconnect_event.set()

    def disconnect(self) -> None:
        """Simulate a bearer disconnect (connection drop)."""
        self._disconnect_event.set()

    def inject_segment(self, segment: MuxSegment) -> None:
        """Inject a segment as if it arrived from the remote peer."""
        self.inbound.put_nowait(segment)


def make_segment(
    protocol_id: int, payload: bytes, is_initiator: bool = True
) -> MuxSegment:
    """Helper to create a MuxSegment with a zero timestamp."""
    return MuxSegment(
        timestamp=0,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_bearer() -> MockBearer:
    return MockBearer()


# ---------------------------------------------------------------------------
# Tests: MiniProtocolChannel
# ---------------------------------------------------------------------------


class TestMiniProtocolChannel:
    """Tests for the MiniProtocolChannel in isolation."""

    @pytest.mark.asyncio
    async def test_send_queues_payload(self) -> None:
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        await ch.send(b"hello")
        payload = ch._outbound.get_nowait()
        assert payload == b"hello"

    @pytest.mark.asyncio
    async def test_recv_returns_inbound_payload(self) -> None:
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        ch._inbound.put_nowait(b"world")
        result = await ch.recv()
        assert result == b"world"

    @pytest.mark.asyncio
    async def test_send_on_closed_channel_raises(self) -> None:
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        ch.close()
        with pytest.raises(MuxClosedError):
            await ch.send(b"data")

    @pytest.mark.asyncio
    async def test_recv_on_closed_channel_raises(self) -> None:
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        ch.close()
        with pytest.raises(MuxClosedError):
            await ch.recv()

    @pytest.mark.asyncio
    async def test_recv_unblocks_on_close(self) -> None:
        """recv() should raise MuxClosedError if the channel closes while waiting."""
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)

        async def close_after_delay():
            await asyncio.sleep(0.01)
            ch.close()

        asyncio.create_task(close_after_delay())
        with pytest.raises(MuxClosedError):
            await ch.recv()

    def test_close_is_idempotent(self) -> None:
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        ch.close()
        ch.close()  # Should not raise.
        assert ch._closed


# ---------------------------------------------------------------------------
# Tests: Multiplexer — single protocol
# ---------------------------------------------------------------------------


class TestMultiplexerSingleProtocol:
    """Test basic mux/demux with a single miniprotocol."""

    @pytest.mark.asyncio
    async def test_send_single_message(self, mock_bearer: MockBearer) -> None:
        """A payload sent on a channel appears as a segment on the bearer."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Send a payload.
        await ch.send(b"hello")

        # Run mux briefly.
        run_task = asyncio.create_task(mux.run())
        # Wait for the segment to appear on the bearer outbound queue.
        segment = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=1.0)

        assert segment.protocol_id == 0
        assert segment.is_initiator is True
        assert segment.payload == b"hello"

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass

    @pytest.mark.asyncio
    async def test_receive_single_message(self, mock_bearer: MockBearer) -> None:
        """An inbound segment on the bearer is delivered to the correct channel."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject a segment from the "remote peer".
        mock_bearer.inject_segment(make_segment(0, b"from-remote"))

        run_task = asyncio.create_task(mux.run())
        payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        assert payload == b"from-remote"

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass

    @pytest.mark.asyncio
    async def test_roundtrip(self, mock_bearer: MockBearer) -> None:
        """Multiple messages sent and received maintain ordering."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(5)

        messages = [f"msg-{i}".encode() for i in range(10)]
        for msg in messages:
            await ch.send(msg)

        run_task = asyncio.create_task(mux.run())

        received_segments = []
        for _ in range(10):
            seg = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=2.0)
            received_segments.append(seg)

        for i, seg in enumerate(received_segments):
            assert seg.protocol_id == 5
            assert seg.payload == messages[i]

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass


# ---------------------------------------------------------------------------
# Tests: Multiplexer — two protocols
# ---------------------------------------------------------------------------


class TestMultiplexerTwoProtocols:
    """Test multiplexing two miniprotocols on the same bearer.

    Spec: test_multiplexed_messages_preserve_protocol_isolation
    """

    @pytest.mark.asyncio
    async def test_two_protocols_isolation(self, mock_bearer: MockBearer) -> None:
        """Messages for different protocols are routed to separate channels."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_a = mux.add_protocol(0)
        ch_b = mux.add_protocol(2)

        # Inject segments for both protocols.
        mock_bearer.inject_segment(make_segment(0, b"for-proto-0"))
        mock_bearer.inject_segment(make_segment(2, b"for-proto-2"))

        run_task = asyncio.create_task(mux.run())

        payload_a = await asyncio.wait_for(ch_a.recv(), timeout=1.0)
        payload_b = await asyncio.wait_for(ch_b.recv(), timeout=1.0)

        assert payload_a == b"for-proto-0"
        assert payload_b == b"for-proto-2"

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass

    @pytest.mark.asyncio
    async def test_two_protocols_outbound(self, mock_bearer: MockBearer) -> None:
        """Outbound messages from two channels both appear on the bearer."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_a = mux.add_protocol(0)
        ch_b = mux.add_protocol(2)

        await ch_a.send(b"from-a")
        await ch_b.send(b"from-b")

        run_task = asyncio.create_task(mux.run())

        segments = []
        for _ in range(2):
            seg = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=1.0)
            segments.append(seg)

        payloads = {seg.payload for seg in segments}
        assert payloads == {b"from-a", b"from-b"}

        # Each segment has the right protocol_id.
        for seg in segments:
            if seg.payload == b"from-a":
                assert seg.protocol_id == 0
            else:
                assert seg.protocol_id == 2

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass


# ---------------------------------------------------------------------------
# Tests: Fair scheduling
# ---------------------------------------------------------------------------


class TestFairScheduling:
    """Verify the sender doesn't starve any protocol.

    Spec: test_mux_fairness_all_protocols_get_scheduled
    """

    @pytest.mark.asyncio
    async def test_no_starvation(self, mock_bearer: MockBearer) -> None:
        """With N protocols each having data, all get serviced in a round."""
        n_protocols = 5
        mux = Multiplexer(mock_bearer, is_initiator=True)
        channels = []
        for pid in range(n_protocols):
            ch = mux.add_protocol(pid)
            channels.append(ch)

        # Each protocol has 3 messages queued.
        for pid, ch in enumerate(channels):
            for j in range(3):
                await ch.send(f"p{pid}-m{j}".encode())

        run_task = asyncio.create_task(mux.run())

        # Collect all 15 segments.
        segments: list[MuxSegment] = []
        for _ in range(15):
            seg = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=2.0)
            segments.append(seg)

        # Every protocol must have been serviced.
        serviced_pids = {seg.protocol_id for seg in segments}
        assert serviced_pids == set(range(n_protocols))

        # Each protocol got exactly 3 segments.
        from collections import Counter

        counts = Counter(seg.protocol_id for seg in segments)
        for pid in range(n_protocols):
            assert counts[pid] == 3

        # Fairness check: in the first N segments, all N protocols should
        # appear (round-robin guarantee).
        first_round_pids = {seg.protocol_id for seg in segments[:n_protocols]}
        assert first_round_pids == set(range(n_protocols))

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass


# ---------------------------------------------------------------------------
# Tests: Unknown protocol ID
# ---------------------------------------------------------------------------


class TestUnknownProtocol:
    """Verify unknown protocol IDs are handled gracefully.

    Spec: test_mux_unknown_miniprotocol_shuts_down_node
    Note: Haskell escalates to ShutdownNode. We log a warning and drop.
    """

    @pytest.mark.asyncio
    async def test_unknown_protocol_dropped(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A segment for an unregistered protocol is dropped with a warning."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject a segment for unknown protocol 99, then a valid one.
        mock_bearer.inject_segment(make_segment(99, b"unknown"))
        mock_bearer.inject_segment(make_segment(0, b"valid"))

        run_task = asyncio.create_task(mux.run())

        with caplog.at_level(logging.WARNING):
            payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        assert payload == b"valid"
        assert "unknown protocol_id 99" in caplog.text

        await mux.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass


# ---------------------------------------------------------------------------
# Tests: Bearer disconnect propagation
# ---------------------------------------------------------------------------


class TestBearerDisconnect:
    """Verify that bearer disconnects propagate to all channels.

    Spec: test_mux_bearer_closed_shuts_down_peer_only
    """

    @pytest.mark.asyncio
    async def test_disconnect_closes_channels(self, mock_bearer: MockBearer) -> None:
        """When the bearer disconnects, all channels become closed."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_a = mux.add_protocol(0)
        ch_b = mux.add_protocol(1)

        run_task = asyncio.create_task(mux.run())

        # Give the receiver loop a moment to start waiting on the bearer.
        await asyncio.sleep(0.02)

        # Simulate disconnect.
        mock_bearer.disconnect()

        # run() should complete (both tasks exit on bearer disconnect).
        await asyncio.wait_for(run_task, timeout=2.0)

        # Channels should be closed.
        assert ch_a._closed
        assert ch_b._closed

    @pytest.mark.asyncio
    async def test_recv_after_disconnect_raises(
        self, mock_bearer: MockBearer
    ) -> None:
        """recv() on a channel raises MuxClosedError after bearer disconnect."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        mock_bearer.disconnect()
        await asyncio.wait_for(run_task, timeout=2.0)

        with pytest.raises(MuxClosedError):
            await ch.recv()


# ---------------------------------------------------------------------------
# Tests: Multiplexer lifecycle
# ---------------------------------------------------------------------------


class TestMultiplexerLifecycle:
    """Test add_protocol validation, close idempotency, etc."""

    @pytest.mark.asyncio
    async def test_add_protocol_duplicate_raises(
        self, mock_bearer: MockBearer
    ) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        mux.add_protocol(0)
        with pytest.raises(ValueError, match="already registered"):
            mux.add_protocol(0)

    @pytest.mark.asyncio
    async def test_add_protocol_invalid_id_raises(
        self, mock_bearer: MockBearer
    ) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        with pytest.raises(ValueError):
            mux.add_protocol(-1)
        with pytest.raises(ValueError):
            mux.add_protocol(0x8000)

    @pytest.mark.asyncio
    async def test_add_protocol_after_close_raises(
        self, mock_bearer: MockBearer
    ) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        await mux.close()
        with pytest.raises(MuxClosedError):
            mux.add_protocol(0)

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, mock_bearer: MockBearer) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        await mux.close()
        await mux.close()  # Should not raise.
        assert mux.is_closed

    @pytest.mark.asyncio
    async def test_run_after_close_raises(self, mock_bearer: MockBearer) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        await mux.close()
        with pytest.raises(MuxClosedError):
            await mux.run()

    @pytest.mark.asyncio
    async def test_initiator_flag_on_outbound_segments(
        self, mock_bearer: MockBearer
    ) -> None:
        """Outbound segments carry the correct is_initiator flag."""
        # Initiator side.
        mux_init = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux_init.add_protocol(0)
        await ch.send(b"init-msg")

        run_task = asyncio.create_task(mux_init.run())
        seg = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=1.0)

        assert seg.is_initiator is True

        await mux_init.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass

    @pytest.mark.asyncio
    async def test_responder_flag_on_outbound_segments(self) -> None:
        """Responder multiplexer sets is_initiator=False on outbound segments."""
        bearer = MockBearer()
        mux_resp = Multiplexer(bearer, is_initiator=False)
        ch = mux_resp.add_protocol(0)
        await ch.send(b"resp-msg")

        run_task = asyncio.create_task(mux_resp.run())
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)

        assert seg.is_initiator is False

        await mux_resp.close()
        try:
            await run_task
        except (asyncio.CancelledError, MuxClosedError):
            pass


# ---------------------------------------------------------------------------
# Tests: Full-duplex — initiator and responder on same bearer
# ---------------------------------------------------------------------------


class TestFullDuplex:
    """Test that initiator and responder can operate simultaneously.

    Spec: test_mux_full_duplex_initiator_and_responder_same_protocol
    """

    @pytest.mark.asyncio
    async def test_bidirectional_communication(self) -> None:
        """Two multiplexers (initiator + responder) communicate via linked bearers."""
        # Create two linked bearers: what one writes, the other reads.
        bearer_init = MockBearer()
        bearer_resp = MockBearer()

        mux_init = Multiplexer(bearer_init, is_initiator=True)
        mux_resp = Multiplexer(bearer_resp, is_initiator=False)

        ch_init = mux_init.add_protocol(0)
        ch_resp = mux_resp.add_protocol(0)

        run_init = asyncio.create_task(mux_init.run())
        run_resp = asyncio.create_task(mux_resp.run())

        # Initiator sends, responder receives.
        await ch_init.send(b"hello-from-init")
        seg = await asyncio.wait_for(bearer_init.outbound.get(), timeout=1.0)
        # Forward to responder's inbound.
        bearer_resp.inject_segment(seg)
        payload = await asyncio.wait_for(ch_resp.recv(), timeout=1.0)
        assert payload == b"hello-from-init"

        # Responder sends, initiator receives.
        await ch_resp.send(b"hello-from-resp")
        seg = await asyncio.wait_for(bearer_resp.outbound.get(), timeout=1.0)
        bearer_init.inject_segment(seg)
        payload = await asyncio.wait_for(ch_init.recv(), timeout=1.0)
        assert payload == b"hello-from-resp"

        await mux_init.close()
        await mux_resp.close()
        for task in (run_init, run_resp):
            try:
                await task
            except (asyncio.CancelledError, MuxClosedError):
                pass
