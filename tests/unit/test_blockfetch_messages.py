"""Tests for Block-Fetch miniprotocol CBOR message codec.

Covers encode/decode roundtrips, known CBOR byte vectors, point encoding,
message ID correctness, and error handling.

Derived from test specifications:
- test_block_fetch_state_machine_idle_to_busy_transition
- test_block_fetch_state_machine_idle_to_done_transition
- test_block_fetch_busy_start_batch_to_streaming
- test_block_fetch_busy_no_blocks_returns_to_idle
- test_block_fetch_streaming_batch_done_returns_to_idle
- test_block_fetch_size_limits_per_state
- test_block_fetch_message_within_idle_limit
- test_block_fetch_message_exceeds_idle_limit
- test_block_fetch_block_body_within_streaming_limit
- test_block_fetch_block_body_exceeds_streaming_limit
- test_block_fetch_message_at_exact_boundary
- test_block_fetch_client_server_round_trip_empty_range
- test_block_fetch_client_server_round_trip_with_blocks

Spec reference: ouroboros-network, Network.Protocol.BlockFetch.Codec
"""

from __future__ import annotations

import cbor2
import pytest

from vibe.cardano.network.blockfetch import (
    BLOCK_FETCH_N2N_ID,
    MSG_BATCH_DONE,
    MSG_BLOCK,
    MSG_CLIENT_DONE,
    MSG_NO_BLOCKS,
    MSG_REQUEST_RANGE,
    MSG_START_BATCH,
    MsgBatchDone,
    MsgBlock,
    MsgClientDone,
    MsgNoBlocks,
    MsgRequestRange,
    MsgStartBatch,
    decode_client_message,
    decode_server_message,
    encode_batch_done,
    encode_block,
    encode_client_done,
    encode_no_blocks,
    encode_request_range,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import (
    ORIGIN,
    Point,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

HASH_32 = b"\xab" * 32
HASH_32_ALT = b"\xcd" * 32

SAMPLE_POINT = Point(slot=42, hash=HASH_32)
SAMPLE_POINT_ALT = Point(slot=1000, hash=HASH_32_ALT)
SAMPLE_BLOCK = b"\xde\xad\xbe\xef" * 100  # 400 byte block body


# ---------------------------------------------------------------------------
# Message ID constants
# ---------------------------------------------------------------------------


class TestMessageIDs:
    """Verify message ID constants match the CBOR array index 0."""

    def test_request_range_id(self) -> None:
        assert MSG_REQUEST_RANGE == 0

    def test_client_done_id(self) -> None:
        assert MSG_CLIENT_DONE == 1

    def test_start_batch_id(self) -> None:
        assert MSG_START_BATCH == 2

    def test_no_blocks_id(self) -> None:
        assert MSG_NO_BLOCKS == 3

    def test_block_id(self) -> None:
        assert MSG_BLOCK == 4

    def test_batch_done_id(self) -> None:
        assert MSG_BATCH_DONE == 5

    def test_miniprotocol_n2n_id(self) -> None:
        """Block-fetch is miniprotocol ID 3 for node-to-node."""
        assert BLOCK_FETCH_N2N_ID == 3


# ---------------------------------------------------------------------------
# Dataclass message IDs
# ---------------------------------------------------------------------------


class TestDataclassMessageIDs:
    """Each dataclass exposes its msg_id matching the constant."""

    def test_request_range(self) -> None:
        msg = MsgRequestRange(point_from=SAMPLE_POINT, point_to=SAMPLE_POINT_ALT)
        assert msg.msg_id == MSG_REQUEST_RANGE

    def test_client_done(self) -> None:
        assert MsgClientDone().msg_id == MSG_CLIENT_DONE

    def test_start_batch(self) -> None:
        assert MsgStartBatch().msg_id == MSG_START_BATCH

    def test_no_blocks(self) -> None:
        assert MsgNoBlocks().msg_id == MSG_NO_BLOCKS

    def test_block(self) -> None:
        msg = MsgBlock(block_cbor=SAMPLE_BLOCK)
        assert msg.msg_id == MSG_BLOCK

    def test_batch_done(self) -> None:
        assert MsgBatchDone().msg_id == MSG_BATCH_DONE


# ---------------------------------------------------------------------------
# Known CBOR byte vectors
# ---------------------------------------------------------------------------


class TestKnownCBORVectors:
    """Verify exact CBOR byte output for known inputs."""

    def test_client_done_bytes(self) -> None:
        """MsgClientDone encodes as CBOR [1] = 0x81 0x01."""
        raw = encode_client_done()
        assert raw == bytes([0x81, 0x01])

    def test_start_batch_bytes(self) -> None:
        """MsgStartBatch encodes as CBOR [2] = 0x81 0x02."""
        raw = encode_start_batch()
        assert raw == bytes([0x81, 0x02])

    def test_no_blocks_bytes(self) -> None:
        """MsgNoBlocks encodes as CBOR [3] = 0x81 0x03."""
        raw = encode_no_blocks()
        assert raw == bytes([0x81, 0x03])

    def test_batch_done_bytes(self) -> None:
        """MsgBatchDone encodes as CBOR [5] = 0x81 0x05."""
        raw = encode_batch_done()
        assert raw == bytes([0x81, 0x05])

    def test_client_done_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [1]."""
        parsed = cbor2.loads(encode_client_done())
        assert parsed == [1]

    def test_start_batch_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [2]."""
        parsed = cbor2.loads(encode_start_batch())
        assert parsed == [2]

    def test_no_blocks_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [3]."""
        parsed = cbor2.loads(encode_no_blocks())
        assert parsed == [3]

    def test_batch_done_cbor_structure(self) -> None:
        """Decoded CBOR is exactly [5]."""
        parsed = cbor2.loads(encode_batch_done())
        assert parsed == [5]

    def test_request_range_cbor_structure(self) -> None:
        """Decoded CBOR for RequestRange has [0, point_from, point_to]."""
        raw = encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 0
        assert parsed[1] == [42, HASH_32]
        assert parsed[2] == [1000, HASH_32_ALT]

    def test_request_range_origin_points(self) -> None:
        """RequestRange with origin points: [0, [], []]."""
        raw = encode_request_range(ORIGIN, ORIGIN)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 0
        assert parsed[1] == []
        assert parsed[2] == []

    def test_block_cbor_structure(self) -> None:
        """Decoded CBOR for Block has [4, block_bytes]."""
        block_data = b"\x42" * 100
        raw = encode_block(block_data)
        parsed = cbor2.loads(raw)
        assert parsed[0] == 4
        # encode_block wraps in CBOR-in-CBOR (Tag 24 + byte string)
        assert hasattr(parsed[1], 'tag') and parsed[1].tag == 24
        assert parsed[1].value == block_data


# ---------------------------------------------------------------------------
# Encode/decode roundtrip -- client messages
# ---------------------------------------------------------------------------


class TestClientMessageRoundtrip:
    """Encode then decode client messages and verify fidelity."""

    def test_request_range_roundtrip(self) -> None:
        raw = encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgRequestRange)
        assert msg.point_from == SAMPLE_POINT
        assert msg.point_to == SAMPLE_POINT_ALT

    def test_request_range_origin_roundtrip(self) -> None:
        raw = encode_request_range(ORIGIN, SAMPLE_POINT)
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgRequestRange)
        assert msg.point_from == ORIGIN
        assert msg.point_to == SAMPLE_POINT

    def test_request_range_both_origin_roundtrip(self) -> None:
        raw = encode_request_range(ORIGIN, ORIGIN)
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgRequestRange)
        assert msg.point_from == ORIGIN
        assert msg.point_to == ORIGIN

    def test_client_done_roundtrip(self) -> None:
        raw = encode_client_done()
        msg = decode_client_message(raw)
        assert isinstance(msg, MsgClientDone)
        assert msg.msg_id == MSG_CLIENT_DONE


# ---------------------------------------------------------------------------
# Encode/decode roundtrip -- server messages
# ---------------------------------------------------------------------------


class TestServerMessageRoundtrip:
    """Encode then decode server messages and verify fidelity."""

    def test_start_batch_roundtrip(self) -> None:
        raw = encode_start_batch()
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgStartBatch)

    def test_no_blocks_roundtrip(self) -> None:
        raw = encode_no_blocks()
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgNoBlocks)

    def test_block_roundtrip(self) -> None:
        raw = encode_block(SAMPLE_BLOCK)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgBlock)
        assert msg.block_cbor == SAMPLE_BLOCK

    def test_block_large_body_roundtrip(self) -> None:
        """MsgBlock with a realistically-sized block body (2MB)."""
        large_block = b"\x42" * 2_000_000
        raw = encode_block(large_block)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgBlock)
        assert msg.block_cbor == large_block

    def test_block_empty_body_roundtrip(self) -> None:
        """MsgBlock with empty block body."""
        raw = encode_block(b"")
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgBlock)
        assert msg.block_cbor == b""

    def test_batch_done_roundtrip(self) -> None:
        raw = encode_batch_done()
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgBatchDone)

    def test_block_with_cbor_block_body(self) -> None:
        """MsgBlock with CBOR-encoded block body roundtrips correctly."""
        fake_block = cbor2.dumps({"era": 7, "body": b"\xaa" * 256, "hash": HASH_32})
        raw = encode_block(fake_block)
        msg = decode_server_message(raw)
        assert isinstance(msg, MsgBlock)
        assert msg.block_cbor == fake_block
        # Verify we can decode the block body later
        decoded = cbor2.loads(msg.block_cbor)
        assert decoded["era"] == 7


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestDecodeErrors:
    """Verify error handling for malformed messages."""

    def test_decode_server_unknown_msg_id(self) -> None:
        raw = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_decode_server_not_a_list(self) -> None:
        raw = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(raw)

    def test_decode_server_empty_list(self) -> None:
        raw = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(raw)

    def test_decode_client_unknown_msg_id(self) -> None:
        raw = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_decode_client_not_a_list(self) -> None:
        raw = cbor2.dumps("hello")
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_client_message(raw)

    def test_decode_request_range_wrong_length(self) -> None:
        """MsgRequestRange with wrong number of elements."""
        raw = cbor2.dumps([0, [42, HASH_32]])
        with pytest.raises(ValueError, match="expected 3 elements"):
            decode_client_message(raw)

    def test_decode_client_done_wrong_length(self) -> None:
        raw = cbor2.dumps([1, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_client_message(raw)

    def test_decode_start_batch_wrong_length(self) -> None:
        raw = cbor2.dumps([2, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_server_message(raw)

    def test_decode_no_blocks_wrong_length(self) -> None:
        raw = cbor2.dumps([3, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_server_message(raw)

    def test_decode_block_wrong_length(self) -> None:
        raw = cbor2.dumps([4])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_server_message(raw)

    def test_decode_batch_done_wrong_length(self) -> None:
        raw = cbor2.dumps([5, "extra"])
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_server_message(raw)

    def test_invalid_point_in_request_range(self) -> None:
        """A point with 1 element is invalid (must be 0 or 2)."""
        raw = cbor2.dumps([0, [42], [1000, HASH_32_ALT]])
        with pytest.raises(ValueError, match="Invalid point encoding"):
            decode_client_message(raw)


# ---------------------------------------------------------------------------
# Cross-decode: client encodes, server decodes (and vice versa)
# ---------------------------------------------------------------------------


class TestCrossDecode:
    """Client messages decoded by server decoder should fail (wrong IDs)."""

    def test_server_decoder_rejects_request_range(self) -> None:
        raw = encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_server_decoder_rejects_client_done(self) -> None:
        raw = encode_client_done()
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(raw)

    def test_client_decoder_rejects_start_batch(self) -> None:
        raw = encode_start_batch()
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_client_decoder_rejects_no_blocks(self) -> None:
        raw = encode_no_blocks()
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_client_decoder_rejects_block(self) -> None:
        raw = encode_block(SAMPLE_BLOCK)
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)

    def test_client_decoder_rejects_batch_done(self) -> None:
        raw = encode_batch_done()
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(raw)


# ---------------------------------------------------------------------------
# Full encode -> decode -> re-encode roundtrip
# ---------------------------------------------------------------------------


class TestFullRoundtrip:
    """Every block-fetch message roundtrips through encode/decode/re-encode."""

    def test_all_messages_roundtrip(self) -> None:
        messages_and_encoders: list[tuple[bytes, str]] = [
            (encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT), "client"),
            (encode_request_range(ORIGIN, SAMPLE_POINT), "client"),
            (encode_client_done(), "client"),
            (encode_start_batch(), "server"),
            (encode_no_blocks(), "server"),
            (encode_block(SAMPLE_BLOCK), "server"),
            (encode_block(b""), "server"),
            (encode_batch_done(), "server"),
        ]

        for original_bytes, side in messages_and_encoders:
            if side == "server":
                msg = decode_server_message(original_bytes)
            else:
                msg = decode_client_message(original_bytes)

            # Re-encode based on message type
            if isinstance(msg, MsgRequestRange):
                re_encoded = encode_request_range(msg.point_from, msg.point_to)
            elif isinstance(msg, MsgClientDone):
                re_encoded = encode_client_done()
            elif isinstance(msg, MsgStartBatch):
                re_encoded = encode_start_batch()
            elif isinstance(msg, MsgNoBlocks):
                re_encoded = encode_no_blocks()
            elif isinstance(msg, MsgBlock):
                re_encoded = encode_block(msg.block_cbor)
            elif isinstance(msg, MsgBatchDone):
                re_encoded = encode_batch_done()
            else:
                raise AssertionError(f"Unknown message type: {type(msg)}")

            assert re_encoded == original_bytes, (
                f"Roundtrip failed for {type(msg).__name__}: "
                f"original={original_bytes.hex()} re_encoded={re_encoded.hex()}"
            )


# ---------------------------------------------------------------------------
# Message size conformance (from test specs)
# ---------------------------------------------------------------------------


class TestMessageSize:
    """From test specs: test_block_fetch_message_within_idle_limit,
    test_block_fetch_message_exceeds_idle_limit,
    test_block_fetch_block_body_within_streaming_limit,
    test_block_fetch_block_body_exceeds_streaming_limit,
    test_block_fetch_message_at_exact_boundary.
    """

    def test_request_range_within_idle_limit(self) -> None:
        """MsgRequestRange serializes well under the 65535-byte idle limit."""
        raw = encode_request_range(SAMPLE_POINT, SAMPLE_POINT_ALT)
        assert len(raw) < 65535

    def test_client_done_within_idle_limit(self) -> None:
        """MsgClientDone serializes to 2 bytes, well under 65535."""
        raw = encode_client_done()
        assert len(raw) < 65535

    def test_block_within_streaming_limit(self) -> None:
        """A ~2MB block body stays under the 2,500,000 byte streaming limit."""
        block_data = b"\x42" * 2_000_000
        raw = encode_block(block_data)
        assert len(raw) < 2_500_000

    def test_block_body_exceeds_streaming_limit(self) -> None:
        """A block body over 2.5MB exceeds the streaming limit."""
        block_data = b"\x42" * 2_500_000
        raw = encode_block(block_data)
        assert len(raw) > 2_500_000


# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    """Messages are frozen dataclasses."""

    def test_request_range_frozen(self) -> None:
        msg = MsgRequestRange(point_from=SAMPLE_POINT, point_to=SAMPLE_POINT_ALT)
        with pytest.raises(AttributeError):
            msg.point_from = ORIGIN  # type: ignore[misc]

    def test_block_frozen(self) -> None:
        msg = MsgBlock(block_cbor=SAMPLE_BLOCK)
        with pytest.raises(AttributeError):
            msg.block_cbor = b""  # type: ignore[misc]

    def test_client_done_frozen(self) -> None:
        with pytest.raises(AttributeError):
            MsgClientDone().msg_id = 99  # type: ignore[misc]
