"""Ouroboros multiplexer segment framing — encode/decode 8-byte SDU headers.

Wire format (big-endian, 8 bytes total):
    Bytes 0-3: Transmission time (uint32) — lower 32 bits of sender's
               monotonic clock in microseconds.
    Bytes 4-5: Mode bit (bit 15) + Mini Protocol ID (bits 14-0).
               M=0 → initiator (has initial agency),
               M=1 → responder.
    Bytes 6-7: Payload length (uint16) — max 2^16 - 1 = 65535 bytes.

Spec reference:
    Ouroboros network spec, Chapter 1 "Multiplexing mini-protocols",
    Section 1.1 "Wire Format", Table 1.1 (segment header layout).
    Source: IntersectMBO/ouroboros-network, docs/network-spec/mux.tex

Haskell reference:
    Network.Mux.Codec.encodeSDU / decodeSDUHeader
    InitiatorDir → M=0, ResponderDir → M=0x8000
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# Header: 4 (timestamp) + 2 (mode|protocol_id) + 2 (payload length) = 8 bytes
SEGMENT_HEADER_SIZE: int = 8

# Maximum payload per the wire format (uint16 max).
MAX_PAYLOAD_SIZE: int = 65535

# Node-to-node SDU maximum size (12 KiB).
# Haskell reference: Network.Mux.Types.sduSize = 12288
# The Haskell mux splits any message larger than this into multiple segments.
N2N_SDU_MAX_SIZE: int = 12288

# Timeout constants for the multiplexer (seconds).
# Haskell reference: Network.Mux.Types (handshake timeout, SDU timeout).
HANDSHAKE_TIMEOUT: int = 10
DEFAULT_TIMEOUT: int = 30

# struct format: big-endian uint32 + uint16 + uint16
_HEADER_FMT = "!IHH"
_HEADER_STRUCT = struct.Struct(_HEADER_FMT)

# Bit 15 of the protocol_id word distinguishes initiator (0) from responder (1).
_MODE_BIT: int = 0x8000
_PROTOCOL_MASK: int = 0x7FFF


@dataclass(frozen=True, slots=True)
class MuxSegment:
    """A single Ouroboros multiplexer segment (SDU).

    Attributes:
        timestamp: Transmission time — lower 32 bits of the sender's
            monotonic clock in microseconds.
        protocol_id: Mini-protocol number (0-32767).
        is_initiator: True if the segment originates from the initiator
            (the side that initially holds agency). On the wire, the
            initiator sets M=0 and the responder sets M=1.
        payload: The segment payload bytes.
    """

    timestamp: int
    protocol_id: int
    is_initiator: bool
    payload: bytes


def encode_segment(segment: MuxSegment) -> bytes:
    """Encode a MuxSegment into its on-wire representation.

    Returns the 8-byte header concatenated with the payload.

    Raises:
        ValueError: If protocol_id, timestamp, or payload length is out of range.
    """
    if not (0 <= segment.protocol_id <= _PROTOCOL_MASK):
        raise ValueError(
            f"protocol_id must be 0..{_PROTOCOL_MASK}, got {segment.protocol_id}"
        )
    if not (0 <= segment.timestamp <= 0xFFFFFFFF):
        raise ValueError(
            f"timestamp must be 0..{0xFFFFFFFF}, got {segment.timestamp}"
        )
    payload_len = len(segment.payload)
    if payload_len > MAX_PAYLOAD_SIZE:
        raise ValueError(
            f"payload length must be 0..{MAX_PAYLOAD_SIZE}, got {payload_len}"
        )

    # Spec: M=0 for initiator, M=1 (0x8000) for responder.
    # Haskell: InitiatorDir → n, ResponderDir → n .|. 0x8000
    proto_word = segment.protocol_id
    if not segment.is_initiator:
        proto_word |= _MODE_BIT

    header = _HEADER_STRUCT.pack(segment.timestamp, proto_word, payload_len)
    return header + segment.payload


def decode_segment(data: bytes) -> tuple[MuxSegment, int]:
    """Decode a MuxSegment from a bytes buffer.

    Args:
        data: Buffer containing at least an 8-byte header followed by
            the indicated payload bytes.

    Returns:
        A tuple of (decoded MuxSegment, total bytes consumed).

    Raises:
        ValueError: If the buffer is too short for the header or payload.
    """
    if len(data) < SEGMENT_HEADER_SIZE:
        raise ValueError(
            f"need at least {SEGMENT_HEADER_SIZE} bytes for header, "
            f"got {len(data)}"
        )

    timestamp, proto_word, payload_len = _HEADER_STRUCT.unpack_from(data)

    total = SEGMENT_HEADER_SIZE + payload_len
    if len(data) < total:
        raise ValueError(
            f"need {total} bytes (header + payload), got {len(data)}"
        )

    is_initiator = (proto_word & _MODE_BIT) == 0
    protocol_id = proto_word & _PROTOCOL_MASK
    payload = data[SEGMENT_HEADER_SIZE:total]

    segment = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=bytes(payload),
    )
    return segment, total
