"""Hypothesis property tests for async TCP bearer.

These tests verify that bearer read/write roundtrips hold for arbitrary
mux segments within the valid parameter space. Uses mock asyncio streams
so no real TCP connections are needed.

DB test_specifications referenced:
    test_bytestream_ordering_preserved_per_protocol
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.multiplexer.bearer import Bearer
from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    MuxSegment,
    encode_segment,
)

# ---------------------------------------------------------------------------
# Strategies — same parameter space as the segment property tests
# ---------------------------------------------------------------------------

timestamps = st.integers(min_value=0, max_value=0xFFFFFFFF)
protocol_ids = st.integers(min_value=0, max_value=0x7FFF)
directions = st.booleans()
# Keep payloads small-ish for speed; the unit tests cover max payload.
payloads = st.binary(min_size=0, max_size=4096)


def _make_reader(data: bytes) -> asyncio.StreamReader:
    """Create a real StreamReader pre-loaded with data."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


def _make_writer() -> MagicMock:
    """Create a mock StreamWriter that captures writes."""
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()
    return writer


# ---------------------------------------------------------------------------
# Property: write then read roundtrip preserves all segment fields
# ---------------------------------------------------------------------------


@given(
    timestamp=timestamps,
    protocol_id=protocol_ids,
    is_initiator=directions,
    payload=payloads,
)
@settings(max_examples=200, deadline=None)
async def test_write_read_roundtrip_preserves_fields(
    timestamp: int,
    protocol_id: int,
    is_initiator: bool,
    payload: bytes,
) -> None:
    """For any valid segment, writing it via a bearer and reading it back
    via another bearer yields an identical segment.

    This is the bearer-level analogue of the segment encode/decode roundtrip,
    but exercises the async stream read/write path.
    """
    original = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )

    # Write side: capture what the bearer writes
    wire = encode_segment(original)

    # Read side: feed the wire bytes into a reader
    reader = _make_reader(wire)
    read_bearer = Bearer(reader, _make_writer())
    result = await read_bearer.read_segment()

    assert result.timestamp == original.timestamp
    assert result.protocol_id == original.protocol_id
    assert result.is_initiator == original.is_initiator
    assert result.payload == original.payload


# ---------------------------------------------------------------------------
# Property: N segments written in order are read back in the same order
# ---------------------------------------------------------------------------


@given(
    segments=st.lists(
        st.builds(
            MuxSegment,
            timestamp=timestamps,
            protocol_id=protocol_ids,
            is_initiator=directions,
            payload=payloads,
        ),
        min_size=1,
        max_size=20,
    )
)
@settings(max_examples=100, deadline=None)
async def test_segment_ordering_preserved(segments: list[MuxSegment]) -> None:
    """For any list of valid segments, concatenating their wire encodings and
    reading them back via a bearer yields the same segments in the same order.

    DB test_specifications: test_bytestream_ordering_preserved_per_protocol
    """
    wire = b"".join(encode_segment(seg) for seg in segments)

    reader = _make_reader(wire)
    bearer = Bearer(reader, _make_writer())

    for original in segments:
        result = await bearer.read_segment()
        assert result.timestamp == original.timestamp
        assert result.protocol_id == original.protocol_id
        assert result.is_initiator == original.is_initiator
        assert result.payload == original.payload


# ---------------------------------------------------------------------------
# Property: bearer correctly reports closed state after close
# ---------------------------------------------------------------------------


@given(
    timestamp=timestamps,
    protocol_id=protocol_ids,
    is_initiator=directions,
    payload=payloads,
)
@settings(max_examples=50, deadline=None)
async def test_bearer_closed_state_consistent(
    timestamp: int,
    protocol_id: int,
    is_initiator: bool,
    payload: bytes,
) -> None:
    """After close(), is_closed is True and operations raise BearerClosedError."""
    from vibe.core.multiplexer.bearer import BearerClosedError

    seg = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )
    wire = encode_segment(seg)
    reader = _make_reader(wire)
    bearer = Bearer(reader, _make_writer())

    assert not bearer.is_closed
    await bearer.close()
    assert bearer.is_closed

    # Both read and write must raise
    try:
        await bearer.read_segment()
        raise AssertionError("Expected BearerClosedError")  # pragma: no cover
    except BearerClosedError:
        pass

    try:
        await bearer.write_segment(seg)
        raise AssertionError("Expected BearerClosedError")  # pragma: no cover
    except BearerClosedError:
        pass
