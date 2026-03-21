"""N2C codec split boundary tests for local miniprotocols.

Tests that CBOR-encoded messages survive 2-chunk and 3-chunk byte splits.
This follows the Haskell codec test pattern from ouroboros-network:
encode a message, split the bytes at every possible position, reassemble,
and verify decode produces the original message.

These tests cover the four local (node-to-client) miniprotocols:
- Local chain-sync (protocol ID 5) — reuses the same codec as N2N chain-sync
- Local tx-submission (protocol ID 6) — reuses the tx-submission codec
- Local state-query and local tx-monitor — not yet implemented; placeholder
  tests verify the codec split infrastructure is ready

The chain-sync and tx-submission codecs are shared between N2N and N2C.
The wire format is identical; only the miniprotocol ID and multiplexer
framing differ. So codec split tests here validate N2C correctness too.

Haskell reference:
    Ouroboros.Network.Protocol.ChainSync.Codec (prop_codec_splits_ChainSync)
    Ouroboros.Network.Protocol.LocalTxSubmission.Codec (prop_codec_splits)
    Ouroboros.Network.Protocol.LocalStateQuery.Codec (prop_codec_splits)
    Ouroboros.Network.Protocol.LocalTxMonitor.Codec (prop_codec_splits)
"""

from __future__ import annotations

import os

import cbor2
import pytest

from vibe.cardano.network.chainsync import (
    ORIGIN,
    MsgRollForward,
    MsgRollBackward,
    MsgRequestNext,
    MsgFindIntersect,
    MsgDone as CsMsgDone,
    MsgIntersectFound,
    MsgIntersectNotFound,
    Point,
    Tip,
    decode_server_message as cs_decode_server,
    decode_client_message as cs_decode_client,
    encode_roll_forward,
    encode_roll_backward,
    encode_request_next,
    encode_find_intersect,
    encode_done as cs_encode_done,
    encode_intersect_found,
    encode_intersect_not_found,
)
from vibe.cardano.network.txsubmission import (
    MsgInit,
    MsgRequestTxIds,
    MsgReplyTxIds,
    MsgRequestTxs,
    MsgReplyTxs,
    MsgDone as TxMsgDone,
    decode_server_message as tx_decode_server,
    decode_client_message as tx_decode_client,
    encode_init,
    encode_request_tx_ids,
    encode_reply_tx_ids,
    encode_request_txs,
    encode_reply_txs,
    encode_done as tx_encode_done,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_2chunk_splits(data: bytes) -> list[tuple[bytes, bytes]]:
    """Generate all 2-chunk splits of data (N-1 split points)."""
    return [(data[:i], data[i:]) for i in range(1, len(data))]


def _all_3chunk_splits(data: bytes) -> list[tuple[bytes, bytes, bytes]]:
    """Generate all 3-chunk splits of data (all pairs 1 <= i < j < N)."""
    n = len(data)
    return [
        (data[:i], data[i:j], data[j:])
        for i in range(1, n)
        for j in range(i + 1, n)
    ]


def _make_tip() -> Tip:
    """Create a test Tip with a realistic block hash."""
    block_hash = bytes(range(32))
    return Tip(point=Point(slot=42000, hash=block_hash), block_number=1234)


def _make_header() -> bytes:
    """Create a test block header payload (opaque bytes for the codec)."""
    # In real Cardano, headers are era-tagged CBOR. For codec split
    # testing, any bytes work — the codec treats the header as opaque.
    return os.urandom(200)


# ---------------------------------------------------------------------------
# Test 8: Local chain-sync — 2-chunk split for MsgRollForward
# ---------------------------------------------------------------------------


class TestLocalChainSync2ChunkSplit:
    """2-chunk codec splits for local chain-sync messages.

    MsgRollForward with a block payload is the most interesting case
    because it's the largest message (carries the full header).
    """

    def test_roll_forward_2chunk(self) -> None:
        """MsgRollForward survives all 2-chunk splits."""
        header = _make_header()
        tip = _make_tip()
        encoded = encode_roll_forward(header, tip)

        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            reassembled = chunk1 + chunk2
            assert reassembled == encoded
            msg = cs_decode_server(reassembled)
            assert isinstance(msg, MsgRollForward)
            assert msg.header == header
            assert msg.tip.block_number == tip.block_number

    def test_roll_backward_2chunk(self) -> None:
        """MsgRollBackward survives all 2-chunk splits."""
        point = Point(slot=100, hash=bytes(range(32)))
        tip = _make_tip()
        encoded = encode_roll_backward(point, tip)

        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = cs_decode_server(chunk1 + chunk2)
            assert isinstance(msg, MsgRollBackward)
            assert isinstance(msg.point, Point)
            assert msg.point.slot == 100

    def test_request_next_2chunk(self) -> None:
        """MsgRequestNext survives all 2-chunk splits."""
        encoded = encode_request_next()
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = cs_decode_client(chunk1 + chunk2)
            assert isinstance(msg, MsgRequestNext)

    def test_find_intersect_2chunk(self) -> None:
        """MsgFindIntersect survives all 2-chunk splits."""
        points = [
            Point(slot=100, hash=bytes(range(32))),
            Point(slot=50, hash=bytes(range(32, 64))),
            ORIGIN,
        ]
        encoded = encode_find_intersect(points)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = cs_decode_client(chunk1 + chunk2)
            assert isinstance(msg, MsgFindIntersect)
            assert len(msg.points) == 3

    def test_intersect_found_2chunk(self) -> None:
        """MsgIntersectFound survives all 2-chunk splits."""
        point = Point(slot=100, hash=bytes(range(32)))
        tip = _make_tip()
        encoded = encode_intersect_found(point, tip)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = cs_decode_server(chunk1 + chunk2)
            assert isinstance(msg, MsgIntersectFound)

    def test_intersect_not_found_2chunk(self) -> None:
        """MsgIntersectNotFound survives all 2-chunk splits."""
        tip = _make_tip()
        encoded = encode_intersect_not_found(tip)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = cs_decode_server(chunk1 + chunk2)
            assert isinstance(msg, MsgIntersectNotFound)


# ---------------------------------------------------------------------------
# Test 9: Local chain-sync — 3-chunk split
# ---------------------------------------------------------------------------


class TestLocalChainSync3ChunkSplit:
    """3-chunk codec splits for local chain-sync messages."""

    def test_roll_forward_3chunk(self) -> None:
        """MsgRollForward survives all 3-chunk splits.

        For a large header, the number of 3-chunk splits is O(N^2),
        so we use a smaller header to keep test time reasonable.
        """
        header = os.urandom(32)  # Smaller header for 3-chunk
        tip = _make_tip()
        encoded = encode_roll_forward(header, tip)

        for c1, c2, c3 in _all_3chunk_splits(encoded):
            reassembled = c1 + c2 + c3
            assert reassembled == encoded
            msg = cs_decode_server(reassembled)
            assert isinstance(msg, MsgRollForward)
            assert msg.header == header

    def test_roll_backward_3chunk(self) -> None:
        """MsgRollBackward survives all 3-chunk splits."""
        point = Point(slot=200, hash=bytes(range(32)))
        tip = _make_tip()
        encoded = encode_roll_backward(point, tip)

        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = cs_decode_server(c1 + c2 + c3)
            assert isinstance(msg, MsgRollBackward)

    def test_find_intersect_3chunk(self) -> None:
        """MsgFindIntersect with multiple points survives 3-chunk splits."""
        points = [
            Point(slot=100, hash=bytes(range(32))),
            ORIGIN,
        ]
        encoded = encode_find_intersect(points)
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = cs_decode_client(c1 + c2 + c3)
            assert isinstance(msg, MsgFindIntersect)
            assert len(msg.points) == 2

    def test_intersect_found_3chunk(self) -> None:
        """MsgIntersectFound survives all 3-chunk splits."""
        point = Point(slot=500, hash=bytes(range(32)))
        tip = _make_tip()
        encoded = encode_intersect_found(point, tip)
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = cs_decode_server(c1 + c2 + c3)
            assert isinstance(msg, MsgIntersectFound)


# ---------------------------------------------------------------------------
# Test 10: Local tx-submission — 2-chunk split for MsgSubmitTx
# ---------------------------------------------------------------------------


class TestLocalTxSubmission2ChunkSplit:
    """2-chunk codec splits for local tx-submission messages.

    The local tx-submission miniprotocol (N2C) reuses the same CBOR
    message format as the N2N tx-submission (TxSubmission2) protocol.
    """

    def test_reply_tx_ids_2chunk(self) -> None:
        """MsgReplyTxIds survives all 2-chunk splits."""
        txids = [
            (os.urandom(32), 256),
            (os.urandom(32), 512),
        ]
        encoded = encode_reply_tx_ids(txids)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_client(chunk1 + chunk2)
            assert isinstance(msg, MsgReplyTxIds)
            assert len(msg.txids) == 2

    def test_reply_txs_2chunk(self) -> None:
        """MsgReplyTxs survives all 2-chunk splits."""
        txs = [os.urandom(100), os.urandom(200)]
        encoded = encode_reply_txs(txs)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_client(chunk1 + chunk2)
            assert isinstance(msg, MsgReplyTxs)
            assert len(msg.txs) == 2

    def test_init_2chunk(self) -> None:
        """MsgInit survives all 2-chunk splits."""
        encoded = encode_init()
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_client(chunk1 + chunk2)
            assert isinstance(msg, MsgInit)

    def test_request_tx_ids_2chunk(self) -> None:
        """MsgRequestTxIds survives all 2-chunk splits."""
        encoded = encode_request_tx_ids(blocking=True, ack_count=5, req_count=10)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_server(chunk1 + chunk2)
            assert isinstance(msg, MsgRequestTxIds)
            assert msg.blocking is True
            assert msg.ack_count == 5
            assert msg.req_count == 10

    def test_request_txs_2chunk(self) -> None:
        """MsgRequestTxs survives all 2-chunk splits."""
        txids = [os.urandom(32) for _ in range(3)]
        encoded = encode_request_txs(txids)
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_server(chunk1 + chunk2)
            assert isinstance(msg, MsgRequestTxs)
            assert len(msg.txids) == 3

    def test_done_2chunk(self) -> None:
        """MsgDone survives all 2-chunk splits."""
        encoded = tx_encode_done()
        for chunk1, chunk2 in _all_2chunk_splits(encoded):
            msg = tx_decode_client(chunk1 + chunk2)
            assert isinstance(msg, TxMsgDone)


# ---------------------------------------------------------------------------
# Test 11: Local tx-submission — 3-chunk split
# ---------------------------------------------------------------------------


class TestLocalTxSubmission3ChunkSplit:
    """3-chunk codec splits for local tx-submission messages."""

    def test_reply_tx_ids_3chunk(self) -> None:
        """MsgReplyTxIds survives all 3-chunk splits."""
        txids = [(os.urandom(32), 128)]
        encoded = encode_reply_tx_ids(txids)
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = tx_decode_client(c1 + c2 + c3)
            assert isinstance(msg, MsgReplyTxIds)
            assert len(msg.txids) == 1

    def test_reply_txs_3chunk(self) -> None:
        """MsgReplyTxs survives all 3-chunk splits."""
        txs = [os.urandom(50)]
        encoded = encode_reply_txs(txs)
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = tx_decode_client(c1 + c2 + c3)
            assert isinstance(msg, MsgReplyTxs)
            assert len(msg.txs) == 1

    def test_request_tx_ids_3chunk(self) -> None:
        """MsgRequestTxIds survives all 3-chunk splits."""
        encoded = encode_request_tx_ids(
            blocking=False, ack_count=0, req_count=5
        )
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = tx_decode_server(c1 + c2 + c3)
            assert isinstance(msg, MsgRequestTxIds)
            assert msg.blocking is False

    def test_request_txs_3chunk(self) -> None:
        """MsgRequestTxs survives all 3-chunk splits."""
        txids = [os.urandom(32)]
        encoded = encode_request_txs(txids)
        for c1, c2, c3 in _all_3chunk_splits(encoded):
            msg = tx_decode_server(c1 + c2 + c3)
            assert isinstance(msg, MsgRequestTxs)
            assert len(msg.txids) == 1


# ---------------------------------------------------------------------------
# Tests 12-13: Local state-query codec splits (placeholder)
# ---------------------------------------------------------------------------


class TestLocalStateQuery2ChunkSplit:
    """2-chunk codec splits for local state-query messages.

    The local state-query miniprotocol is not yet implemented.
    These tests verify the codec split infrastructure works and
    serve as a placeholder for when the implementation lands.
    """

    def test_placeholder_query_2chunk(self) -> None:
        """Placeholder: simulate a state-query MsgQuery + MsgResult pair.

        State-query wire format (from the Haskell codec):
            MsgAcquire   [0, point]
            MsgAcquired  [1]
            MsgFailure   [2, failure]
            MsgQuery     [3, query]
            MsgResult    [4, result]
            MsgRelease   [5]
            MsgReAcquire [6, point]
            MsgDone      [7]

        We encode synthetic CBOR and verify split/reassemble.
        """
        # Simulate MsgQuery [3, <query-payload>]
        query_payload = cbor2.dumps({"epoch": 400})
        msg_query = cbor2.dumps([3, query_payload])

        for chunk1, chunk2 in _all_2chunk_splits(msg_query):
            reassembled = chunk1 + chunk2
            assert reassembled == msg_query
            decoded = cbor2.loads(reassembled)
            assert decoded[0] == 3

        # Simulate MsgResult [4, <result-payload>]
        result_payload = cbor2.dumps({"delegations": [], "rewards": {}})
        msg_result = cbor2.dumps([4, result_payload])

        for chunk1, chunk2 in _all_2chunk_splits(msg_result):
            reassembled = chunk1 + chunk2
            assert reassembled == msg_result
            decoded = cbor2.loads(reassembled)
            assert decoded[0] == 4


class TestLocalStateQuery3ChunkSplit:
    """3-chunk codec splits for local state-query messages."""

    def test_placeholder_query_3chunk(self) -> None:
        """Placeholder: MsgQuery survives 3-chunk splits."""
        query_payload = cbor2.dumps({"utxo_by_address": b"\xaa" * 28})
        msg_query = cbor2.dumps([3, query_payload])

        for c1, c2, c3 in _all_3chunk_splits(msg_query):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded[0] == 3

    def test_placeholder_result_3chunk(self) -> None:
        """Placeholder: MsgResult survives 3-chunk splits."""
        result_payload = cbor2.dumps([1, 2, 3, os.urandom(32)])
        msg_result = cbor2.dumps([4, result_payload])

        for c1, c2, c3 in _all_3chunk_splits(msg_result):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded[0] == 4


# ---------------------------------------------------------------------------
# Tests 14-15: Local tx-monitor codec splits (placeholder)
# ---------------------------------------------------------------------------


class TestLocalTxMonitor2ChunkSplit:
    """2-chunk codec splits for local tx-monitor messages.

    Local tx-monitor wire format (from the Haskell codec):
        MsgAcquire        [0]
        MsgAcquired       [1, slot]
        MsgRelease        [2]
        MsgNextTx         [3]
        MsgReplyNextTx    [4, Nothing] or [4, Just tx]
        MsgHasTx          [5, txid]
        MsgReplyHasTx     [6, bool]
        MsgGetSizes       [7]
        MsgReplyGetSizes  [8, ...]
    """

    def test_reply_next_tx_nothing_2chunk(self) -> None:
        """MsgReplyNextTx with Nothing survives all 2-chunk splits.

        Wire: [4, null] (no transaction in the mempool)
        """
        msg = cbor2.dumps([4, None])
        for chunk1, chunk2 in _all_2chunk_splits(msg):
            decoded = cbor2.loads(chunk1 + chunk2)
            assert decoded == [4, None]

    def test_reply_next_tx_just_2chunk(self) -> None:
        """MsgReplyNextTx with a transaction survives all 2-chunk splits.

        Wire: [4, tx_bytes]
        """
        tx_bytes = os.urandom(150)
        msg = cbor2.dumps([4, tx_bytes])
        for chunk1, chunk2 in _all_2chunk_splits(msg):
            decoded = cbor2.loads(chunk1 + chunk2)
            assert decoded[0] == 4
            assert decoded[1] == tx_bytes

    def test_acquire_2chunk(self) -> None:
        """MsgAcquire survives all 2-chunk splits."""
        msg = cbor2.dumps([0])
        for chunk1, chunk2 in _all_2chunk_splits(msg):
            decoded = cbor2.loads(chunk1 + chunk2)
            assert decoded == [0]

    def test_acquired_2chunk(self) -> None:
        """MsgAcquired with slot number survives all 2-chunk splits."""
        msg = cbor2.dumps([1, 42000])
        for chunk1, chunk2 in _all_2chunk_splits(msg):
            decoded = cbor2.loads(chunk1 + chunk2)
            assert decoded == [1, 42000]

    def test_reply_has_tx_2chunk(self) -> None:
        """MsgReplyHasTx survives all 2-chunk splits."""
        msg = cbor2.dumps([6, True])
        for chunk1, chunk2 in _all_2chunk_splits(msg):
            decoded = cbor2.loads(chunk1 + chunk2)
            assert decoded == [6, True]


class TestLocalTxMonitor3ChunkSplit:
    """3-chunk codec splits for local tx-monitor messages."""

    def test_reply_next_tx_nothing_3chunk(self) -> None:
        """MsgReplyNextTx Nothing survives all 3-chunk splits."""
        msg = cbor2.dumps([4, None])
        for c1, c2, c3 in _all_3chunk_splits(msg):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded == [4, None]

    def test_reply_next_tx_just_3chunk(self) -> None:
        """MsgReplyNextTx with tx survives all 3-chunk splits.

        Use a small tx to keep the O(N^2) 3-chunk enumeration fast.
        """
        tx_bytes = os.urandom(20)
        msg = cbor2.dumps([4, tx_bytes])
        for c1, c2, c3 in _all_3chunk_splits(msg):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded[0] == 4
            assert decoded[1] == tx_bytes

    def test_acquired_3chunk(self) -> None:
        """MsgAcquired survives all 3-chunk splits."""
        msg = cbor2.dumps([1, 99999])
        for c1, c2, c3 in _all_3chunk_splits(msg):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded == [1, 99999]

    def test_reply_has_tx_3chunk(self) -> None:
        """MsgReplyHasTx survives all 3-chunk splits."""
        msg = cbor2.dumps([6, False])
        for c1, c2, c3 in _all_3chunk_splits(msg):
            decoded = cbor2.loads(c1 + c2 + c3)
            assert decoded == [6, False]
