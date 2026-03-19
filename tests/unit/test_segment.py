"""Unit tests for Ouroboros multiplexer segment framing.

Tests encode/decode of the 8-byte SDU header as defined in the Ouroboros
network spec, Section 1.1 "Wire Format".
"""

from __future__ import annotations

import struct

import pytest

from vibe.core.multiplexer.segment import (
    MAX_PAYLOAD_SIZE,
    SEGMENT_HEADER_SIZE,
    MuxSegment,
    decode_segment,
    encode_segment,
)


class TestEncodeDecodeRoundtrip:
    """Encode a segment, decode it, verify all fields match."""

    def test_encode_decode_roundtrip(self) -> None:
        payload = b"hello ouroboros"
        seg = MuxSegment(
            timestamp=1_000_000,
            protocol_id=2,
            is_initiator=True,
            payload=payload,
        )
        wire = encode_segment(seg)
        decoded, consumed = decode_segment(wire)

        assert decoded.timestamp == seg.timestamp
        assert decoded.protocol_id == seg.protocol_id
        assert decoded.is_initiator == seg.is_initiator
        assert decoded.payload == seg.payload
        assert consumed == len(wire)

    def test_roundtrip_responder(self) -> None:
        seg = MuxSegment(
            timestamp=42,
            protocol_id=5,
            is_initiator=False,
            payload=b"\x01\x02\x03",
        )
        wire = encode_segment(seg)
        decoded, consumed = decode_segment(wire)

        assert decoded.timestamp == 42
        assert decoded.protocol_id == 5
        assert decoded.is_initiator is False
        assert decoded.payload == b"\x01\x02\x03"
        assert consumed == SEGMENT_HEADER_SIZE + 3


class TestInitiatorBit:
    """Verify the M bit (bit 15 of bytes 4-5) follows the spec.

    Spec: M=0 for initiator, M=1 for responder.
    Haskell: InitiatorDir -> n, ResponderDir -> n .|. 0x8000
    """

    def test_initiator_bit_clear_for_initiator(self) -> None:
        seg = MuxSegment(timestamp=0, protocol_id=3, is_initiator=True, payload=b"")
        wire = encode_segment(seg)
        proto_word = struct.unpack_from("!H", wire, 4)[0]
        # Bit 15 must be 0 for initiator
        assert proto_word & 0x8000 == 0
        assert proto_word == 3

    def test_initiator_bit_set_for_responder(self) -> None:
        seg = MuxSegment(timestamp=0, protocol_id=3, is_initiator=False, payload=b"")
        wire = encode_segment(seg)
        proto_word = struct.unpack_from("!H", wire, 4)[0]
        # Bit 15 must be 1 for responder
        assert proto_word & 0x8000 == 0x8000
        assert proto_word == 3 | 0x8000


class TestMaxPayload:
    """65535-byte payload encodes and decodes correctly."""

    def test_max_payload(self) -> None:
        payload = b"\xab" * MAX_PAYLOAD_SIZE
        assert len(payload) == MAX_PAYLOAD_SIZE

        seg = MuxSegment(
            timestamp=0xFFFFFFFF,
            protocol_id=0x7FFF,
            is_initiator=True,
            payload=payload,
        )
        wire = encode_segment(seg)
        assert len(wire) == SEGMENT_HEADER_SIZE + MAX_PAYLOAD_SIZE

        decoded, consumed = decode_segment(wire)
        assert decoded.payload == payload
        assert consumed == len(wire)

    def test_payload_too_large(self) -> None:
        seg = MuxSegment(
            timestamp=0,
            protocol_id=0,
            is_initiator=True,
            payload=b"\x00" * (MAX_PAYLOAD_SIZE + 1),
        )
        with pytest.raises(ValueError, match="payload length"):
            encode_segment(seg)


class TestZeroPayload:
    """Empty payload works correctly."""

    def test_zero_payload(self) -> None:
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"")
        wire = encode_segment(seg)
        assert len(wire) == SEGMENT_HEADER_SIZE

        decoded, consumed = decode_segment(wire)
        assert decoded.payload == b""
        assert decoded.protocol_id == 0
        assert consumed == SEGMENT_HEADER_SIZE


class TestKnownBytes:
    """Encode with known values and compare against expected byte sequence.

    Hand-computed expected bytes:
        timestamp  = 0x00_0F_42_40  (1,000,000 us = 1 second)
        proto_word = 0x00_02        (protocol_id=2, initiator, M=0)
        length     = 0x00_05        (5 byte payload)
        payload    = b"hello"
    """

    def test_known_bytes_initiator(self) -> None:
        seg = MuxSegment(
            timestamp=0x000F4240,
            protocol_id=2,
            is_initiator=True,
            payload=b"hello",
        )
        wire = encode_segment(seg)
        expected = (
            b"\x00\x0f\x42\x40"  # timestamp
            b"\x00\x02"  # M=0 | protocol_id=2
            b"\x00\x05"  # payload length
            b"hello"  # payload
        )
        assert wire == expected

    def test_known_bytes_responder(self) -> None:
        seg = MuxSegment(
            timestamp=0x000F4240,
            protocol_id=2,
            is_initiator=False,
            payload=b"hello",
        )
        wire = encode_segment(seg)
        expected = (
            b"\x00\x0f\x42\x40"  # timestamp
            b"\x80\x02"  # M=1 | protocol_id=2
            b"\x00\x05"  # payload length
            b"hello"  # payload
        )
        assert wire == expected


class TestDecodeErrors:
    """Decode raises on malformed input."""

    def test_short_header(self) -> None:
        with pytest.raises(ValueError, match="need at least 8 bytes"):
            decode_segment(b"\x00" * 7)

    def test_short_payload(self) -> None:
        # Header says 10 bytes of payload but only 5 follow
        header = struct.pack("!IHH", 0, 0, 10)
        with pytest.raises(ValueError, match="need 18 bytes"):
            decode_segment(header + b"\x00" * 5)
