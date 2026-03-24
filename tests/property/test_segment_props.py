"""Hypothesis property tests for Ouroboros multiplexer segment framing.

These tests verify that encode/decode roundtrips hold for arbitrary inputs
within the valid parameter space defined by the wire format.
"""

from __future__ import annotations

import struct

from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    decode_segment,
    encode_segment,
)

# Strategies matching the wire format constraints
timestamps = st.integers(min_value=0, max_value=0xFFFFFFFF)
protocol_ids = st.integers(min_value=0, max_value=0x7FFF)
directions = st.booleans()
# Cap payload size at a reasonable level for fast tests; max_payload test below
# exercises the full 65535 range explicitly.
payloads = st.binary(min_size=0, max_size=MAX_PAYLOAD_SIZE)


@given(
    timestamp=timestamps,
    protocol_id=protocol_ids,
    is_initiator=directions,
    payload=payloads,
)
@settings(max_examples=200, deadline=None)
def test_roundtrip_arbitrary(
    timestamp: int,
    protocol_id: int,
    is_initiator: bool,
    payload: bytes,
) -> None:
    """Random protocol_id, payload, timestamp, and direction roundtrip."""
    seg = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )
    wire = encode_segment(seg)
    decoded, consumed = decode_segment(wire)

    assert decoded.timestamp == seg.timestamp
    assert decoded.protocol_id == seg.protocol_id
    assert decoded.is_initiator == seg.is_initiator
    assert decoded.payload == seg.payload
    assert consumed == SEGMENT_HEADER_SIZE + len(payload)


@given(
    timestamp=timestamps,
    protocol_id=protocol_ids,
    is_initiator=directions,
    payload=payloads,
)
@settings(max_examples=200, deadline=None)
def test_header_always_8_bytes(
    timestamp: int,
    protocol_id: int,
    is_initiator: bool,
    payload: bytes,
) -> None:
    """Encoded header is always exactly 8 bytes regardless of payload."""
    seg = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )
    wire = encode_segment(seg)
    assert len(wire) == SEGMENT_HEADER_SIZE + len(payload)
    # The header portion is always 8 bytes
    assert len(wire) >= SEGMENT_HEADER_SIZE


@given(
    timestamp=timestamps,
    protocol_id=protocol_ids,
    is_initiator=directions,
    payload=payloads,
)
@settings(max_examples=200, deadline=None)
def test_segment_payload_never_exceeds_max(
    timestamp: int,
    protocol_id: int,
    is_initiator: bool,
    payload: bytes,
) -> None:
    """Encoded segment payload length always <= MAX_PAYLOAD_SIZE.

    DB test_specifications: test_segment_payload_never_exceeds_max.
    """
    seg = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=payload,
    )
    wire = encode_segment(seg)

    # Extract the payload length field from the header (bytes 6-7, big-endian uint16)
    payload_len_on_wire = struct.unpack_from("!H", wire, 6)[0]
    assert payload_len_on_wire <= MAX_PAYLOAD_SIZE

    # Also verify the actual payload bytes match
    actual_payload = wire[SEGMENT_HEADER_SIZE:]
    assert len(actual_payload) == payload_len_on_wire
    assert len(actual_payload) <= MAX_PAYLOAD_SIZE


@given(
    protocol_id=st.integers(min_value=0, max_value=0x7FFF),
    is_initiator=directions,
    timestamp=timestamps,
)
@settings(max_examples=300, deadline=None)
def test_mux_demux_roundtrip_valid_protocol_ids(
    protocol_id: int,
    is_initiator: bool,
    timestamp: int,
) -> None:
    """Roundtrip preserves protocol_id for all valid values (0..32767).

    DB test_specifications: test_mux_demux_roundtrip_valid_protocol_ids.
    """
    seg = MuxSegment(
        timestamp=timestamp,
        protocol_id=protocol_id,
        is_initiator=is_initiator,
        payload=b"roundtrip",
    )
    wire = encode_segment(seg)
    decoded, consumed = decode_segment(wire)

    assert decoded.protocol_id == protocol_id
    assert decoded.is_initiator == is_initiator
    assert decoded.timestamp == timestamp
    assert consumed == SEGMENT_HEADER_SIZE + len(b"roundtrip")
