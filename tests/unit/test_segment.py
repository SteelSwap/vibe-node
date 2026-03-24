"""Unit tests for Ouroboros multiplexer segment framing.

Tests encode/decode of the 8-byte SDU header as defined in the Ouroboros
network spec, Section 1.1 "Wire Format".
"""

from __future__ import annotations

import struct

import pytest

from vibe.core.multiplexer.segment import (
    DEFAULT_TIMEOUT,
    HANDSHAKE_TIMEOUT,
    MAX_PAYLOAD_SIZE,
    N2N_SDU_MAX_SIZE,
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


class TestSDUConstants:
    """Verify SDU size and timeout constants match the Haskell reference.

    DB test_specifications: test_node_to_node_sdu_max_size_constant,
    test_sdu_handshake_timeout_constant.
    """

    def test_node_to_node_sdu_max_size_constant(self) -> None:
        """N2N SDU max size must be exactly 12288 bytes (12 KiB).

        Haskell ref: Network.Mux.Types.sduSize = 12288
        """
        assert N2N_SDU_MAX_SIZE == 12288

    def test_max_payload_size_constant(self) -> None:
        """Segment-level MAX_PAYLOAD_SIZE must be 65535 (uint16 max)."""
        assert MAX_PAYLOAD_SIZE == 65535

    def test_n2n_sdu_max_less_than_segment_max(self) -> None:
        """The N2N SDU limit is stricter than the segment payload limit."""
        assert N2N_SDU_MAX_SIZE < MAX_PAYLOAD_SIZE

    def test_sdu_handshake_timeout_constant(self) -> None:
        """Handshake timeout must be 10 seconds."""
        assert HANDSHAKE_TIMEOUT == 10

    def test_sdu_default_timeout_constant(self) -> None:
        """Default SDU timeout must be 30 seconds."""
        assert DEFAULT_TIMEOUT == 30


class TestMixedProtocols:
    """Verify segments with different protocol_ids stay separate.

    DB test_specifications: test_segment_mixed_protocols_in_sequence.
    """

    def test_segment_mixed_protocols_in_sequence(self) -> None:
        """Encoding two segments with different protocol_ids produces
        separate valid segments that decode independently.
        """
        seg_a = MuxSegment(
            timestamp=100,
            protocol_id=2,
            is_initiator=True,
            payload=b"chain-sync",
        )
        seg_b = MuxSegment(
            timestamp=200,
            protocol_id=5,
            is_initiator=False,
            payload=b"block-fetch",
        )

        wire_a = encode_segment(seg_a)
        wire_b = encode_segment(seg_b)

        # Concatenate on the wire (as a mux would)
        combined = wire_a + wire_b

        # Decode first segment
        decoded_a, consumed_a = decode_segment(combined)
        assert decoded_a.protocol_id == 2
        assert decoded_a.is_initiator is True
        assert decoded_a.payload == b"chain-sync"

        # Decode second segment from remainder
        decoded_b, consumed_b = decode_segment(combined[consumed_a:])
        assert decoded_b.protocol_id == 5
        assert decoded_b.is_initiator is False
        assert decoded_b.payload == b"block-fetch"

        # Total bytes consumed equals the combined length
        assert consumed_a + consumed_b == len(combined)


class TestSingleSegmentEncoding:
    """Verify that payloads within limit encode to exactly one segment.

    DB test_specifications: test_single_message_fits_in_one_segment.
    """

    def test_single_message_fits_in_one_segment(self) -> None:
        """When payload <= MAX_PAYLOAD_SIZE, encoding produces exactly
        1 segment: 8-byte header + payload, nothing more.
        """
        payload = b"\xfe" * 1024  # 1 KiB, well within limit
        seg = MuxSegment(
            timestamp=0,
            protocol_id=7,
            is_initiator=True,
            payload=payload,
        )
        wire = encode_segment(seg)

        # Exactly one segment: header + payload, no trailing data
        assert len(wire) == SEGMENT_HEADER_SIZE + len(payload)

        # Decode consumes the entire buffer
        decoded, consumed = decode_segment(wire)
        assert consumed == len(wire)
        assert decoded.payload == payload

    def test_single_message_empty_payload(self) -> None:
        """Empty payload still produces exactly one segment (header only)."""
        seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=b"")
        wire = encode_segment(seg)
        assert len(wire) == SEGMENT_HEADER_SIZE

    def test_single_message_at_max_payload(self) -> None:
        """Payload at exactly MAX_PAYLOAD_SIZE still fits in one segment."""
        seg = MuxSegment(
            timestamp=0,
            protocol_id=1,
            is_initiator=True,
            payload=b"\x00" * MAX_PAYLOAD_SIZE,
        )
        wire = encode_segment(seg)
        assert len(wire) == SEGMENT_HEADER_SIZE + MAX_PAYLOAD_SIZE
