"""Unit tests for async TCP bearer — read/write mux segments over asyncio streams.

Tests use mock asyncio.StreamReader / asyncio.StreamWriter objects to verify
bearer behavior without real TCP connections.

DB test_specifications referenced:
    test_mux_bearer_closed_shuts_down_peer_only
    test_mini_protocols_share_single_bearer
    test_bytestream_ordering_preserved_per_protocol
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe.core.multiplexer.bearer import (
    Bearer,
    BearerClosedError,
    BearerError,
    connect,
)
from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    encode_segment,
)


# ---------------------------------------------------------------------------
# Helpers — mock stream factory
# ---------------------------------------------------------------------------


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


def _make_bearer(data: bytes = b"") -> tuple[Bearer, MagicMock]:
    """Create a Bearer with a pre-loaded reader and mock writer."""
    reader = _make_reader(data)
    writer = _make_writer()
    return Bearer(reader, writer), writer


# ---------------------------------------------------------------------------
# Read segment tests
# ---------------------------------------------------------------------------


class TestReadSegment:
    """Test Bearer.read_segment() with mock streams."""

    async def test_read_single_segment(self) -> None:
        """Read a single well-formed segment."""
        seg = MuxSegment(timestamp=1000, protocol_id=2, is_initiator=True, payload=b"hello")
        wire = encode_segment(seg)
        bearer, _ = _make_bearer(wire)

        result = await bearer.read_segment()

        assert result.timestamp == 1000
        assert result.protocol_id == 2
        assert result.is_initiator is True
        assert result.payload == b"hello"

    async def test_read_responder_segment(self) -> None:
        """Read a segment with is_initiator=False (M=1 bit set)."""
        seg = MuxSegment(timestamp=42, protocol_id=5, is_initiator=False, payload=b"\x01\x02")
        wire = encode_segment(seg)
        bearer, _ = _make_bearer(wire)

        result = await bearer.read_segment()

        assert result.is_initiator is False
        assert result.protocol_id == 5
        assert result.payload == b"\x01\x02"

    async def test_read_empty_payload(self) -> None:
        """Read a segment with zero-length payload."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"")
        wire = encode_segment(seg)
        bearer, _ = _make_bearer(wire)

        result = await bearer.read_segment()

        assert result.payload == b""
        assert result.protocol_id == 0

    async def test_read_max_payload(self) -> None:
        """Read a segment with maximum payload size (65535 bytes)."""
        payload = b"\xab" * MAX_PAYLOAD_SIZE
        seg = MuxSegment(timestamp=0xFFFFFFFF, protocol_id=0x7FFF, is_initiator=True, payload=payload)
        wire = encode_segment(seg)
        bearer, _ = _make_bearer(wire)

        result = await bearer.read_segment()

        assert result.payload == payload
        assert len(result.payload) == MAX_PAYLOAD_SIZE

    async def test_read_multiple_segments_sequentially(self) -> None:
        """Read two segments from a single stream in sequence.

        DB test_specifications: test_bytestream_ordering_preserved_per_protocol
        """
        seg_a = MuxSegment(timestamp=100, protocol_id=2, is_initiator=True, payload=b"chain-sync")
        seg_b = MuxSegment(timestamp=200, protocol_id=5, is_initiator=False, payload=b"block-fetch")
        wire = encode_segment(seg_a) + encode_segment(seg_b)
        bearer, _ = _make_bearer(wire)

        result_a = await bearer.read_segment()
        result_b = await bearer.read_segment()

        assert result_a.protocol_id == 2
        assert result_a.payload == b"chain-sync"
        assert result_b.protocol_id == 5
        assert result_b.payload == b"block-fetch"


# ---------------------------------------------------------------------------
# Write segment tests
# ---------------------------------------------------------------------------


class TestWriteSegment:
    """Test Bearer.write_segment() with mock streams."""

    async def test_write_segment(self) -> None:
        """Write a segment — verify the exact bytes sent to the writer."""
        seg = MuxSegment(timestamp=1000, protocol_id=2, is_initiator=True, payload=b"hello")
        expected_wire = encode_segment(seg)
        bearer, writer = _make_bearer()

        await bearer.write_segment(seg)

        writer.write.assert_called_once_with(expected_wire)
        writer.drain.assert_awaited_once()

    async def test_write_empty_payload(self) -> None:
        """Write a segment with empty payload."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"")
        bearer, writer = _make_bearer()

        await bearer.write_segment(seg)

        data = writer.write.call_args[0][0]
        assert len(data) == SEGMENT_HEADER_SIZE

    async def test_write_invalid_segment_raises_valueerror(self) -> None:
        """Write a segment with out-of-range fields raises ValueError."""
        seg = MuxSegment(
            timestamp=0,
            protocol_id=0,
            is_initiator=True,
            payload=b"\x00" * (MAX_PAYLOAD_SIZE + 1),
        )
        bearer, _ = _make_bearer()

        with pytest.raises(ValueError, match="payload length"):
            await bearer.write_segment(seg)


# ---------------------------------------------------------------------------
# Connection error handling
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    """Test error handling on broken/closed connections."""

    async def test_read_on_closed_bearer_raises(self) -> None:
        """Reading from a closed bearer raises BearerClosedError."""
        bearer, _ = _make_bearer()
        await bearer.close()

        with pytest.raises(BearerClosedError, match="bearer is closed"):
            await bearer.read_segment()

    async def test_write_on_closed_bearer_raises(self) -> None:
        """Writing to a closed bearer raises BearerClosedError."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"")
        bearer, _ = _make_bearer()
        await bearer.close()

        with pytest.raises(BearerClosedError, match="bearer is closed"):
            await bearer.write_segment(seg)

    async def test_read_eof_with_no_data_raises_connection_error(self) -> None:
        """If the peer closes with 0 bytes read, raise ConnectionError.

        DB test_specifications: test_mux_bearer_closed_shuts_down_peer_only
        """
        bearer, _ = _make_bearer(b"")  # EOF immediately

        with pytest.raises(ConnectionError, match="connection closed by peer"):
            await bearer.read_segment()

        assert bearer.is_closed

    async def test_read_partial_header_raises_incomplete_read(self) -> None:
        """If the peer closes mid-header, raise IncompleteReadError."""
        # Feed only 4 of the required 8 header bytes
        bearer, _ = _make_bearer(b"\x00" * 4)

        with pytest.raises(asyncio.IncompleteReadError):
            await bearer.read_segment()

        assert bearer.is_closed

    async def test_read_partial_payload_raises_incomplete_read(self) -> None:
        """If the peer closes mid-payload, raise IncompleteReadError."""
        # Valid header saying 10 bytes of payload, but only 5 follow
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"\x00" * 10)
        wire = encode_segment(seg)
        # Truncate: header (8 bytes) + only 5 of 10 payload bytes
        bearer, _ = _make_bearer(wire[:SEGMENT_HEADER_SIZE + 5])

        with pytest.raises(asyncio.IncompleteReadError):
            await bearer.read_segment()

        assert bearer.is_closed

    async def test_write_broken_pipe_raises_connection_error(self) -> None:
        """Write on a broken pipe raises ConnectionError and marks closed."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"x")
        bearer, writer = _make_bearer()
        writer.drain = AsyncMock(side_effect=BrokenPipeError("broken pipe"))

        with pytest.raises(ConnectionError, match="broken pipe"):
            await bearer.write_segment(seg)

        assert bearer.is_closed

    async def test_write_connection_reset_raises_connection_error(self) -> None:
        """Write on a reset connection raises ConnectionError."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"x")
        bearer, writer = _make_bearer()
        writer.drain = AsyncMock(side_effect=ConnectionResetError("reset"))

        with pytest.raises(ConnectionError):
            await bearer.write_segment(seg)

        assert bearer.is_closed


# ---------------------------------------------------------------------------
# Close behavior
# ---------------------------------------------------------------------------


class TestClose:
    """Test Bearer.close() behavior."""

    async def test_close_calls_writer_close(self) -> None:
        """close() calls writer.close() and wait_closed()."""
        bearer, writer = _make_bearer()

        await bearer.close()

        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()
        assert bearer.is_closed

    async def test_close_idempotent(self) -> None:
        """Calling close() multiple times is safe."""
        bearer, writer = _make_bearer()

        await bearer.close()
        await bearer.close()

        # Only called once despite two close() calls
        writer.close.assert_called_once()

    async def test_close_on_already_broken_connection(self) -> None:
        """close() on a broken connection does not raise."""
        bearer, writer = _make_bearer()
        writer.wait_closed = AsyncMock(side_effect=ConnectionResetError("reset"))

        # Should not raise
        await bearer.close()
        assert bearer.is_closed


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestBearerProperties:
    """Test Bearer property accessors."""

    async def test_is_closed_initially_false(self) -> None:
        bearer, _ = _make_bearer()
        assert bearer.is_closed is False

    async def test_is_closed_after_close(self) -> None:
        bearer, _ = _make_bearer()
        await bearer.close()
        assert bearer.is_closed is True


# ---------------------------------------------------------------------------
# Mini-protocols sharing a single bearer
# ---------------------------------------------------------------------------


class TestMultiProtocol:
    """Verify multiple mini-protocols can share a single bearer.

    DB test_specifications: test_mini_protocols_share_single_bearer
    """

    async def test_mini_protocols_share_single_bearer(self) -> None:
        """Multiple protocol_ids interleaved on one bearer demux correctly."""
        segments = [
            MuxSegment(timestamp=i * 100, protocol_id=pid, is_initiator=True, payload=f"msg-{pid}".encode())
            for i, pid in enumerate([0, 2, 3, 5, 7])
        ]
        wire = b"".join(encode_segment(s) for s in segments)
        bearer, _ = _make_bearer(wire)

        results = [await bearer.read_segment() for _ in segments]

        for original, result in zip(segments, results):
            assert result.protocol_id == original.protocol_id
            assert result.payload == original.payload


# ---------------------------------------------------------------------------
# connect() function
# ---------------------------------------------------------------------------


class TestConnect:
    """Test the connect() convenience function."""

    async def test_connect_returns_bearer(self) -> None:
        """connect() returns a Bearer wrapping the opened streams."""
        mock_reader = asyncio.StreamReader()
        mock_writer = _make_writer()

        with patch("vibe.core.multiplexer.bearer.asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.return_value = (mock_reader, mock_writer)
            bearer = await connect("127.0.0.1", 3001)

        assert isinstance(bearer, Bearer)
        assert bearer.is_closed is False
        mock_open.assert_awaited_once_with("127.0.0.1", 3001)

    async def test_connect_propagates_connection_error(self) -> None:
        """connect() propagates connection failures."""
        with patch("vibe.core.multiplexer.bearer.asyncio.open_connection", new_callable=AsyncMock) as mock_open:
            mock_open.side_effect = ConnectionRefusedError("refused")

            with pytest.raises(ConnectionRefusedError):
                await connect("127.0.0.1", 9999)


# ---------------------------------------------------------------------------
# BearerError hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Verify exception class hierarchy."""

    def test_bearer_closed_error_is_bearer_error(self) -> None:
        assert issubclass(BearerClosedError, BearerError)

    def test_bearer_error_is_exception(self) -> None:
        assert issubclass(BearerError, Exception)
