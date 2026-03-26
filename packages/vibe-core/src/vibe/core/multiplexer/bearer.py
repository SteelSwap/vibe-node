"""Async TCP bearer — read/write mux segments over asyncio streams.

Wraps asyncio.StreamReader / asyncio.StreamWriter to transport Ouroboros
multiplexer segments (SDUs) over a TCP connection. Each segment is framed
with an 8-byte header followed by a variable-length payload, as defined in
the Ouroboros network spec, Section 1.1 "Wire Format".

Haskell reference:
    Network.Mux.Bearer.Socket (socketAsBearer)
    Network.Mux.Codec (encodeSDU / decodeSDUHeader)

Spec reference:
    Ouroboros network spec, Chapter 1 "Multiplexing mini-protocols",
    Section 1.1 "Wire Format", Table 1.1 (segment header layout).
"""

from __future__ import annotations

import asyncio
import struct

from vibe.core.multiplexer.segment import (
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    encode_segment,
)

# struct format for the header — mirrors segment.py's _HEADER_FMT
_HEADER_STRUCT = struct.Struct("!IHH")

# Bit 15 distinguishes initiator (0) from responder (1).
_MODE_BIT: int = 0x8000
_PROTOCOL_MASK: int = 0x7FFF


class BearerError(Exception):
    """Base exception for bearer-level errors."""


class BearerClosedError(BearerError):
    """Raised when an operation is attempted on a closed bearer.

    Haskell reference: Network.Mux.Types.MuxBearerClosed
    """


class Bearer:
    """Async TCP bearer for Ouroboros multiplexer segments.

    Reads and writes framed mux segments over asyncio streams. Each segment
    consists of an 8-byte header (timestamp, mode|protocol_id, payload length)
    followed by the payload bytes.

    Haskell reference: Network.Mux.Bearer.Socket.socketAsBearer
    """

    __slots__ = ("_reader", "_writer", "_closed")

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """True if the bearer has been closed."""
        return self._closed

    async def read_segment(self) -> MuxSegment:
        """Read exactly one mux segment from the stream.

        Reads the 8-byte header, parses the payload length, then reads
        exactly that many payload bytes.

        Returns:
            The decoded MuxSegment.

        Raises:
            BearerClosedError: If the bearer is already closed.
            ConnectionError: On broken pipe or connection reset.
            asyncio.IncompleteReadError: On unexpected disconnect mid-read.
            ValueError: On malformed segment header (e.g. impossible field values).
        """
        if self._closed:
            raise BearerClosedError("bearer is closed")

        try:
            # Read exactly 8 header bytes.
            # StreamReader.readexactly raises IncompleteReadError if the
            # connection closes before delivering all requested bytes.
            header = await self._reader.readexactly(SEGMENT_HEADER_SIZE)
        except asyncio.IncompleteReadError as exc:
            self._closed = True
            if len(exc.partial) == 0:
                raise ConnectionError("connection closed by peer") from exc
            raise
        except (ConnectionError, OSError) as exc:
            self._closed = True
            raise ConnectionError(str(exc)) from exc

        # Parse header fields.
        timestamp, proto_word, payload_len = _HEADER_STRUCT.unpack(header)

        is_initiator = (proto_word & _MODE_BIT) == 0
        protocol_id = proto_word & _PROTOCOL_MASK

        # Read exact payload bytes.
        if payload_len > 0:
            try:
                payload = await self._reader.readexactly(payload_len)
            except asyncio.IncompleteReadError:
                self._closed = True
                raise
            except (ConnectionError, OSError) as exc:
                self._closed = True
                raise ConnectionError(str(exc)) from exc
        else:
            payload = b""

        return MuxSegment(
            timestamp=timestamp,
            protocol_id=protocol_id,
            is_initiator=is_initiator,
            payload=payload,
        )

    async def write_segment(self, segment: MuxSegment) -> None:
        """Encode and write a mux segment to the stream.

        Args:
            segment: The MuxSegment to send.

        Raises:
            BearerClosedError: If the bearer is already closed.
            ConnectionError: On broken pipe or connection reset.
            ValueError: If the segment fields are out of range (from encode_segment).
        """
        if self._closed:
            raise BearerClosedError("bearer is closed")

        wire = encode_segment(segment)

        try:
            self._writer.write(wire)
            # Only drain when the write buffer exceeds 64KB. Small writes
            # (e.g. MsgRequestRange ~100 bytes) skip the syscall entirely
            # and let the OS TCP stack flush naturally. This avoids the
            # per-segment drain() latency that was our main overhead.
            try:
                buf_size = self._writer.transport.get_write_buffer_size()
                if buf_size > 65536:
                    await self._writer.drain()
            except (AttributeError, TypeError):
                pass
        except (ConnectionError, OSError) as exc:
            self._closed = True
            raise ConnectionError(str(exc)) from exc

    def buffer_segment(self, segment: MuxSegment) -> None:
        """Buffer a segment without flushing to the socket.

        Call flush() after buffering one or more segments to send them
        all in a single syscall. Used by the mux sender to batch writes
        across a round-robin pass.

        Raises:
            BearerClosedError: If the bearer is already closed.
        """
        if self._closed:
            raise BearerClosedError("bearer is closed")
        wire = encode_segment(segment)
        self._writer.write(wire)

    async def flush(self) -> None:
        """Flush all buffered writes to the socket.

        Raises:
            BearerClosedError: If the bearer is already closed.
            ConnectionError: On broken pipe or connection reset.
        """
        if self._closed:
            raise BearerClosedError("bearer is closed")
        try:
            await self._writer.drain()
        except (ConnectionError, OSError) as exc:
            self._closed = True
            raise ConnectionError(str(exc)) from exc

    async def close(self) -> None:
        """Close the underlying transport.

        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except ConnectionError, OSError:
            # Already broken — nothing to do.
            pass


async def connect(host: str, port: int) -> Bearer:
    """Open a TCP connection and return a Bearer.

    Args:
        host: Hostname or IP address.
        port: TCP port number.

    Returns:
        A connected Bearer ready for segment I/O.

    Raises:
        ConnectionError: If the TCP connection cannot be established.
        OSError: On DNS or network-level failures.
    """
    reader, writer = await asyncio.open_connection(host, port)
    return Bearer(reader, writer)
