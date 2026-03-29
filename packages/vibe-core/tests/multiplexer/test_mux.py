"""Tests for dual-channel (bidirectional) multiplexer support.

Validates that the mux supports both initiator and responder channels
per protocol_id, matching Haskell's (MiniProtocolNum, MiniProtocolDir) keying.

Haskell reference:
    Network.Mux.Types — MuxMode InitiatorResponderMode keys by (num, dir).
    Network.Mux.demux — flips direction on receive: remote initiator → local responder.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from vibe.core.multiplexer.bearer import Bearer, BearerClosedError
from vibe.core.multiplexer.mux import (
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
)
from vibe.core.multiplexer.segment import MuxSegment, decode_segment, encode_segment


# ---------------------------------------------------------------------------
# MockBearer — in-memory bearer for unit tests
# ---------------------------------------------------------------------------


class MockBearer:
    """In-memory bearer that records written segments and feeds reads from a queue.

    Implements the same interface as Bearer (write_segment, read_segment, close)
    without needing real TCP sockets.
    """

    def __init__(self) -> None:
        self.written_segments: list[MuxSegment] = []
        self._read_queue: asyncio.Queue[MuxSegment | None] = asyncio.Queue()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def write_segment(self, segment: MuxSegment) -> None:
        if self._closed:
            raise BearerClosedError("mock bearer closed")
        self.written_segments.append(segment)

    async def read_segment(self) -> MuxSegment:
        if self._closed:
            raise BearerClosedError("mock bearer closed")
        item = await self._read_queue.get()
        if item is None:
            self._closed = True
            raise BearerClosedError("mock bearer closed")
        return item

    def feed_segment(self, segment: MuxSegment) -> None:
        """Enqueue a segment for the receiver to read."""
        self._read_queue.put_nowait(segment)

    async def close(self) -> None:
        self._closed = True
        # Unblock any pending read_segment
        try:
            self._read_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    def buffer_segment(self, segment: MuxSegment) -> None:
        self.written_segments.append(segment)

    async def flush(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests: add_protocol_pair
# ---------------------------------------------------------------------------


class TestAddProtocolPair:
    """Tests for the new add_protocol_pair() method."""

    def test_returns_two_channels_with_correct_directions(self) -> None:
        """add_protocol_pair returns (initiator_channel, responder_channel)."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        init_ch, resp_ch = mux.add_protocol_pair(protocol_id=2)

        assert isinstance(init_ch, MiniProtocolChannel)
        assert isinstance(resp_ch, MiniProtocolChannel)
        assert init_ch.protocol_id == 2
        assert resp_ch.protocol_id == 2
        assert init_ch.is_initiator is True
        assert resp_ch.is_initiator is False

    def test_channels_keyed_by_tuple(self) -> None:
        """Both channels should be registered under (protocol_id, direction) keys."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        mux.add_protocol_pair(protocol_id=5)

        assert (5, True) in mux._channels
        assert (5, False) in mux._channels

    def test_duplicate_raises_value_error(self) -> None:
        """Registering the same protocol_id pair twice raises ValueError."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        mux.add_protocol_pair(protocol_id=3)

        with pytest.raises(ValueError, match="already registered"):
            mux.add_protocol_pair(protocol_id=3)

    def test_max_ingress_size_applied(self) -> None:
        """max_ingress_size is applied to both channels."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        init_ch, resp_ch = mux.add_protocol_pair(protocol_id=7, max_ingress_size=10)

        assert init_ch.max_ingress_size == 10
        assert resp_ch.max_ingress_size == 10

    def test_on_closed_mux_raises(self) -> None:
        """add_protocol_pair on a closed mux raises MuxClosedError."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]
        mux._closed = True

        with pytest.raises(MuxClosedError):
            mux.add_protocol_pair(protocol_id=1)


# ---------------------------------------------------------------------------
# Tests: add_protocol backward compat
# ---------------------------------------------------------------------------


class TestAddProtocolBackwardCompat:
    """Tests that the original add_protocol still works, keying by direction."""

    def test_initiator_mux_keys_by_true(self) -> None:
        """On an initiator mux, add_protocol keys by (pid, True)."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        ch = mux.add_protocol(protocol_id=4)

        assert (4, True) in mux._channels
        assert ch.is_initiator is True

    def test_responder_mux_keys_by_false(self) -> None:
        """On a responder mux, add_protocol keys by (pid, False)."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=False)  # type: ignore[arg-type]

        ch = mux.add_protocol(protocol_id=4)

        assert (4, False) in mux._channels
        assert ch.is_initiator is False

    def test_duplicate_single_direction_raises(self) -> None:
        """Registering same protocol+direction twice raises ValueError."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        mux.add_protocol(protocol_id=4)

        with pytest.raises(ValueError, match="already registered"):
            mux.add_protocol(protocol_id=4)


# ---------------------------------------------------------------------------
# Tests: sender uses per-channel is_initiator for direction bit
# ---------------------------------------------------------------------------


class TestSenderDirectionBit:
    """Sender must use channel.is_initiator, not mux._is_initiator, for segments."""

    @pytest.mark.asyncio
    async def test_sender_uses_channel_direction(self) -> None:
        """When sending, the segment's is_initiator matches the channel, not the mux."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        init_ch, resp_ch = mux.add_protocol_pair(protocol_id=2)

        # Queue data on both channels
        await init_ch._outbound.put(b"from-initiator")
        await resp_ch._outbound.put(b"from-responder")

        # Run sender for a brief moment
        mux._running = True
        sender_task = asyncio.create_task(mux._sender_loop())
        await asyncio.sleep(0.05)
        mux._closed = True
        mux._stop_event.set()
        mux._data_available.set()
        try:
            await asyncio.wait_for(sender_task, timeout=1.0)
        except Exception:
            pass

        # Check written segments
        assert len(bearer.written_segments) >= 2

        init_seg = [s for s in bearer.written_segments if s.payload == b"from-initiator"]
        resp_seg = [s for s in bearer.written_segments if s.payload == b"from-responder"]

        assert len(init_seg) == 1
        assert init_seg[0].is_initiator is True
        assert init_seg[0].protocol_id == 2

        assert len(resp_seg) == 1
        assert resp_seg[0].is_initiator is False
        assert resp_seg[0].protocol_id == 2


# ---------------------------------------------------------------------------
# Tests: receiver flips direction when routing
# ---------------------------------------------------------------------------


class TestReceiverDirectionFlip:
    """Receiver must flip direction: remote's initiator → local's responder."""

    @pytest.mark.asyncio
    async def test_receiver_routes_to_flipped_direction(self) -> None:
        """A segment marked is_initiator=True routes to the local responder channel."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        init_ch, resp_ch = mux.add_protocol_pair(protocol_id=2)

        # Feed a segment from the remote's initiator side
        bearer.feed_segment(
            MuxSegment(
                timestamp=0,
                protocol_id=2,
                is_initiator=True,  # remote is initiator
                payload=b"hello-from-remote-init",
            )
        )

        # Run receiver briefly
        mux._running = True
        receiver_task = asyncio.create_task(mux._receiver_loop())
        await asyncio.sleep(0.05)
        mux._closed = True
        await bearer.close()
        try:
            await asyncio.wait_for(receiver_task, timeout=1.0)
        except Exception:
            pass

        # The data should land in the responder channel (flipped)
        assert not resp_ch._inbound.empty()
        data = resp_ch._inbound.get_nowait()
        assert data == b"hello-from-remote-init"

        # Initiator channel should be empty
        assert init_ch._inbound.empty()

    @pytest.mark.asyncio
    async def test_receiver_routes_responder_to_initiator(self) -> None:
        """A segment marked is_initiator=False routes to the local initiator channel."""
        bearer = MockBearer()
        mux = Multiplexer(bearer, is_initiator=True)  # type: ignore[arg-type]

        init_ch, resp_ch = mux.add_protocol_pair(protocol_id=2)

        # Feed a segment from the remote's responder side
        bearer.feed_segment(
            MuxSegment(
                timestamp=0,
                protocol_id=2,
                is_initiator=False,  # remote is responder
                payload=b"hello-from-remote-resp",
            )
        )

        mux._running = True
        receiver_task = asyncio.create_task(mux._receiver_loop())
        await asyncio.sleep(0.05)
        mux._closed = True
        await bearer.close()
        try:
            await asyncio.wait_for(receiver_task, timeout=1.0)
        except Exception:
            pass

        # The data should land in the initiator channel (flipped)
        assert not init_ch._inbound.empty()
        data = init_ch._inbound.get_nowait()
        assert data == b"hello-from-remote-resp"

        # Responder channel should be empty
        assert resp_ch._inbound.empty()
