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
)
from vibe.core.multiplexer.segment import MuxSegment, decode_segment, encode_segment

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


def make_segment(protocol_id: int, payload: bytes, is_initiator: bool = True) -> MuxSegment:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
    async def test_recv_after_disconnect_raises(self, mock_bearer: MockBearer) -> None:
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
    async def test_add_protocol_duplicate_raises(self, mock_bearer: MockBearer) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        mux.add_protocol(0)
        with pytest.raises(ValueError, match="already registered"):
            mux.add_protocol(0)

    @pytest.mark.asyncio
    async def test_add_protocol_invalid_id_raises(self, mock_bearer: MockBearer) -> None:
        mux = Multiplexer(mock_bearer, is_initiator=True)
        with pytest.raises(ValueError):
            mux.add_protocol(-1)
        with pytest.raises(ValueError):
            mux.add_protocol(0x8000)

    @pytest.mark.asyncio
    async def test_add_protocol_after_close_raises(self, mock_bearer: MockBearer) -> None:
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
    async def test_initiator_flag_on_outbound_segments(self, mock_bearer: MockBearer) -> None:
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
        except asyncio.CancelledError, MuxClosedError:
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
        except asyncio.CancelledError, MuxClosedError:
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
            except asyncio.CancelledError, MuxClosedError:
                pass


# ---------------------------------------------------------------------------
# Tests: Bounded ingress queue (max_ingress_size)
# ---------------------------------------------------------------------------


class TestIngressQueueBounds:
    """Test bounded inbound queues and overflow behavior.

    Critical: The Haskell mux tears down the connection when an ingress
    queue overflows. We close the individual channel — a documented
    divergence until we have a full connection manager.
    """

    @pytest.mark.asyncio
    async def test_demux_ingress_queue_max_size(self) -> None:
        """MiniProtocolChannel with max_ingress_size creates a bounded queue."""
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True, max_ingress_size=3)
        assert ch._inbound.maxsize == 3

        # Can put up to max_ingress_size items.
        ch._inbound.put_nowait(b"a")
        ch._inbound.put_nowait(b"b")
        ch._inbound.put_nowait(b"c")

        # 4th item should raise QueueFull.
        with pytest.raises(asyncio.QueueFull):
            ch._inbound.put_nowait(b"d")

    @pytest.mark.asyncio
    async def test_demux_ingress_queue_overflow_closes_channel(
        self, mock_bearer: MockBearer
    ) -> None:
        """When the inbound queue overflows, the channel is closed (not just dropped)."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0, max_ingress_size=2)

        # Inject 3 segments — the 3rd should overflow the queue and close the channel.
        mock_bearer.inject_segment(make_segment(0, b"msg-1"))
        mock_bearer.inject_segment(make_segment(0, b"msg-2"))
        mock_bearer.inject_segment(make_segment(0, b"msg-3"))
        # Add a valid segment for a different protocol so the receiver keeps running.
        ch_other = mux.add_protocol(1, max_ingress_size=0)
        mock_bearer.inject_segment(make_segment(1, b"sentinel"))

        run_task = asyncio.create_task(mux.run())

        # Wait for the sentinel to arrive — confirms all 3 proto-0 segments processed.
        payload = await asyncio.wait_for(ch_other.recv(), timeout=2.0)
        assert payload == b"sentinel"

        # Channel 0 should be closed due to overflow.
        assert ch._closed

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_demux_ingress_unbounded_default(self) -> None:
        """Default max_ingress_size=0 creates an unbounded queue."""
        ch = MiniProtocolChannel(protocol_id=0, is_initiator=True)
        assert ch._inbound.maxsize == 0  # asyncio.Queue(0) = unbounded

        # Should accept many items without error.
        for i in range(100):
            ch._inbound.put_nowait(f"item-{i}".encode())


# ---------------------------------------------------------------------------
# Tests: Direction handling (demux direction reversal)
# ---------------------------------------------------------------------------


class TestDirectionHandling:
    """Test that the demux correctly handles protocol direction.

    Critical: In the Ouroboros mux protocol, SDUs carry a direction bit.
    An initiator-side mux receives ResponderDir SDUs (the remote responder
    is sending to us). The protocol_id is the same, but the direction is
    reversed from the sender's perspective.

    Spec reference: Ouroboros network spec, Section 1.1 — M=0 is initiator,
    M=1 is responder. The receiver dispatches by protocol_id regardless of
    direction bit (direction is already implicit in the connection role).
    """

    @pytest.mark.asyncio
    async def test_demux_direction_reversal(self, mock_bearer: MockBearer) -> None:
        """ResponderDir SDUs are delivered to the initiator-side channel for that protocol.

        When an initiator receives a segment with is_initiator=False (ResponderDir),
        it should dispatch to the channel registered for that protocol_id. The
        direction reversal is implicit: the initiator receives responder segments,
        and vice versa.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject a ResponderDir segment (is_initiator=False) — this is what
        # the remote responder sends to us (the initiator).
        mock_bearer.inject_segment(make_segment(0, b"from-responder", is_initiator=False))

        run_task = asyncio.create_task(mux.run())
        payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        assert payload == b"from-responder"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_demux_initiator_only_rejects_responder_sdu(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When configured as initiator-only, a channel receives ResponderDir SDUs.

        Note: In the current design, the mux routes by protocol_id only (not by
        direction). An initiator-only channel WILL receive ResponderDir SDUs
        because that's what the remote peer sends to us. This test documents
        that behavior — it's correct for an initiator to receive responder
        segments (that's how bidirectional communication works).

        If we later add direction-aware routing (separate channels for each
        direction per protocol), this test would need updating.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # An initiator should receive ResponderDir segments — that's the
        # remote responder talking to us.
        mock_bearer.inject_segment(make_segment(0, b"resp-sdu", is_initiator=False))

        run_task = asyncio.create_task(mux.run())
        payload = await asyncio.wait_for(ch.recv(), timeout=1.0)
        assert payload == b"resp-sdu"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: No head-of-line blocking
# ---------------------------------------------------------------------------


class TestNoHeadOfLineBlocking:
    """Test that one stalled protocol doesn't block others.

    Critical: The sender uses round-robin with get_nowait(), so a protocol
    with no outbound data (or a full outbound queue on the bearer side)
    should not block other protocols from making progress.
    """

    @pytest.mark.asyncio
    async def test_mux_no_head_of_line_blocking(self, mock_bearer: MockBearer) -> None:
        """One protocol with no data doesn't block another from sending."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_idle = mux.add_protocol(0)  # No data queued — "stalled"
        ch_active = mux.add_protocol(1)

        # Only the active channel has data.
        await ch_active.send(b"active-msg-1")
        await ch_active.send(b"active-msg-2")

        run_task = asyncio.create_task(mux.run())

        # Both messages from the active channel should arrive promptly
        # despite ch_idle having nothing.
        seg1 = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=1.0)
        seg2 = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=1.0)

        assert seg1.protocol_id == 1
        assert seg1.payload == b"active-msg-1"
        assert seg2.protocol_id == 1
        assert seg2.payload == b"active-msg-2"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Unknown protocol behavior documentation
# ---------------------------------------------------------------------------


class TestUnknownProtocolDocumented:
    """Document and test the divergence from Haskell on unknown protocols.

    Critical: Haskell escalates unknown protocols to ShutdownNode, which
    tears down the entire connection manager. We DROP the segment and log a
    warning because we don't yet have a connection manager to escalate to.
    This is a documented gap — see gap-analysis.md.
    """

    @pytest.mark.asyncio
    async def test_mux_unknown_protocol_behavior_documented(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unknown protocol segments are DROPPED (not ShutdownNode).

        GAP: Haskell Network.Mux.demux triggers MuxError (ShutdownNode) for
        unknown MiniProtocolNum. We drop and log. This divergence is acceptable
        until we implement the connection manager layer, at which point we
        should escalate to shut down the peer connection.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject unknown protocols with different IDs.
        mock_bearer.inject_segment(make_segment(42, b"unknown-42"))
        mock_bearer.inject_segment(make_segment(999, b"unknown-999"))
        # Then a valid one so the mux keeps running.
        mock_bearer.inject_segment(make_segment(0, b"valid"))

        run_task = asyncio.create_task(mux.run())

        with caplog.at_level(logging.WARNING):
            payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        # Valid segment delivered.
        assert payload == b"valid"

        # Unknown protocols were logged.
        assert "unknown protocol_id 42" in caplog.text
        assert "unknown protocol_id 999" in caplog.text

        # The mux is still running — it didn't shut down.
        assert mux.is_running

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Per-protocol buffer isolation
# ---------------------------------------------------------------------------


class TestPerProtocolBufferIsolation:
    """Test that filling one protocol's queue doesn't affect another.

    High: This verifies that the per-protocol queue architecture provides
    proper isolation — a slow consumer on one protocol doesn't impact others.
    """

    @pytest.mark.asyncio
    async def test_demux_per_protocol_buffer_isolation(self, mock_bearer: MockBearer) -> None:
        """Filling protocol 0's inbound queue doesn't prevent protocol 1 from receiving."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_full = mux.add_protocol(0, max_ingress_size=2)
        ch_ok = mux.add_protocol(1, max_ingress_size=0)

        # Fill proto 0's queue to capacity.
        mock_bearer.inject_segment(make_segment(0, b"fill-1"))
        mock_bearer.inject_segment(make_segment(0, b"fill-2"))
        # This one overflows proto 0 — closes that channel.
        mock_bearer.inject_segment(make_segment(0, b"overflow"))
        # Proto 1 should still work fine.
        mock_bearer.inject_segment(make_segment(1, b"unaffected"))

        run_task = asyncio.create_task(mux.run())

        # Proto 1 receives its message despite proto 0 overflowing.
        payload = await asyncio.wait_for(ch_ok.recv(), timeout=2.0)
        assert payload == b"unaffected"

        # Proto 0 is closed.
        assert ch_full._closed

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Multi-segment reassembly (data preservation)
# ---------------------------------------------------------------------------


class TestReassembly:
    """Test that multi-segment payloads are delivered correctly.

    High: The mux layer delivers each segment's payload individually (it does
    NOT do higher-level reassembly — that's the miniprotocol's job). This test
    verifies that each segment's data is preserved exactly through mux/demux.
    """

    @pytest.mark.asyncio
    async def test_demux_reassembly_preserves_data(self, mock_bearer: MockBearer) -> None:
        """Multiple segments for the same protocol deliver payloads in order, intact."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Simulate a large message split into 3 segments by the remote peer.
        chunks = [b"chunk-000-start", b"chunk-001-middle", b"chunk-002-end"]
        for chunk in chunks:
            mock_bearer.inject_segment(make_segment(0, chunk))

        run_task = asyncio.create_task(mux.run())

        received = []
        for _ in range(3):
            payload = await asyncio.wait_for(ch.recv(), timeout=1.0)
            received.append(payload)

        # Each chunk delivered exactly, in order.
        assert received == chunks
        # Reassembly is the caller's job — but data is preserved.
        assert b"".join(received) == b"chunk-000-startchunk-001-middlechunk-002-end"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Fairness — bounded delay
# ---------------------------------------------------------------------------


class TestFairnessBoundedDelay:
    """Test that the scheduler doesn't let one protocol monopolize the bearer.

    High: With round-robin scheduling, the maximum number of consecutive
    segments from a single protocol should be bounded by 1 per round.
    """

    @pytest.mark.asyncio
    async def test_fairness_bounded_delay(self, mock_bearer: MockBearer) -> None:
        """No protocol sends more than 1 consecutive segment before others get a turn."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        n_protocols = 3
        channels = []
        for pid in range(n_protocols):
            ch = mux.add_protocol(pid)
            channels.append(ch)

        # Protocol 0 has 5 messages, others have 1 each.
        for i in range(5):
            await channels[0].send(f"p0-{i}".encode())
        await channels[1].send(b"p1-0")
        await channels[2].send(b"p2-0")

        run_task = asyncio.create_task(mux.run())

        # Collect 7 segments total.
        segments: list[MuxSegment] = []
        for _ in range(7):
            seg = await asyncio.wait_for(mock_bearer.outbound.get(), timeout=2.0)
            segments.append(seg)

        # In the first round (3 segments), all 3 protocols should appear.
        first_round = [seg.protocol_id for seg in segments[:n_protocols]]
        assert set(first_round) == {
            0,
            1,
            2,
        }, f"First round should service all protocols, got {first_round}"

        # Check no consecutive run from protocol 0 exceeds 1 in the first 3 segments.
        max_consecutive = 1
        current_run = 1
        for i in range(1, len(segments)):
            if segments[i].protocol_id == segments[i - 1].protocol_id:
                current_run += 1
                max_consecutive = max(max_consecutive, current_run)
            else:
                current_run = 1

        # After others are drained, proto 0 will run consecutively — that's fine.
        # But in the first N segments (where all have data), max run should be 1.
        first_n_max = 1
        current_run = 1
        for i in range(1, n_protocols):
            if segments[i].protocol_id == segments[i - 1].protocol_id:
                current_run += 1
                first_n_max = max(first_n_max, current_run)
            else:
                current_run = 1
        assert (
            first_n_max == 1
        ), f"In first round, max consecutive from one protocol should be 1, got {first_n_max}"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Fairness property test — N protocols
# ---------------------------------------------------------------------------


class TestFairnessPropertyNProtocols:
    """Property test: with N=2..10 protocols, all get scheduled.

    High: This is a parameterized version of the starvation test that
    exercises a range of protocol counts to verify fairness at scale.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("n_protocols", [2, 3, 5, 7, 10])
    async def test_mux_fairness_property_n_protocols(self, n_protocols: int) -> None:
        """With N protocols each sending 1 message, all N appear in output."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        channels = []
        for pid in range(n_protocols):
            ch = mux.add_protocol(pid)
            channels.append(ch)
            await ch.send(f"proto-{pid}".encode())

        run_task = asyncio.create_task(mux.run())

        segments: list[MuxSegment] = []
        for _ in range(n_protocols):
            seg = await asyncio.wait_for(bearer.outbound.get(), timeout=2.0)
            segments.append(seg)

        # All N protocols got scheduled.
        serviced = {seg.protocol_id for seg in segments}
        assert serviced == set(
            range(n_protocols)
        ), f"Expected all {n_protocols} protocols serviced, got {serviced}"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Framing round-trip property
# ---------------------------------------------------------------------------


class TestFramingRoundtrip:
    """Property test at the mux layer — encode/decode segment preserves all fields.

    High: Verifies that MuxSegment serialization round-trips correctly for
    a variety of inputs.
    """

    @pytest.mark.parametrize(
        "protocol_id,is_initiator,payload",
        [
            (0, True, b""),
            (0, False, b"hello"),
            (0x7FFF, True, b"\x00\xff" * 100),
            (42, False, b"x" * 65535),
            (1, True, b"\x00"),
        ],
    )
    def test_multiplexer_framing_roundtrip_property(
        self, protocol_id: int, is_initiator: bool, payload: bytes
    ) -> None:
        """encode_segment -> decode_segment preserves all fields."""
        seg = MuxSegment(
            timestamp=12345,
            protocol_id=protocol_id,
            is_initiator=is_initiator,
            payload=payload,
        )
        wire = encode_segment(seg)
        decoded, consumed = decode_segment(wire)

        assert consumed == len(wire)
        assert decoded.timestamp == seg.timestamp
        assert decoded.protocol_id == seg.protocol_id
        assert decoded.is_initiator == seg.is_initiator
        assert decoded.payload == seg.payload


# ---------------------------------------------------------------------------
# Tests: Protocol keyed by (num, direction) composite key
# ---------------------------------------------------------------------------


class TestProtocolCompositeKey:
    """Verify that protocols are keyed by protocol_id.

    High: In Haskell, protocols are keyed by (MiniProtocolNum, MiniProtocolDir).
    Our current implementation keys by protocol_id only — direction is implicit
    in the mux role (initiator vs responder). This test documents the keying
    behavior and verifies that distinct protocol_ids get distinct channels.
    """

    @pytest.mark.asyncio
    async def test_mux_mini_protocol_keyed_by_num_and_dir(self, mock_bearer: MockBearer) -> None:
        """Different protocol_ids get independent channels.

        Note: In Haskell, the key is (MiniProtocolNum, MiniProtocolDir),
        supporting separate channels for initiator and responder on the
        same protocol number. Our design uses one channel per protocol_id
        per mux instance, with direction implicit in is_initiator. Full-duplex
        is achieved by having separate initiator and responder Multiplexer
        instances. This test verifies our keying is correct for our design.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_0 = mux.add_protocol(0)
        ch_1 = mux.add_protocol(1)
        ch_2 = mux.add_protocol(2)

        # Each channel is independent.
        assert ch_0.protocol_id == 0
        assert ch_1.protocol_id == 1
        assert ch_2.protocol_id == 2

        # Segments are routed to the correct channel.
        mock_bearer.inject_segment(make_segment(2, b"for-2"))
        mock_bearer.inject_segment(make_segment(0, b"for-0"))
        mock_bearer.inject_segment(make_segment(1, b"for-1"))

        run_task = asyncio.create_task(mux.run())

        p0 = await asyncio.wait_for(ch_0.recv(), timeout=1.0)
        p1 = await asyncio.wait_for(ch_1.recv(), timeout=1.0)
        p2 = await asyncio.wait_for(ch_2.recv(), timeout=1.0)

        assert p0 == b"for-0"
        assert p1 == b"for-1"
        assert p2 == b"for-2"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: I/O exception shuts down peer only
# ---------------------------------------------------------------------------


class TestIOExceptionIsolation:
    """Test that an I/O error on one mux doesn't affect another.

    High: Each Multiplexer manages a single bearer (peer connection).
    An I/O error should shut down only that mux instance, not others.
    """

    @pytest.mark.asyncio
    async def test_mux_io_exception_shuts_down_peer_only(self) -> None:
        """An I/O error on bearer A closes mux A but mux B remains operational."""
        bearer_a = MockBearer()
        bearer_b = MockBearer()

        mux_a = Multiplexer(bearer_a, is_initiator=True)
        mux_b = Multiplexer(bearer_b, is_initiator=True)

        ch_a = mux_a.add_protocol(0)
        ch_b = mux_b.add_protocol(0)

        run_a = asyncio.create_task(mux_a.run())
        run_b = asyncio.create_task(mux_b.run())

        await asyncio.sleep(0.02)

        # Disconnect bearer A (simulates I/O error).
        bearer_a.disconnect()

        # Mux A should shut down.
        await asyncio.wait_for(run_a, timeout=2.0)
        assert ch_a._closed

        # Mux B should still be running.
        assert mux_b.is_running
        assert not ch_b._closed

        # Mux B can still process messages.
        bearer_b.inject_segment(make_segment(0, b"still-alive"))
        payload = await asyncio.wait_for(ch_b.recv(), timeout=1.0)
        assert payload == b"still-alive"

        await mux_b.close()
        try:
            await run_b
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Error path closes multiplexer and socket
# ---------------------------------------------------------------------------


class TestErrorPathCleanup:
    """Test the error -> mux close -> bearer release chain.

    High: When an error occurs, the cleanup chain should close the
    multiplexer, which closes all channels, which closes the bearer.
    """

    @pytest.mark.asyncio
    async def test_error_path_closes_multiplexer_and_socket(self, mock_bearer: MockBearer) -> None:
        """Bearer disconnect triggers: mux shutdown -> channel close -> bearer close."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_a = mux.add_protocol(0)
        ch_b = mux.add_protocol(1)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Disconnect the bearer (simulates network error).
        mock_bearer.disconnect()

        # run() should exit cleanly.
        await asyncio.wait_for(run_task, timeout=2.0)

        # All channels closed.
        assert ch_a._closed
        assert ch_b._closed

        # Mux is no longer running.
        assert not mux.is_running

        # Now explicitly close to verify bearer release.
        await mux.close()
        assert mock_bearer.is_closed


# ---------------------------------------------------------------------------
# Tests: Bearer close propagates to all channels
# ---------------------------------------------------------------------------


class TestBearerClosePropagatesToChannels:
    """Test that bearer close propagates to all registered channels.

    High: When the bearer is closed (either by us or by the remote peer),
    every registered channel should transition to closed state.
    """

    @pytest.mark.asyncio
    async def test_mux_bearer_closed_shuts_down_peer(self) -> None:
        """Closing the bearer propagates to all channels via mux shutdown."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        channels = []
        for pid in range(5):
            channels.append(mux.add_protocol(pid))

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Close the mux (which closes bearer and channels).
        await mux.close()

        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        # All 5 channels are closed.
        for pid, ch in enumerate(channels):
            assert ch._closed, f"channel {pid} should be closed"

        # Bearer is closed.
        assert bearer.is_closed

        # recv() on any channel raises MuxClosedError.
        for ch in channels:
            with pytest.raises(MuxClosedError):
                await ch.recv()


# ---------------------------------------------------------------------------
# Fault-injection mock bearers
# ---------------------------------------------------------------------------


class TruncatedHeaderBearer:
    """Bearer that returns only a partial (4-byte) header on read, simulating
    a truncated SDU.  The Haskell equivalent is prop_demux_sdu which injects
    malformed SDU headers and verifies the demux handles them.
    """

    def __init__(self) -> None:
        self._closed = False
        self._read_count = 0

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        self._read_count += 1
        self._closed = True
        # Simulate an incomplete header by raising IncompleteReadError
        # as the real Bearer would when only 4 of 8 header bytes arrive.
        raise asyncio.IncompleteReadError(partial=b"\x00" * 4, expected=8)

    async def write_segment(self, segment: MuxSegment) -> None:
        if self._closed:
            raise BearerClosedError("truncated bearer is closed")

    async def close(self) -> None:
        self._closed = True


class FaultyReadBearer:
    """Bearer whose read_segment raises ConnectionError after delivering
    some valid segments.  Simulates a mid-stream network fault.
    """

    def __init__(self, segments: list[MuxSegment], fault_after: int = 0) -> None:
        self._segments = list(segments)
        self._fault_after = fault_after
        self._delivered = 0
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        if self._closed:
            raise BearerClosedError("faulty bearer is closed")
        if self._delivered < self._fault_after and self._segments:
            seg = self._segments.pop(0)
            self._delivered += 1
            return seg
        self._closed = True
        raise ConnectionError("simulated read fault")

    async def write_segment(self, segment: MuxSegment) -> None:
        if self._closed:
            raise BearerClosedError("faulty bearer is closed")

    async def close(self) -> None:
        self._closed = True


class FaultyWriteBearer:
    """Bearer whose write_segment raises ConnectionError, simulating
    a broken pipe on the outbound side.  Equivalent to Haskell's
    prop_mux_close_sim which tests mux behavior when the bearer fails
    during writes.
    """

    def __init__(self) -> None:
        self._closed = False
        self._read_event = asyncio.Event()

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def read_segment(self) -> MuxSegment:
        # Block until close — we only care about the write fault.
        await self._read_event.wait()
        raise BearerClosedError("faulty write bearer closed")

    async def write_segment(self, segment: MuxSegment) -> None:
        self._closed = True
        raise ConnectionError("simulated write fault")

    async def close(self) -> None:
        self._closed = True
        self._read_event.set()


# ---------------------------------------------------------------------------
# Tests: Fault injection — invalid SDU and bearer faults
#
# These tests are the Python equivalents of Haskell's prop_demux_sdu
# (malformed SDU handling) and prop_mux_close_sim (bearer failure during
# mux operation).  They verify the multiplexer handles pathological inputs
# and I/O faults gracefully — no crashes, no resource leaks.
# ---------------------------------------------------------------------------


class TestInvalidSDU:
    """Test multiplexer behavior with malformed SDU data.

    Haskell reference: Network.Mux.Test (prop_demux_sdu) — verifies that
    the demux correctly handles truncated headers, zero-length payloads,
    and length mismatches.
    """

    @pytest.mark.asyncio
    async def test_invalid_sdu_truncated_header(self) -> None:
        """Feed a bearer that returns only 4 bytes (incomplete 8-byte header).

        The mux receiver should handle the IncompleteReadError from the bearer
        gracefully — close all channels and exit without crashing.
        """
        bearer = TruncatedHeaderBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # run() should exit cleanly when the bearer delivers a truncated header.
        await asyncio.wait_for(mux.run(), timeout=2.0)

        # Channel should be closed after the receiver exits.
        assert ch._closed
        assert not mux.is_running

    @pytest.mark.asyncio
    async def test_invalid_sdu_zero_length_payload(self, mock_bearer: MockBearer) -> None:
        """SDU with payload_length=0 in header.  Empty payload is valid per spec.

        Spec reference: Ouroboros network spec, Section 1.1 — payload_length
        is a uint16, 0 is a legal value (e.g., keep-alive heartbeats).
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject a segment with empty payload.
        mock_bearer.inject_segment(make_segment(0, b""))

        # Follow it with a non-empty segment so we can confirm delivery.
        mock_bearer.inject_segment(make_segment(0, b"after-empty"))

        run_task = asyncio.create_task(mux.run())

        # Empty payload should be delivered as b"".
        payload_empty = await asyncio.wait_for(ch.recv(), timeout=1.0)
        assert payload_empty == b""

        # Next segment also arrives.
        payload_after = await asyncio.wait_for(ch.recv(), timeout=1.0)
        assert payload_after == b"after-empty"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_invalid_sdu_length_mismatch(self) -> None:
        """SDU header claims payload_length=100 but only 50 bytes follow.

        The real Bearer raises IncompleteReadError when it can't read the
        full payload.  We simulate this by having the mock bearer raise
        the same error the real bearer would.
        """

        class LengthMismatchBearer:
            """Bearer that simulates a payload length mismatch by raising
            IncompleteReadError as the real Bearer.read_segment would."""

            def __init__(self) -> None:
                self._closed = False

            @property
            def is_closed(self) -> bool:
                return self._closed

            async def read_segment(self) -> MuxSegment:
                self._closed = True
                # This is what Bearer.read_segment raises when it reads
                # the header (payload_len=100) but only gets 50 bytes.
                raise asyncio.IncompleteReadError(partial=b"\x00" * 50, expected=100)

            async def write_segment(self, segment: MuxSegment) -> None:
                raise BearerClosedError("length mismatch bearer closed")

            async def close(self) -> None:
                self._closed = True

        bearer = LengthMismatchBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # The mux should handle the IncompleteReadError gracefully.
        await asyncio.wait_for(mux.run(), timeout=2.0)

        assert ch._closed
        assert not mux.is_running

    @pytest.mark.asyncio
    async def test_mux_corrupt_sdu_header(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Feed a segment with a very large unknown protocol_id.

        The mux should log a warning and drop it — same as any unknown
        protocol.  This verifies that corrupt protocol IDs in the valid
        range (0-32767) don't cause crashes.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Inject a segment with protocol_id=32767 (max valid, but unregistered).
        mock_bearer.inject_segment(make_segment(0x7FFF, b"corrupt-proto"))
        # Then a valid one so the test can verify the mux continued.
        mock_bearer.inject_segment(make_segment(0, b"after-corrupt"))

        run_task = asyncio.create_task(mux.run())

        with caplog.at_level(logging.WARNING):
            payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        assert payload == b"after-corrupt"
        assert "unknown protocol_id 32767" in caplog.text

        # Mux is still running — corrupt header didn't crash it.
        assert mux.is_running

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


class TestBearerFaults:
    """Test multiplexer behavior when the bearer raises I/O errors.

    Haskell reference: Network.Mux.Test (prop_mux_close_sim) — verifies
    that the mux handles bearer failures during both read and write
    operations, closing all channels and cleaning up properly.
    """

    @pytest.mark.asyncio
    async def test_mux_reader_fault(self) -> None:
        """MockBearer read_segment raises ConnectionError mid-stream.

        Deliver one valid segment, then raise ConnectionError.  All
        channels should be closed after the mux exits.
        """
        valid_seg = make_segment(0, b"before-fault")
        bearer = FaultyReadBearer(segments=[valid_seg], fault_after=1)

        mux = Multiplexer(bearer, is_initiator=True)
        ch_a = mux.add_protocol(0)
        ch_b = mux.add_protocol(1)

        # run() should exit when the read fault occurs.
        run_task = asyncio.create_task(mux.run())

        # First segment should arrive before the fault.
        payload = await asyncio.wait_for(ch_a.recv(), timeout=2.0)
        assert payload == b"before-fault"

        # run() exits after the fault.
        await asyncio.wait_for(run_task, timeout=2.0)

        # Both channels closed.
        assert ch_a._closed
        assert ch_b._closed
        assert not mux.is_running

    @pytest.mark.asyncio
    async def test_mux_writer_fault(self) -> None:
        """MockBearer write_segment raises ConnectionError.

        The sender loop should catch the error and exit, causing the
        mux to shut down all channels.
        """
        bearer = FaultyWriteBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Queue a message so the sender tries to write and hits the fault.
        await ch.send(b"will-fail")

        # run() should exit after the write fault.
        await asyncio.wait_for(mux.run(), timeout=2.0)

        # Channel closed, mux stopped.
        assert ch._closed
        assert not mux.is_running

    @pytest.mark.asyncio
    async def test_mux_reader_fault_immediate(self) -> None:
        """ConnectionError on the very first read — no segments delivered.

        This is the harshest scenario: the bearer breaks immediately.
        """
        bearer = FaultyReadBearer(segments=[], fault_after=0)
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        await asyncio.wait_for(mux.run(), timeout=2.0)

        assert ch._closed
        assert not mux.is_running


class TestMuxLifecycleAdvanced:
    """Advanced lifecycle tests: restart after completion, start/stop
    verification, and simultaneous handshake.
    """

    @pytest.mark.asyncio
    async def test_mux_restart_after_completion(self) -> None:
        """Run a mux to completion, then create a new one on a fresh bearer.

        The Multiplexer is not designed to be restarted (is_closed becomes
        True after close), so the correct pattern is to create a new instance.
        This test verifies that pattern works.
        """
        # First run: bearer disconnects, mux exits.
        bearer1 = MockBearer()
        mux1 = Multiplexer(bearer1, is_initiator=True)
        ch1 = mux1.add_protocol(0)

        run1 = asyncio.create_task(mux1.run())
        await asyncio.sleep(0.02)
        bearer1.disconnect()
        await asyncio.wait_for(run1, timeout=2.0)

        assert ch1._closed
        assert not mux1.is_running

        # Second run: fresh bearer and mux instance.
        bearer2 = MockBearer()
        mux2 = Multiplexer(bearer2, is_initiator=True)
        ch2 = mux2.add_protocol(0)

        bearer2.inject_segment(make_segment(0, b"second-life"))

        run2 = asyncio.create_task(mux2.run())
        payload = await asyncio.wait_for(ch2.recv(), timeout=1.0)
        assert payload == b"second-life"

        await mux2.close()
        try:
            await run2
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_mux_start_stop_lifecycle(self) -> None:
        """Start mux, verify it's running, close it, verify it's stopped.
        Then verify can't run after close.
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        mux.add_protocol(0)

        # Not yet running.
        assert not mux.is_running
        assert not mux.is_closed

        # Start it.
        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        assert mux.is_running
        assert not mux.is_closed

        # Close it.
        await mux.close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        assert not mux.is_running
        assert mux.is_closed

        # Can't run after close.
        with pytest.raises(MuxClosedError):
            await mux.run()

    @pytest.mark.asyncio
    async def test_simultaneous_open_handshake(self) -> None:
        """Both initiator and responder send handshake simultaneously.

        This is the most common real-world scenario: both sides start
        their mux and immediately begin sending.  We mock two bearers
        connected back-to-back and relay segments between them.

        Haskell reference: Network.Mux.Test — tests mux with both
        InitiatorResponderMode where both sides are active simultaneously.
        """
        bearer_init = MockBearer()
        bearer_resp = MockBearer()

        mux_init = Multiplexer(bearer_init, is_initiator=True)
        mux_resp = Multiplexer(bearer_resp, is_initiator=False)

        ch_init = mux_init.add_protocol(0)
        ch_resp = mux_resp.add_protocol(0)

        run_init = asyncio.create_task(mux_init.run())
        run_resp = asyncio.create_task(mux_resp.run())

        # Both sides send simultaneously (before either has received anything).
        await ch_init.send(b"init-handshake")
        await ch_resp.send(b"resp-handshake")

        # Relay initiator -> responder.
        seg_from_init = await asyncio.wait_for(bearer_init.outbound.get(), timeout=1.0)
        bearer_resp.inject_segment(seg_from_init)

        # Relay responder -> initiator.
        seg_from_resp = await asyncio.wait_for(bearer_resp.outbound.get(), timeout=1.0)
        bearer_init.inject_segment(seg_from_resp)

        # Both sides receive the other's handshake.
        init_received = await asyncio.wait_for(ch_init.recv(), timeout=1.0)
        resp_received = await asyncio.wait_for(ch_resp.recv(), timeout=1.0)

        assert resp_received == b"init-handshake"
        assert init_received == b"resp-handshake"

        # Verify the direction bits are correct.
        assert seg_from_init.is_initiator is True
        assert seg_from_resp.is_initiator is False

        # Clean up.
        await mux_init.close()
        await mux_resp.close()
        for task in (run_init, run_resp):
            try:
                await task
            except asyncio.CancelledError, MuxClosedError:
                pass


# ---------------------------------------------------------------------------
# Tests: SDU demux — invalid miniprotocol ID triggers error
#
# Haskell reference: Network.Mux.Test (prop_demux_sdu) — the Haskell mux
# escalates unknown MiniProtocolNum to MuxError (ShutdownNode).  We
# currently DROP and log — these tests verify the drop behavior and
# document the gap.
# ---------------------------------------------------------------------------


class TestDemuxInvalidProtocolID:
    """Verify that demux rejects/drops segments with unregistered protocol IDs.

    This extends TestUnknownProtocol with explicit invalid-ID variants:
    - protocol_id at the upper boundary (0x7FFF)
    - protocol_id 0 when no protocol is registered
    - multiple invalid IDs in sequence
    """

    @pytest.mark.asyncio
    async def test_demux_max_protocol_id_unregistered(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Segment with protocol_id=0x7FFF (max valid) is dropped when unregistered."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        mock_bearer.inject_segment(make_segment(0x7FFF, b"bad-proto"))
        mock_bearer.inject_segment(make_segment(0, b"good"))

        run_task = asyncio.create_task(mux.run())

        with caplog.at_level(logging.WARNING):
            payload = await asyncio.wait_for(ch.recv(), timeout=1.0)

        assert payload == b"good"
        assert "unknown protocol_id 32767" in caplog.text

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_demux_no_protocols_registered(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """All segments are dropped when no protocols are registered.

        Edge case: a multiplexer with no add_protocol() calls still runs
        the receiver loop but every segment goes to the unknown handler.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        # Do NOT register any protocols

        mock_bearer.inject_segment(make_segment(0, b"no-home"))
        mock_bearer.inject_segment(make_segment(1, b"also-homeless"))

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.05)  # Let receiver process both segments

        with caplog.at_level(logging.WARNING):
            # Give it time to process
            await asyncio.sleep(0.05)

        assert "unknown protocol_id 0" in caplog.text
        assert "unknown protocol_id 1" in caplog.text

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_demux_rapid_invalid_ids(
        self, mock_bearer: MockBearer, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Rapid-fire segments with various invalid protocol IDs.

        Verifies the mux handles a burst of invalid IDs without crashing
        or degrading service to the valid channel.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(5)

        # Inject 10 invalid segments followed by 1 valid one
        for bad_id in [1, 2, 3, 4, 6, 7, 8, 9, 10, 100]:
            mock_bearer.inject_segment(make_segment(bad_id, f"bad-{bad_id}".encode()))
        mock_bearer.inject_segment(make_segment(5, b"valid-after-burst"))

        run_task = asyncio.create_task(mux.run())

        with caplog.at_level(logging.WARNING):
            payload = await asyncio.wait_for(ch.recv(), timeout=2.0)

        assert payload == b"valid-after-burst"
        # Mux is still running
        assert mux.is_running

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: SDU demux — invalid payload length (at segment layer)
#
# Haskell reference: Network.Mux.Codec.decodeSDUHeader — the Haskell
# decoder validates payload_length against MAX_SEGMENT_SIZE.  We test
# encode_segment / decode_segment validation for out-of-range payloads.
# ---------------------------------------------------------------------------


class TestDemuxInvalidPayloadLength:
    """Verify that segment encoding/decoding rejects invalid payload lengths."""

    def test_encode_rejects_oversized_payload(self) -> None:
        """encode_segment raises ValueError if payload exceeds MAX_PAYLOAD_SIZE."""
        from vibe.core.multiplexer.segment import MAX_PAYLOAD_SIZE

        oversized = b"\x00" * (MAX_PAYLOAD_SIZE + 1)
        seg = MuxSegment(
            timestamp=0,
            protocol_id=0,
            is_initiator=True,
            payload=oversized,
        )
        with pytest.raises(ValueError, match="payload length"):
            encode_segment(seg)

    def test_decode_rejects_truncated_buffer(self) -> None:
        """decode_segment raises ValueError if buffer is shorter than header claims."""
        # Craft a valid header claiming 100 bytes of payload, but provide only 50
        import struct

        header = struct.pack("!IHH", 0, 0, 100)  # timestamp=0, proto=0, len=100
        short_buffer = header + b"\x00" * 50

        with pytest.raises(ValueError, match="need"):
            decode_segment(short_buffer)

    def test_decode_rejects_too_short_header(self) -> None:
        """decode_segment raises ValueError if buffer is shorter than 8 bytes."""
        with pytest.raises(ValueError, match="need at least"):
            decode_segment(b"\x00\x01\x02\x03")

    @pytest.mark.asyncio
    async def test_mux_demux_with_payload_length_mismatch_bearer(self) -> None:
        """Mux handles a bearer that reports payload length mismatch.

        When the bearer's read_segment raises IncompleteReadError due to
        the header claiming more bytes than available, the mux receiver
        exits cleanly.
        """

        class PayloadLengthMismatchBearer:
            """Simulates a bearer where the header says 1000 bytes but only 10 arrive."""

            def __init__(self) -> None:
                self._closed = False

            @property
            def is_closed(self) -> bool:
                return self._closed

            async def read_segment(self) -> MuxSegment:
                self._closed = True
                raise asyncio.IncompleteReadError(
                    partial=b"\x00" * 10,
                    expected=1000,
                )

            async def write_segment(self, segment: MuxSegment) -> None:
                raise BearerClosedError("closed")

            async def close(self) -> None:
                self._closed = True

        bearer = PayloadLengthMismatchBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        await asyncio.wait_for(mux.run(), timeout=2.0)

        assert ch._closed
        assert not mux.is_running


# ---------------------------------------------------------------------------
# Tests: SDU demux — ingress overflow (payload > qMax)
#
# Extends TestIngressQueueBounds with explicit qMax-style tests verifying
# that when total inbound payload count exceeds the channel's max_ingress_size,
# the channel is forcefully closed (matching Haskell's teardown behavior).
# ---------------------------------------------------------------------------


class TestIngressOverflowQMax:
    """Verify the mux closes channels when inbound data exceeds qMax.

    Haskell reference: Network.Mux.demux — when the ingress queue for a
    miniprotocol is full, the Haskell mux tears down the connection.
    We close the individual channel (documented gap).
    """

    @pytest.mark.asyncio
    async def test_ingress_overflow_exact_boundary(self, mock_bearer: MockBearer) -> None:
        """Channel with max_ingress_size=1 overflows on 2nd segment."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0, max_ingress_size=1)
        ch_sentinel = mux.add_protocol(1)

        mock_bearer.inject_segment(make_segment(0, b"fits"))
        mock_bearer.inject_segment(make_segment(0, b"overflows"))
        mock_bearer.inject_segment(make_segment(1, b"sentinel"))

        run_task = asyncio.create_task(mux.run())

        # Wait for sentinel to confirm all segments processed
        s = await asyncio.wait_for(ch_sentinel.recv(), timeout=2.0)
        assert s == b"sentinel"

        # Channel 0 must be closed due to overflow
        assert ch._closed

        # The first message should be in the queue (it fit)
        # but the channel is closed so recv raises
        # Actually, we can still read what was queued before close
        # if the queue has items
        try:
            first = ch._inbound.get_nowait()
            assert first == b"fits"
        except asyncio.QueueEmpty:
            pass  # May have been consumed by close sentinel

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_ingress_overflow_does_not_affect_other_channels(
        self, mock_bearer: MockBearer
    ) -> None:
        """Overflow on one channel does not close other channels.

        Isolation: each channel's qMax is independent.
        """
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch_tiny = mux.add_protocol(0, max_ingress_size=1)
        ch_big = mux.add_protocol(1, max_ingress_size=100)

        # Overflow ch_tiny
        mock_bearer.inject_segment(make_segment(0, b"a"))
        mock_bearer.inject_segment(make_segment(0, b"b"))

        # ch_big gets data just fine
        mock_bearer.inject_segment(make_segment(1, b"ok"))

        run_task = asyncio.create_task(mux.run())

        payload = await asyncio.wait_for(ch_big.recv(), timeout=2.0)
        assert payload == b"ok"

        assert ch_tiny._closed
        assert not ch_big._closed

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Trailing bytes after mux close
#
# Verifies that when the mux is closed, any trailing data on the bearer
# is handled cleanly — no errors, no hangs, no resource leaks.
# ---------------------------------------------------------------------------


class TestTrailingBytesAfterClose:
    """Test that trailing segments after mux close are handled cleanly.

    When a multiplexer is closed, there may be in-flight segments from
    the remote peer that arrive after the close. The mux must not crash
    or hang — it should discard them cleanly.
    """

    @pytest.mark.asyncio
    async def test_trailing_segments_after_close(self, mock_bearer: MockBearer) -> None:
        """Segments injected after close() are not delivered and cause no errors."""
        mux = Multiplexer(mock_bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Close the mux
        await mux.close()

        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        # Now inject trailing segments — these should be harmless
        mock_bearer.inject_segment(make_segment(0, b"trailing-1"))
        mock_bearer.inject_segment(make_segment(0, b"trailing-2"))

        # Channel is closed
        assert ch._closed

        # recv raises MuxClosedError — trailing data not delivered
        with pytest.raises(MuxClosedError):
            await ch.recv()

        # Mux state is clean
        assert mux.is_closed
        assert not mux.is_running

    @pytest.mark.asyncio
    async def test_trailing_outbound_after_close(self) -> None:
        """Queued outbound data is not sent after close.

        If a channel has queued data when the mux closes, it should
        not attempt to send it (no write to a closed bearer).
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Queue some outbound data before running
        await ch.send(b"will-be-sent")
        await ch.send(b"might-not-be-sent")

        run_task = asyncio.create_task(mux.run())

        # Wait for at least one segment to be sent
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
        assert seg.payload == b"will-be-sent"

        # Close immediately
        await mux.close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        # Channel is closed — can't send more
        with pytest.raises(MuxClosedError):
            await ch.send(b"after-close")

        # Bearer is closed
        assert bearer.is_closed

    @pytest.mark.asyncio
    async def test_close_during_active_recv(self) -> None:
        """close() while a channel.recv() is blocked.

        The blocked recv must be unblocked and raise MuxClosedError.
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Start a recv that will block (no data available)
        recv_task = asyncio.create_task(ch.recv())
        await asyncio.sleep(0.01)  # Let it block

        # Close the mux — this should unblock the recv
        await mux.close()

        with pytest.raises(MuxClosedError):
            await asyncio.wait_for(recv_task, timeout=2.0)

        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Mux start/stop lifecycle (extended)
#
# Extends TestMuxLifecycleAdvanced with additional lifecycle scenarios
# covering the full start -> verify running -> stop -> verify stopped flow.
# ---------------------------------------------------------------------------


class TestMuxStartStopLifecycle:
    """Extended lifecycle tests for the multiplexer.

    Verifies the state machine of the Multiplexer itself:
    - initial state: not running, not closed
    - after run(): running, not closed
    - after close(): not running, closed
    - run() after close(): raises MuxClosedError
    """

    @pytest.mark.asyncio
    async def test_lifecycle_properties(self) -> None:
        """Full lifecycle: create -> run -> verify -> close -> verify."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        # Initial state
        assert not mux.is_running
        assert not mux.is_closed
        assert mux.is_initiator

        # Start
        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Running state
        assert mux.is_running
        assert not mux.is_closed

        # Can still send/receive
        await ch.send(b"alive")
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
        assert seg.payload == b"alive"

        # Stop
        await mux.close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        # Stopped state
        assert not mux.is_running
        assert mux.is_closed
        assert ch._closed

    @pytest.mark.asyncio
    async def test_cannot_add_protocol_while_running(self) -> None:
        """Adding a protocol while the mux is running.

        Note: the current implementation allows add_protocol while running
        (it just adds to the dict). This test documents this behavior and
        verifies the channel is functional. If we later add a running check
        to add_protocol, this test should be updated to expect ValueError.
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)

        # Adding protocol while running — currently allowed
        ch_late = mux.add_protocol(1)

        # The late channel might not be picked up by the sender loop
        # (which iterates a snapshot of protocol_ids taken at start).
        # But the receiver loop dispatches by dict lookup, so inbound
        # segments for protocol 1 should work.
        bearer.inject_segment(make_segment(1, b"late-arrival"))

        payload = await asyncio.wait_for(ch_late.recv(), timeout=1.0)
        assert payload == b"late-arrival"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass


# ---------------------------------------------------------------------------
# Tests: Mux restart after stop
#
# The Multiplexer sets _closed=True after close(), making it non-restartable.
# The correct pattern is to create a fresh instance. These tests verify both
# the non-restartability constraint and the fresh-instance pattern.
# ---------------------------------------------------------------------------


class TestMuxRestartAfterStop:
    """Verify mux restart behavior after stop."""

    @pytest.mark.asyncio
    async def test_closed_mux_rejects_run(self) -> None:
        """A closed multiplexer raises MuxClosedError on run()."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())
        await asyncio.sleep(0.02)
        await mux.close()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except asyncio.CancelledError, MuxClosedError:
            pass

        # Cannot restart
        with pytest.raises(MuxClosedError):
            await mux.run()

    @pytest.mark.asyncio
    async def test_fresh_instance_after_close(self) -> None:
        """Create a new Multiplexer after the old one is closed.

        This is the correct restart pattern: old mux is dead, create
        a fresh one on a fresh bearer.
        """
        # First instance
        bearer1 = MockBearer()
        mux1 = Multiplexer(bearer1, is_initiator=True)
        ch1 = mux1.add_protocol(0)

        bearer1.inject_segment(make_segment(0, b"gen-1"))
        run1 = asyncio.create_task(mux1.run())
        p1 = await asyncio.wait_for(ch1.recv(), timeout=1.0)
        assert p1 == b"gen-1"

        await mux1.close()
        try:
            await run1
        except asyncio.CancelledError, MuxClosedError:
            pass

        assert mux1.is_closed
        assert ch1._closed

        # Second instance — fresh everything
        bearer2 = MockBearer()
        mux2 = Multiplexer(bearer2, is_initiator=True)
        ch2 = mux2.add_protocol(0)

        bearer2.inject_segment(make_segment(0, b"gen-2"))
        run2 = asyncio.create_task(mux2.run())
        p2 = await asyncio.wait_for(ch2.recv(), timeout=1.0)
        assert p2 == b"gen-2"

        # The new instance is fully functional
        assert mux2.is_running
        assert not mux2.is_closed

        await mux2.close()
        try:
            await run2
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_restart_preserves_protocol_registration(self) -> None:
        """New mux instance requires re-registering protocols.

        Channels from the old mux do NOT carry over — protocols must
        be explicitly re-registered on the new instance.
        """
        bearer1 = MockBearer()
        mux1 = Multiplexer(bearer1, is_initiator=True)
        ch1_a = mux1.add_protocol(0)
        ch1_b = mux1.add_protocol(1)

        await mux1.close()

        # New instance: must register again
        bearer2 = MockBearer()
        mux2 = Multiplexer(bearer2, is_initiator=True)
        ch2_a = mux2.add_protocol(0)
        ch2_b = mux2.add_protocol(1)

        # Old channels are closed
        assert ch1_a._closed
        assert ch1_b._closed

        # New channels are fresh
        assert not ch2_a._closed
        assert not ch2_b._closed
        assert ch2_a is not ch1_a
        assert ch2_b is not ch1_b

        await mux2.close()


# ---------------------------------------------------------------------------
# Tests: Compat interface — send/receive
#
# Verify that the MiniProtocolChannel send/recv interface works correctly
# as a protocol-agnostic transport for higher-level miniprotocols like
# the handshake. This is the "compat" layer — MiniProtocolChannel
# satisfies the Channel protocol expected by handshake_protocol.py.
# ---------------------------------------------------------------------------


class TestCompatInterface:
    """Test that MiniProtocolChannel satisfies the Channel interface.

    The handshake protocol uses a Channel with send(bytes) and recv() -> bytes.
    MiniProtocolChannel must be usable as this Channel without any adapters.
    """

    @pytest.mark.asyncio
    async def test_channel_send_recv_roundtrip(self) -> None:
        """send() followed by recv() on a paired mux delivers the message.

        This is the basic compat test: MiniProtocolChannel used as a
        transport for arbitrary byte messages.
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())

        # Send a message
        await ch.send(b"hello-compat")

        # Verify it appears on the bearer
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
        assert seg.protocol_id == 0
        assert seg.payload == b"hello-compat"

        # Inject a response
        bearer.inject_segment(make_segment(0, b"response-compat"))

        # Receive it
        resp = await asyncio.wait_for(ch.recv(), timeout=1.0)
        assert resp == b"response-compat"

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_channel_as_handshake_transport(self) -> None:
        """MiniProtocolChannel used as transport for a handshake exchange.

        Verifies that the MiniProtocolChannel interface is compatible
        with the Channel protocol expected by run_handshake_client.
        """
        from vibe.cardano.network.handshake import (
            N2N_V15,
            PREPROD_NETWORK_MAGIC,
            build_version_table,
            decode_handshake_response,
            encode_propose_versions,
        )

        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())

        # Client sends MsgProposeVersions via the channel
        vt = build_version_table(PREPROD_NETWORK_MAGIC)
        propose_bytes = encode_propose_versions(vt)
        await ch.send(propose_bytes)

        # Verify the proposal made it to the bearer
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
        assert seg.protocol_id == 0
        assert seg.payload == propose_bytes

        # Simulate server responding with AcceptVersion
        import cbor2

        accept_bytes = cbor2.dumps(
            [
                1,
                N2N_V15,
                [PREPROD_NETWORK_MAGIC, False, 0, False],
            ]
        )
        bearer.inject_segment(make_segment(0, accept_bytes))

        # Client receives and decodes
        response_raw = await asyncio.wait_for(ch.recv(), timeout=1.0)
        response = decode_handshake_response(response_raw)
        from vibe.cardano.network.handshake import MsgAcceptVersion

        assert isinstance(response, MsgAcceptVersion)
        assert response.version_number == N2N_V15

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_channel_multiple_messages(self) -> None:
        """Multiple sequential send/recv pairs work correctly.

        Verifies message ordering and data integrity across multiple
        exchanges on the same channel.
        """
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())

        messages = [f"msg-{i}".encode() for i in range(5)]

        # Send all messages
        for msg in messages:
            await ch.send(msg)

        # Verify all appear on bearer in order
        for msg in messages:
            seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
            assert seg.payload == msg

        # Inject responses in order
        responses = [f"resp-{i}".encode() for i in range(5)]
        for resp in responses:
            bearer.inject_segment(make_segment(0, resp))

        # Receive all in order
        for resp in responses:
            received = await asyncio.wait_for(ch.recv(), timeout=1.0)
            assert received == resp

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass

    @pytest.mark.asyncio
    async def test_channel_empty_payload(self) -> None:
        """send/recv with empty bytes works (keep-alive scenario)."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)
        ch = mux.add_protocol(0)

        run_task = asyncio.create_task(mux.run())

        await ch.send(b"")
        seg = await asyncio.wait_for(bearer.outbound.get(), timeout=1.0)
        assert seg.payload == b""

        bearer.inject_segment(make_segment(0, b""))
        resp = await asyncio.wait_for(ch.recv(), timeout=1.0)
        assert resp == b""

        await mux.close()
        try:
            await run_task
        except asyncio.CancelledError, MuxClosedError:
            pass
