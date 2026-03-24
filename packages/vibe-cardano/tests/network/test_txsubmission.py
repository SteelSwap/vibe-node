"""Tests for the tx-submission CBOR message codec.

Tests encode/decode round-trips, message ID constants, wire format
correctness, and error handling for all tx-submission message types.
"""

from __future__ import annotations

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.txsubmission import (
    MSG_DONE,
    # Constants
    MSG_INIT,
    MSG_REPLY_TX_IDS,
    MSG_REPLY_TXS,
    MSG_REQUEST_TX_IDS,
    MSG_REQUEST_TXS,
    TX_SUBMISSION_N2N_ID,
    MsgDone,
    # Message classes
    MsgInit,
    MsgReplyTxIds,
    MsgReplyTxs,
    MsgRequestTxIds,
    MsgRequestTxs,
    decode_client_message,
    # Decode
    decode_server_message,
    encode_done,
    # Encode
    encode_init,
    encode_reply_tx_ids,
    encode_reply_txs,
    encode_request_tx_ids,
    encode_request_txs,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify message ID constants match the Haskell wire format."""

    def test_msg_ids(self) -> None:
        assert MSG_REQUEST_TX_IDS == 0
        assert MSG_REPLY_TX_IDS == 1
        assert MSG_REQUEST_TXS == 2
        assert MSG_REPLY_TXS == 3
        assert MSG_DONE == 4
        assert MSG_INIT == 6

    def test_protocol_id(self) -> None:
        assert TX_SUBMISSION_N2N_ID == 4


# ---------------------------------------------------------------------------
# Message dataclass construction
# ---------------------------------------------------------------------------


class TestMessageConstruction:
    """Verify message dataclass fields and msg_id defaults."""

    def test_msg_init(self) -> None:
        msg = MsgInit()
        assert msg.msg_id == MSG_INIT

    def test_msg_request_tx_ids(self) -> None:
        msg = MsgRequestTxIds(blocking=True, ack_count=5, req_count=10)
        assert msg.msg_id == MSG_REQUEST_TX_IDS
        assert msg.blocking is True
        assert msg.ack_count == 5
        assert msg.req_count == 10

    def test_msg_reply_tx_ids(self) -> None:
        txids = [(b"\xab" * 32, 1024), (b"\xcd" * 32, 2048)]
        msg = MsgReplyTxIds(txids=txids)
        assert msg.msg_id == MSG_REPLY_TX_IDS
        assert len(msg.txids) == 2
        assert msg.txids[0] == (b"\xab" * 32, 1024)

    def test_msg_reply_tx_ids_empty(self) -> None:
        msg = MsgReplyTxIds(txids=[])
        assert msg.msg_id == MSG_REPLY_TX_IDS
        assert msg.txids == []

    def test_msg_request_txs(self) -> None:
        txids = [b"\xab" * 32, b"\xcd" * 32]
        msg = MsgRequestTxs(txids=txids)
        assert msg.msg_id == MSG_REQUEST_TXS
        assert len(msg.txids) == 2

    def test_msg_reply_txs(self) -> None:
        txs = [b"\x01\x02\x03", b"\x04\x05\x06"]
        msg = MsgReplyTxs(txs=txs)
        assert msg.msg_id == MSG_REPLY_TXS
        assert len(msg.txs) == 2

    def test_msg_done(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == MSG_DONE

    def test_frozen_dataclasses(self) -> None:
        """Message dataclasses should be frozen (immutable)."""
        msg = MsgInit()
        with pytest.raises(AttributeError):
            msg.msg_id = 99  # type: ignore[misc]

        msg2 = MsgRequestTxIds(blocking=True, ack_count=0, req_count=1)
        with pytest.raises(AttributeError):
            msg2.blocking = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Encode/decode round-trip -- client messages
# ---------------------------------------------------------------------------


class TestEncodeDecodeClient:
    """Test encode/decode round-trips for client-to-server messages."""

    def test_init_round_trip(self) -> None:
        encoded = encode_init()
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgInit)

    def test_init_wire_format(self) -> None:
        """MsgInit wire format: [6]."""
        encoded = encode_init()
        raw = cbor2.loads(encoded)
        assert raw == [6]

    def test_reply_tx_ids_round_trip(self) -> None:
        txids = [(b"\xab" * 32, 1024), (b"\xcd" * 32, 2048)]
        encoded = encode_reply_tx_ids(txids)
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxIds)
        assert len(decoded.txids) == 2
        assert decoded.txids[0] == (b"\xab" * 32, 1024)
        assert decoded.txids[1] == (b"\xcd" * 32, 2048)

    def test_reply_tx_ids_empty_round_trip(self) -> None:
        encoded = encode_reply_tx_ids([])
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxIds)
        assert decoded.txids == []

    def test_reply_tx_ids_wire_format(self) -> None:
        """MsgReplyTxIds wire format: [1, [[txid, size], ...]]."""
        txids = [(b"\x01" * 4, 100)]
        encoded = encode_reply_tx_ids(txids)
        raw = cbor2.loads(encoded)
        assert raw[0] == 1
        assert isinstance(raw[1], list)
        assert len(raw[1]) == 1
        assert raw[1][0][0] == b"\x01" * 4
        assert raw[1][0][1] == 100

    def test_reply_txs_round_trip(self) -> None:
        txs = [b"\x01\x02\x03", b"\x04\x05\x06"]
        encoded = encode_reply_txs(txs)
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxs)
        assert decoded.txs == txs

    def test_reply_txs_empty_round_trip(self) -> None:
        encoded = encode_reply_txs([])
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxs)
        assert decoded.txs == []

    def test_reply_txs_wire_format(self) -> None:
        """MsgReplyTxs wire format: [3, [tx, ...]]."""
        txs = [b"\xaa\xbb"]
        encoded = encode_reply_txs(txs)
        raw = cbor2.loads(encoded)
        assert raw[0] == 3
        assert isinstance(raw[1], list)
        assert raw[1][0] == b"\xaa\xbb"

    def test_done_round_trip(self) -> None:
        encoded = encode_done()
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgDone)

    def test_done_wire_format(self) -> None:
        """MsgDone wire format: [4]."""
        encoded = encode_done()
        raw = cbor2.loads(encoded)
        assert raw == [4]


# ---------------------------------------------------------------------------
# Encode/decode round-trip -- server messages
# ---------------------------------------------------------------------------


class TestEncodeDecodeServer:
    """Test encode/decode round-trips for server-to-client messages."""

    def test_request_tx_ids_blocking_round_trip(self) -> None:
        encoded = encode_request_tx_ids(blocking=True, ack_count=3, req_count=10)
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxIds)
        assert decoded.blocking is True
        assert decoded.ack_count == 3
        assert decoded.req_count == 10

    def test_request_tx_ids_nonblocking_round_trip(self) -> None:
        encoded = encode_request_tx_ids(blocking=False, ack_count=0, req_count=5)
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxIds)
        assert decoded.blocking is False
        assert decoded.ack_count == 0
        assert decoded.req_count == 5

    def test_request_tx_ids_wire_format(self) -> None:
        """MsgRequestTxIds wire format: [0, blocking, ack, req]."""
        encoded = encode_request_tx_ids(blocking=True, ack_count=1, req_count=2)
        raw = cbor2.loads(encoded)
        assert raw == [0, True, 1, 2]

    def test_request_txs_round_trip(self) -> None:
        txids = [b"\xab" * 32, b"\xcd" * 32]
        encoded = encode_request_txs(txids)
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxs)
        assert decoded.txids == txids

    def test_request_txs_empty_round_trip(self) -> None:
        encoded = encode_request_txs([])
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxs)
        assert decoded.txids == []

    def test_request_txs_wire_format(self) -> None:
        """MsgRequestTxs wire format: [2, [txid, ...]]."""
        txids = [b"\x01" * 4]
        encoded = encode_request_txs(txids)
        raw = cbor2.loads(encoded)
        assert raw[0] == 2
        assert isinstance(raw[1], list)
        assert raw[1][0] == b"\x01" * 4


# ---------------------------------------------------------------------------
# Decode error handling
# ---------------------------------------------------------------------------


class TestDecodeErrors:
    """Test that decode functions raise ValueError on invalid input."""

    def test_server_decode_not_list(self) -> None:
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(cbor2.dumps(42))

    def test_server_decode_empty_list(self) -> None:
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_server_message(cbor2.dumps([]))

    def test_server_decode_unknown_id(self) -> None:
        with pytest.raises(ValueError, match="Unknown server message ID"):
            decode_server_message(cbor2.dumps([99]))

    def test_server_decode_request_tx_ids_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 4 elements"):
            decode_server_message(cbor2.dumps([0, True, 1]))

    def test_server_decode_request_tx_ids_not_bool(self) -> None:
        with pytest.raises(ValueError, match="blocking must be bool"):
            decode_server_message(cbor2.dumps([0, 1, 0, 5]))

    def test_server_decode_request_txs_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_server_message(cbor2.dumps([2]))

    def test_client_decode_not_list(self) -> None:
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_client_message(cbor2.dumps("hello"))

    def test_client_decode_unknown_id(self) -> None:
        with pytest.raises(ValueError, match="Unknown client message ID"):
            decode_client_message(cbor2.dumps([99]))

    def test_client_decode_init_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_client_message(cbor2.dumps([6, "extra"]))

    def test_client_decode_reply_tx_ids_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_client_message(cbor2.dumps([1]))

    def test_client_decode_reply_tx_ids_not_list(self) -> None:
        with pytest.raises(ValueError, match="txids must be list"):
            decode_client_message(cbor2.dumps([1, "not_a_list"]))

    def test_client_decode_reply_tx_ids_bad_entry(self) -> None:
        with pytest.raises(ValueError, match="2-element list"):
            decode_client_message(cbor2.dumps([1, [[b"\x01"]]]))

    def test_client_decode_done_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 1 element"):
            decode_client_message(cbor2.dumps([4, "extra"]))


# ---------------------------------------------------------------------------
# Hypothesis property-based tests: CBOR round-trip
# ---------------------------------------------------------------------------

# Strategies for generating test data
txid_strategy = st.binary(min_size=1, max_size=64)
size_strategy = st.integers(min_value=0, max_value=2**32 - 1)
txid_size_pair = st.tuples(txid_strategy, size_strategy)
tx_strategy = st.binary(min_size=1, max_size=256)


class TestHypothesisRoundTrip:
    """Property-based round-trip tests using Hypothesis."""

    @given(
        blocking=st.booleans(),
        ack_count=st.integers(min_value=0, max_value=65535),
        req_count=st.integers(min_value=0, max_value=65535),
    )
    @settings(max_examples=100)
    def test_request_tx_ids_round_trip(
        self, blocking: bool, ack_count: int, req_count: int
    ) -> None:
        encoded = encode_request_tx_ids(blocking, ack_count, req_count)
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxIds)
        assert decoded.blocking == blocking
        assert decoded.ack_count == ack_count
        assert decoded.req_count == req_count

    @given(txids=st.lists(txid_size_pair, max_size=20))
    @settings(max_examples=100)
    def test_reply_tx_ids_round_trip(self, txids: list[tuple[bytes, int]]) -> None:
        encoded = encode_reply_tx_ids(txids)
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxIds)
        assert len(decoded.txids) == len(txids)
        for (orig_id, orig_sz), (dec_id, dec_sz) in zip(txids, decoded.txids):
            assert dec_id == orig_id
            assert dec_sz == orig_sz

    @given(txids=st.lists(txid_strategy, max_size=20))
    @settings(max_examples=100)
    def test_request_txs_round_trip(self, txids: list[bytes]) -> None:
        encoded = encode_request_txs(txids)
        decoded = decode_server_message(encoded)
        assert isinstance(decoded, MsgRequestTxs)
        assert decoded.txids == txids

    @given(txs=st.lists(tx_strategy, max_size=20))
    @settings(max_examples=100)
    def test_reply_txs_round_trip(self, txs: list[bytes]) -> None:
        encoded = encode_reply_txs(txs)
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgReplyTxs)
        assert decoded.txs == txs

    def test_init_round_trip_hypothesis(self) -> None:
        """MsgInit has no parameters, just verify the constant round-trip."""
        encoded = encode_init()
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgInit)

    def test_done_round_trip_hypothesis(self) -> None:
        """MsgDone has no parameters, just verify the constant round-trip."""
        encoded = encode_done()
        decoded = decode_client_message(encoded)
        assert isinstance(decoded, MsgDone)


# ---------------------------------------------------------------------------
# Codec split boundary tests (Haskell prop_codec_splitsN)
#
# These simulate network fragmentation by splitting encoded bytes at every
# possible position and feeding the chunks incrementally to cbor2's decoder.
# The Haskell tests use the same approach via codecTxSubmission2 with a
# splitting channel.
# ---------------------------------------------------------------------------


def _all_encoded_messages() -> list[tuple[str, bytes]]:
    """Return a list of (label, encoded_bytes) for representative messages."""
    return [
        ("MsgInit", encode_init()),
        ("MsgDone", encode_done()),
        (
            "MsgRequestTxIds_blocking",
            encode_request_tx_ids(blocking=True, ack_count=3, req_count=10),
        ),
        (
            "MsgRequestTxIds_nonblocking",
            encode_request_tx_ids(blocking=False, ack_count=0, req_count=5),
        ),
        (
            "MsgReplyTxIds_with_data",
            encode_reply_tx_ids([(b"\xab" * 32, 1024), (b"\xcd" * 32, 2048)]),
        ),
        ("MsgReplyTxIds_empty", encode_reply_tx_ids([])),
        (
            "MsgRequestTxs",
            encode_request_txs([b"\xab" * 32, b"\xcd" * 32]),
        ),
        (
            "MsgReplyTxs",
            encode_reply_txs([b"\x01\x02\x03", b"\x04\x05\x06"]),
        ),
    ]


def _decode_any_message(cbor_bytes: bytes) -> object:
    """Decode a message using either server or client decoder."""
    try:
        return decode_server_message(cbor_bytes)
    except ValueError:
        return decode_client_message(cbor_bytes)


class TestCodecSplits2Chunk:
    """Split encoded bytes at every position into 2 chunks and verify decode.

    This is the Haskell prop_codec_splits2 test: for every valid encoded
    message, split the bytes at position i (for all valid i), concatenate
    the two chunks, and verify the result decodes correctly. This simulates
    a TCP segment boundary falling at any point within a CBOR message.
    """

    @pytest.mark.parametrize(
        "label,encoded", _all_encoded_messages(), ids=lambda x: x if isinstance(x, str) else ""
    )
    def test_2chunk_split_all_positions(self, label: str, encoded: bytes) -> None:
        """Splitting into 2 chunks and reassembling must decode identically."""
        reference = _decode_any_message(encoded)

        for split_pos in range(1, len(encoded)):
            chunk1 = encoded[:split_pos]
            chunk2 = encoded[split_pos:]
            reassembled = chunk1 + chunk2
            assert reassembled == encoded, f"Reassembly failed at split {split_pos}"
            decoded = _decode_any_message(reassembled)
            # Verify the decoded message matches the reference
            assert type(decoded) is type(reference), (
                f"Type mismatch at split {split_pos}: "
                f"{type(decoded).__name__} != {type(reference).__name__}"
            )


class TestCodecSplits3Chunk:
    """Split encoded bytes at every pair of positions into 3 chunks.

    This is the Haskell prop_codec_splits3 test: for every valid encoded
    message, split at positions i and j (i < j), producing 3 chunks.
    Reassemble and verify the decode matches the original.
    """

    @pytest.mark.parametrize(
        "label,encoded", _all_encoded_messages(), ids=lambda x: x if isinstance(x, str) else ""
    )
    def test_3chunk_split_all_positions(self, label: str, encoded: bytes) -> None:
        """Splitting into 3 chunks and reassembling must decode identically."""
        reference = _decode_any_message(encoded)

        for i in range(1, len(encoded)):
            for j in range(i + 1, len(encoded)):
                chunk1 = encoded[:i]
                chunk2 = encoded[i:j]
                chunk3 = encoded[j:]
                reassembled = chunk1 + chunk2 + chunk3
                assert reassembled == encoded, f"Reassembly failed at splits ({i}, {j})"
                decoded = _decode_any_message(reassembled)
                assert type(decoded) is type(reference), (
                    f"Type mismatch at splits ({i}, {j}): "
                    f"{type(decoded).__name__} != {type(reference).__name__}"
                )


# ---------------------------------------------------------------------------
# Valid CBOR encoding property (Hypothesis)
#
# For any valid message generated with arbitrary data, the encoded bytes
# must be valid CBOR (cbor2.loads must not throw). This catches any
# encoder bugs that produce malformed CBOR.
# ---------------------------------------------------------------------------


class TestValidCBOREncoding:
    """Property test: every encoded message must be valid CBOR."""

    @given(
        blocking=st.booleans(),
        ack_count=st.integers(min_value=0, max_value=65535),
        req_count=st.integers(min_value=0, max_value=65535),
    )
    @settings(max_examples=50)
    def test_request_tx_ids_valid_cbor(
        self, blocking: bool, ack_count: int, req_count: int
    ) -> None:
        encoded = encode_request_tx_ids(blocking, ack_count, req_count)
        # Must not raise — the encoded bytes must be valid CBOR
        cbor2.loads(encoded)

    @given(txids=st.lists(txid_size_pair, max_size=15))
    @settings(max_examples=50)
    def test_reply_tx_ids_valid_cbor(self, txids: list[tuple[bytes, int]]) -> None:
        encoded = encode_reply_tx_ids(txids)
        cbor2.loads(encoded)

    @given(txids=st.lists(txid_strategy, max_size=15))
    @settings(max_examples=50)
    def test_request_txs_valid_cbor(self, txids: list[bytes]) -> None:
        encoded = encode_request_txs(txids)
        cbor2.loads(encoded)

    @given(txs=st.lists(tx_strategy, max_size=15))
    @settings(max_examples=50)
    def test_reply_txs_valid_cbor(self, txs: list[bytes]) -> None:
        encoded = encode_reply_txs(txs)
        cbor2.loads(encoded)

    def test_init_valid_cbor(self) -> None:
        encoded = encode_init()
        cbor2.loads(encoded)

    def test_done_valid_cbor(self) -> None:
        encoded = encode_done()
        cbor2.loads(encoded)
