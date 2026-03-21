"""Tests for local state-query miniprotocol — messages, codec, FSM, and server.

Tests cover:
- Message construction and field access
- CBOR encoding produces expected wire format
- CBOR decoding recovers the original message
- Round-trip property: decode(encode(msg)) == msg for all message types
- Typed message wrappers with correct state transitions
- Protocol state machine: agency, valid messages per state
- FSM: acquire -> query -> result -> release flow
- Server: UTxO by address returns correct results
- Server: protocol params returns current params
- Server: epoch info returns correct epoch/slot
- Failed acquisition (point not on chain)
- Multiple queries in one session
- Re-acquire to different point
- Hypothesis property tests for round-trip encoding
"""

from __future__ import annotations

import asyncio
from fractions import Fraction
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.local_statequery import (
    LOCAL_STATE_QUERY_PROTOCOL_ID,
    AcquireFailureReason,
    MsgAcquire,
    MsgAcquired,
    MsgDone,
    MsgFailure,
    MsgQuery,
    MsgReAcquire,
    MsgRelease,
    MsgResult,
    Point,
    Query,
    QueryType,
    decode_client_message,
    decode_message,
    decode_server_message,
    encode_acquire,
    encode_acquired,
    encode_done,
    encode_failure,
    encode_query,
    encode_reacquire,
    encode_release,
    encode_result,
)
from vibe.cardano.network.local_statequery_protocol import (
    LocalStateQueryCodec,
    LocalStateQueryProtocol,
    LocalStateQueryServer,
    LocalStateQueryState,
    LsqMsgAcquire,
    LsqMsgAcquired,
    LsqMsgDone,
    LsqMsgFailure,
    LsqMsgQuery,
    LsqMsgReAcquire,
    LsqMsgRelease,
    LsqMsgResult,
)
from vibe.core.protocols import Agency, Message, ProtocolError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify protocol constants match the spec."""

    def test_protocol_id(self) -> None:
        assert LOCAL_STATE_QUERY_PROTOCOL_ID == 7


# ---------------------------------------------------------------------------
# Point dataclass
# ---------------------------------------------------------------------------


class TestPoint:
    """Test Point construction and serialization."""

    def test_construction(self) -> None:
        p = Point(slot=42, block_hash=b"\x00" * 32)
        assert p.slot == 42
        assert p.block_hash == b"\x00" * 32

    def test_to_cbor_list(self) -> None:
        p = Point(slot=100, block_hash=b"\xab" * 32)
        result = p.to_cbor_list()
        assert result == [100, b"\xab" * 32]

    def test_from_cbor_list(self) -> None:
        data = [100, b"\xab" * 32]
        p = Point.from_cbor_list(data)
        assert p.slot == 100
        assert p.block_hash == b"\xab" * 32

    def test_from_cbor_list_wrong_length(self) -> None:
        with pytest.raises(ValueError, match="expected 2 elements"):
            Point.from_cbor_list([100])

    def test_round_trip(self) -> None:
        original = Point(slot=500, block_hash=b"\xff" * 32)
        restored = Point.from_cbor_list(original.to_cbor_list())
        assert restored == original


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMessageConstruction:
    """Message dataclass construction and fields."""

    def test_msg_acquire_with_point(self) -> None:
        p = Point(slot=42, block_hash=b"\x00" * 32)
        msg = MsgAcquire(point=p)
        assert msg.point == p
        assert msg.msg_id == 0

    def test_msg_acquire_origin(self) -> None:
        msg = MsgAcquire(point=None)
        assert msg.point is None

    def test_msg_failure(self) -> None:
        msg = MsgFailure(reason=AcquireFailureReason.AcquireFailurePointNotOnChain)
        assert msg.reason == AcquireFailureReason.AcquireFailurePointNotOnChain
        assert msg.msg_id == 1

    def test_msg_acquired(self) -> None:
        msg = MsgAcquired()
        assert msg.msg_id == 2

    def test_msg_query(self) -> None:
        q = Query(QueryType.ProtocolParameters)
        msg = MsgQuery(query=q)
        assert msg.query.query_type == QueryType.ProtocolParameters
        assert msg.msg_id == 3

    def test_msg_result(self) -> None:
        msg = MsgResult(result={"key": "value"})
        assert msg.result == {"key": "value"}
        assert msg.msg_id == 4

    def test_msg_release(self) -> None:
        msg = MsgRelease()
        assert msg.msg_id == 5

    def test_msg_reacquire(self) -> None:
        p = Point(slot=99, block_hash=b"\x01" * 32)
        msg = MsgReAcquire(point=p)
        assert msg.point == p
        assert msg.msg_id == 6

    def test_msg_done(self) -> None:
        msg = MsgDone()
        assert msg.msg_id == 7


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


class TestEncoding:
    """CBOR encoding produces the correct wire format."""

    def test_encode_acquire_with_point(self) -> None:
        p = Point(slot=42, block_hash=b"\x00" * 32)
        encoded = encode_acquire(p)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 0
        assert decoded[1] == [42, b"\x00" * 32]

    def test_encode_acquire_origin(self) -> None:
        encoded = encode_acquire(None)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 0
        assert decoded[1] == []

    def test_encode_failure_not_on_chain(self) -> None:
        encoded = encode_failure(AcquireFailureReason.AcquireFailurePointNotOnChain)
        decoded = cbor2.loads(encoded)
        assert decoded == [1, 1]

    def test_encode_failure_too_old(self) -> None:
        encoded = encode_failure(AcquireFailureReason.AcquireFailurePointTooOld)
        decoded = cbor2.loads(encoded)
        assert decoded == [1, 0]

    def test_encode_acquired(self) -> None:
        encoded = encode_acquired()
        decoded = cbor2.loads(encoded)
        assert decoded == [2]

    def test_encode_query_protocol_params(self) -> None:
        q = Query(QueryType.ProtocolParameters)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 3
        # [0, era_index, [4]]
        assert decoded[1][0] == 0  # wrapper tag
        assert decoded[1][2] == [4]  # protocol params query tag

    def test_encode_query_epoch_info(self) -> None:
        q = Query(QueryType.EpochInfo)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 3
        assert decoded[1][2] == [7]

    def test_encode_query_utxo_by_address(self) -> None:
        addrs = [b"\xaa" * 28]
        q = Query(QueryType.UTxOByAddress, params=addrs)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 3
        assert decoded[1][2][0] == 2
        assert decoded[1][2][1] == addrs

    def test_encode_query_utxo_by_txin(self) -> None:
        txins = [b"\xbb" * 34]
        q = Query(QueryType.UTxOByTxIn, params=txins)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 3
        assert decoded[1][2][0] == 5
        assert decoded[1][2][1] == txins

    def test_encode_query_stake_distribution(self) -> None:
        q = Query(QueryType.StakeDistribution)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[1][2] == [6]

    def test_encode_query_governance_state(self) -> None:
        q = Query(QueryType.GovernanceState)
        encoded = encode_query(q)
        decoded = cbor2.loads(encoded)
        assert decoded[1][2] == [10]

    def test_encode_result(self) -> None:
        encoded = encode_result([100, 50, 431950])
        decoded = cbor2.loads(encoded)
        assert decoded == [4, [100, 50, 431950]]

    def test_encode_release(self) -> None:
        encoded = encode_release()
        decoded = cbor2.loads(encoded)
        assert decoded == [5]

    def test_encode_reacquire(self) -> None:
        p = Point(slot=99, block_hash=b"\x01" * 32)
        encoded = encode_reacquire(p)
        decoded = cbor2.loads(encoded)
        assert decoded[0] == 6
        assert decoded[1] == [99, b"\x01" * 32]

    def test_encode_done(self) -> None:
        encoded = encode_done()
        decoded = cbor2.loads(encoded)
        assert decoded == [7]


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


class TestDecoding:
    """CBOR decoding recovers the original message."""

    def test_decode_acquire(self) -> None:
        cbor_bytes = cbor2.dumps([0, [42, b"\x00" * 32]])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgAcquire)
        assert msg.point is not None
        assert msg.point.slot == 42

    def test_decode_acquire_origin(self) -> None:
        cbor_bytes = cbor2.dumps([0, []])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgAcquire)
        assert msg.point is None

    def test_decode_failure(self) -> None:
        cbor_bytes = cbor2.dumps([1, 1])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgFailure)
        assert msg.reason == AcquireFailureReason.AcquireFailurePointNotOnChain

    def test_decode_acquired(self) -> None:
        cbor_bytes = cbor2.dumps([2])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgAcquired)

    def test_decode_query(self) -> None:
        cbor_bytes = cbor2.dumps([3, [0, 5, [4]]])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgQuery)
        assert msg.query.query_type == QueryType.ProtocolParameters

    def test_decode_result(self) -> None:
        cbor_bytes = cbor2.dumps([4, {"foo": "bar"}])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgResult)
        assert msg.result == {"foo": "bar"}

    def test_decode_release(self) -> None:
        cbor_bytes = cbor2.dumps([5])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgRelease)

    def test_decode_reacquire(self) -> None:
        cbor_bytes = cbor2.dumps([6, [99, b"\x01" * 32]])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgReAcquire)
        assert msg.point is not None
        assert msg.point.slot == 99

    def test_decode_done(self) -> None:
        cbor_bytes = cbor2.dumps([7])
        msg = decode_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_unknown_message_id(self) -> None:
        cbor_bytes = cbor2.dumps([99])
        with pytest.raises(ValueError, match="Unknown local state-query message ID"):
            decode_message(cbor_bytes)

    def test_decode_not_a_list(self) -> None:
        cbor_bytes = cbor2.dumps(42)
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_empty_list(self) -> None:
        cbor_bytes = cbor2.dumps([])
        with pytest.raises(ValueError, match="Expected CBOR list"):
            decode_message(cbor_bytes)

    def test_decode_acquire_wrong_length(self) -> None:
        cbor_bytes = cbor2.dumps([0])
        with pytest.raises(ValueError, match="expected 2 elements"):
            decode_message(cbor_bytes)

    def test_decode_failure_unknown_reason(self) -> None:
        cbor_bytes = cbor2.dumps([1, 99])
        with pytest.raises(ValueError, match="unknown reason"):
            decode_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Typed decode helpers
# ---------------------------------------------------------------------------


class TestTypedDecode:
    """decode_server_message and decode_client_message."""

    def test_decode_server_acquired(self) -> None:
        cbor_bytes = encode_acquired()
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgAcquired)

    def test_decode_server_failure(self) -> None:
        cbor_bytes = encode_failure(AcquireFailureReason.AcquireFailurePointTooOld)
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgFailure)

    def test_decode_server_result(self) -> None:
        cbor_bytes = encode_result(42)
        msg = decode_server_message(cbor_bytes)
        assert isinstance(msg, MsgResult)

    def test_decode_server_rejects_client_msg(self) -> None:
        cbor_bytes = encode_acquire(None)
        with pytest.raises(ValueError, match="Expected server message"):
            decode_server_message(cbor_bytes)

    def test_decode_client_acquire(self) -> None:
        cbor_bytes = encode_acquire(None)
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgAcquire)

    def test_decode_client_done(self) -> None:
        cbor_bytes = encode_done()
        msg = decode_client_message(cbor_bytes)
        assert isinstance(msg, MsgDone)

    def test_decode_client_rejects_server_msg(self) -> None:
        cbor_bytes = encode_acquired()
        with pytest.raises(ValueError, match="Expected client message"):
            decode_client_message(cbor_bytes)


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Encode then decode recovers the original message."""

    def test_acquire_round_trip(self) -> None:
        p = Point(slot=42, block_hash=b"\xab" * 32)
        encoded = encode_acquire(p)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgAcquire)
        assert decoded.point is not None
        assert decoded.point.slot == 42
        assert decoded.point.block_hash == b"\xab" * 32

    def test_acquire_origin_round_trip(self) -> None:
        encoded = encode_acquire(None)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgAcquire)
        assert decoded.point is None

    def test_failure_round_trip(self) -> None:
        for reason in AcquireFailureReason:
            encoded = encode_failure(reason)
            decoded = decode_message(encoded)
            assert isinstance(decoded, MsgFailure)
            assert decoded.reason == reason

    def test_acquired_round_trip(self) -> None:
        encoded = encode_acquired()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgAcquired)

    def test_query_round_trip_protocol_params(self) -> None:
        q = Query(QueryType.ProtocolParameters, era_index=5)
        encoded = encode_query(q)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgQuery)
        assert decoded.query.query_type == QueryType.ProtocolParameters
        assert decoded.query.era_index == 5

    def test_query_round_trip_epoch_info(self) -> None:
        q = Query(QueryType.EpochInfo)
        encoded = encode_query(q)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgQuery)
        assert decoded.query.query_type == QueryType.EpochInfo

    def test_result_round_trip(self) -> None:
        data = [100, 50, 431950]
        encoded = encode_result(data)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgResult)
        assert decoded.result == data

    def test_release_round_trip(self) -> None:
        encoded = encode_release()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgRelease)

    def test_reacquire_round_trip(self) -> None:
        p = Point(slot=99, block_hash=b"\x01" * 32)
        encoded = encode_reacquire(p)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgReAcquire)
        assert decoded.point is not None
        assert decoded.point.slot == 99

    def test_done_round_trip(self) -> None:
        encoded = encode_done()
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgDone)


# ---------------------------------------------------------------------------
# Protocol state machine tests
# ---------------------------------------------------------------------------


class TestLocalStateQueryProtocol:
    """Verify the protocol state machine definition."""

    def setup_method(self) -> None:
        self.protocol = LocalStateQueryProtocol()

    def test_initial_state(self) -> None:
        assert self.protocol.initial_state() == LocalStateQueryState.StIdle

    def test_agency_idle(self) -> None:
        assert self.protocol.agency(LocalStateQueryState.StIdle) == Agency.Client

    def test_agency_acquiring(self) -> None:
        assert self.protocol.agency(LocalStateQueryState.StAcquiring) == Agency.Server

    def test_agency_acquired(self) -> None:
        assert self.protocol.agency(LocalStateQueryState.StAcquired) == Agency.Client

    def test_agency_querying(self) -> None:
        assert self.protocol.agency(LocalStateQueryState.StQuerying) == Agency.Server

    def test_agency_done(self) -> None:
        assert self.protocol.agency(LocalStateQueryState.StDone) == Agency.Nobody

    def test_valid_messages_idle(self) -> None:
        msgs = self.protocol.valid_messages(LocalStateQueryState.StIdle)
        assert LsqMsgAcquire in msgs
        assert LsqMsgDone in msgs
        assert len(msgs) == 2

    def test_valid_messages_acquiring(self) -> None:
        msgs = self.protocol.valid_messages(LocalStateQueryState.StAcquiring)
        assert LsqMsgAcquired in msgs
        assert LsqMsgFailure in msgs
        assert len(msgs) == 2

    def test_valid_messages_acquired(self) -> None:
        msgs = self.protocol.valid_messages(LocalStateQueryState.StAcquired)
        assert LsqMsgQuery in msgs
        assert LsqMsgReAcquire in msgs
        assert LsqMsgRelease in msgs
        assert len(msgs) == 3

    def test_valid_messages_querying(self) -> None:
        msgs = self.protocol.valid_messages(LocalStateQueryState.StQuerying)
        assert LsqMsgResult in msgs
        assert len(msgs) == 1

    def test_valid_messages_done(self) -> None:
        msgs = self.protocol.valid_messages(LocalStateQueryState.StDone)
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# Typed message wrapper tests
# ---------------------------------------------------------------------------


class TestTypedMessages:
    """Verify typed message wrappers carry correct state transitions."""

    def test_lsq_msg_acquire(self) -> None:
        p = Point(slot=42, block_hash=b"\x00" * 32)
        msg = LsqMsgAcquire(point=p)
        assert msg.from_state == LocalStateQueryState.StIdle
        assert msg.to_state == LocalStateQueryState.StAcquiring
        assert msg.point == p

    def test_lsq_msg_acquired(self) -> None:
        msg = LsqMsgAcquired()
        assert msg.from_state == LocalStateQueryState.StAcquiring
        assert msg.to_state == LocalStateQueryState.StAcquired

    def test_lsq_msg_failure(self) -> None:
        msg = LsqMsgFailure(AcquireFailureReason.AcquireFailurePointNotOnChain)
        assert msg.from_state == LocalStateQueryState.StAcquiring
        assert msg.to_state == LocalStateQueryState.StIdle
        assert msg.reason == AcquireFailureReason.AcquireFailurePointNotOnChain

    def test_lsq_msg_query(self) -> None:
        q = Query(QueryType.ProtocolParameters)
        msg = LsqMsgQuery(query=q)
        assert msg.from_state == LocalStateQueryState.StAcquired
        assert msg.to_state == LocalStateQueryState.StQuerying
        assert msg.query.query_type == QueryType.ProtocolParameters

    def test_lsq_msg_result(self) -> None:
        msg = LsqMsgResult(result=42)
        assert msg.from_state == LocalStateQueryState.StQuerying
        assert msg.to_state == LocalStateQueryState.StAcquired
        assert msg.result == 42

    def test_lsq_msg_release(self) -> None:
        msg = LsqMsgRelease()
        assert msg.from_state == LocalStateQueryState.StAcquired
        assert msg.to_state == LocalStateQueryState.StIdle

    def test_lsq_msg_reacquire(self) -> None:
        p = Point(slot=99, block_hash=b"\x01" * 32)
        msg = LsqMsgReAcquire(point=p)
        assert msg.from_state == LocalStateQueryState.StAcquired
        assert msg.to_state == LocalStateQueryState.StAcquiring
        assert msg.point == p

    def test_lsq_msg_done(self) -> None:
        msg = LsqMsgDone()
        assert msg.from_state == LocalStateQueryState.StIdle
        assert msg.to_state == LocalStateQueryState.StDone


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


class TestLocalStateQueryCodec:
    """Verify the codec encodes and decodes correctly."""

    def setup_method(self) -> None:
        self.codec = LocalStateQueryCodec()

    def test_round_trip_acquire(self) -> None:
        p = Point(slot=42, block_hash=b"\x00" * 32)
        original = LsqMsgAcquire(point=p)
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, LsqMsgAcquire)
        assert decoded.point is not None
        assert decoded.point.slot == 42

    def test_round_trip_acquired(self) -> None:
        original = LsqMsgAcquired()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgAcquired)

    def test_round_trip_failure(self) -> None:
        original = LsqMsgFailure(AcquireFailureReason.AcquireFailurePointTooOld)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgFailure)
        assert decoded.reason == AcquireFailureReason.AcquireFailurePointTooOld

    def test_round_trip_query(self) -> None:
        q = Query(QueryType.StakeDistribution)
        original = LsqMsgQuery(query=q)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgQuery)
        assert decoded.query.query_type == QueryType.StakeDistribution

    def test_round_trip_result(self) -> None:
        original = LsqMsgResult(result=[100, 50, 431950])
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgResult)
        assert decoded.result == [100, 50, 431950]

    def test_round_trip_release(self) -> None:
        original = LsqMsgRelease()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgRelease)

    def test_round_trip_reacquire(self) -> None:
        p = Point(slot=99, block_hash=b"\x01" * 32)
        original = LsqMsgReAcquire(point=p)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgReAcquire)
        assert decoded.point is not None
        assert decoded.point.slot == 99

    def test_round_trip_done(self) -> None:
        original = LsqMsgDone()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LsqMsgDone)

    def test_decode_preserves_state_transitions(self) -> None:
        """Decoded messages have correct from_state/to_state."""
        p = Point(slot=1, block_hash=b"\x00" * 32)
        acq = LsqMsgAcquire(point=p)
        decoded = self.codec.decode(self.codec.encode(acq))
        assert decoded.from_state == LocalStateQueryState.StIdle
        assert decoded.to_state == LocalStateQueryState.StAcquiring

        acquired = LsqMsgAcquired()
        decoded = self.codec.decode(self.codec.encode(acquired))
        assert decoded.from_state == LocalStateQueryState.StAcquiring
        assert decoded.to_state == LocalStateQueryState.StAcquired

        done = LsqMsgDone()
        decoded = self.codec.decode(self.codec.encode(done))
        assert decoded.from_state == LocalStateQueryState.StIdle
        assert decoded.to_state == LocalStateQueryState.StDone


# ---------------------------------------------------------------------------
# FSM transition tests
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    """Verify the full state machine transition graph."""

    def setup_method(self) -> None:
        self.protocol = LocalStateQueryProtocol()

    def test_full_acquire_query_release_done_cycle(self) -> None:
        """Walk through: Idle -> Acquire -> Acquired -> Query -> Result -> Release -> Idle -> Done."""
        state = self.protocol.initial_state()
        assert state == LocalStateQueryState.StIdle

        # Client acquires
        p = Point(slot=42, block_hash=b"\x00" * 32)
        acq = LsqMsgAcquire(point=p)
        assert acq.from_state == state
        state = acq.to_state
        assert state == LocalStateQueryState.StAcquiring

        # Server confirms
        acquired = LsqMsgAcquired()
        assert acquired.from_state == state
        state = acquired.to_state
        assert state == LocalStateQueryState.StAcquired

        # Client queries
        q = Query(QueryType.ProtocolParameters)
        query_msg = LsqMsgQuery(query=q)
        assert query_msg.from_state == state
        state = query_msg.to_state
        assert state == LocalStateQueryState.StQuerying

        # Server responds
        result = LsqMsgResult(result={"min_fee": 155381})
        assert result.from_state == state
        state = result.to_state
        assert state == LocalStateQueryState.StAcquired

        # Client releases
        release = LsqMsgRelease()
        assert release.from_state == state
        state = release.to_state
        assert state == LocalStateQueryState.StIdle

        # Client terminates
        done = LsqMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == LocalStateQueryState.StDone
        assert self.protocol.agency(state) == Agency.Nobody

    def test_multiple_queries_in_session(self) -> None:
        """Multiple queries can be run against the same acquired state."""
        state = self.protocol.initial_state()

        # Acquire
        state = LsqMsgAcquire(point=None).to_state
        state = LsqMsgAcquired().to_state

        # First query
        state = LsqMsgQuery(query=Query(QueryType.ProtocolParameters)).to_state
        assert state == LocalStateQueryState.StQuerying
        state = LsqMsgResult(result={}).to_state
        assert state == LocalStateQueryState.StAcquired

        # Second query
        state = LsqMsgQuery(query=Query(QueryType.EpochInfo)).to_state
        assert state == LocalStateQueryState.StQuerying
        state = LsqMsgResult(result=[100, 50, 431950]).to_state
        assert state == LocalStateQueryState.StAcquired

        # Third query
        state = LsqMsgQuery(query=Query(QueryType.StakeDistribution)).to_state
        state = LsqMsgResult(result={}).to_state
        assert state == LocalStateQueryState.StAcquired

        # Release and done
        state = LsqMsgRelease().to_state
        state = LsqMsgDone().to_state
        assert state == LocalStateQueryState.StDone

    def test_acquire_failure_and_retry(self) -> None:
        """Failed acquisition returns to StIdle for retry."""
        state = self.protocol.initial_state()

        # First acquire attempt fails
        state = LsqMsgAcquire(point=Point(slot=999, block_hash=b"\xff" * 32)).to_state
        assert state == LocalStateQueryState.StAcquiring
        state = LsqMsgFailure(AcquireFailureReason.AcquireFailurePointNotOnChain).to_state
        assert state == LocalStateQueryState.StIdle

        # Second acquire attempt succeeds
        state = LsqMsgAcquire(point=None).to_state
        state = LsqMsgAcquired().to_state
        assert state == LocalStateQueryState.StAcquired

    def test_reacquire_from_acquired(self) -> None:
        """Re-acquire transitions from StAcquired -> StAcquiring."""
        state = self.protocol.initial_state()
        state = LsqMsgAcquire(point=None).to_state
        state = LsqMsgAcquired().to_state
        assert state == LocalStateQueryState.StAcquired

        # Re-acquire
        p = Point(slot=50, block_hash=b"\x02" * 32)
        state = LsqMsgReAcquire(point=p).to_state
        assert state == LocalStateQueryState.StAcquiring
        state = LsqMsgAcquired().to_state
        assert state == LocalStateQueryState.StAcquired

    def test_done_is_terminal(self) -> None:
        """StDone has no valid messages."""
        assert self.protocol.agency(LocalStateQueryState.StDone) == Agency.Nobody
        assert len(self.protocol.valid_messages(LocalStateQueryState.StDone)) == 0


# ---------------------------------------------------------------------------
# Server tests — mock LedgerDB for UTxO queries
# ---------------------------------------------------------------------------


class _MockLedgerDB:
    """Minimal mock LedgerDB for testing the server query handlers."""

    def __init__(self, utxos: dict[bytes, dict[str, Any]] | None = None) -> None:
        self._index: dict[bytes, int] = {}
        self._utxos: dict[bytes, dict[str, Any]] = utxos or {}
        for key in self._utxos:
            self._index[key] = len(self._index)

    def get_utxo(self, txin: bytes) -> dict[str, Any] | None:
        return self._utxos.get(txin)

    @property
    def utxo_count(self) -> int:
        return len(self._utxos)


def _make_connected_channels() -> tuple[MagicMock, MagicMock]:
    """Create a pair of connected mock channels for client-server pairing."""
    client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
    server_to_client: asyncio.Queue[bytes] = asyncio.Queue()

    client_channel = MagicMock()
    server_channel = MagicMock()

    async def client_send(data: bytes) -> None:
        await client_to_server.put(data)

    async def client_recv() -> bytes:
        return await server_to_client.get()

    async def server_send(data: bytes) -> None:
        await server_to_client.put(data)

    async def server_recv() -> bytes:
        return await client_to_server.get()

    client_channel.send = AsyncMock(side_effect=client_send)
    client_channel.recv = AsyncMock(side_effect=client_recv)
    server_channel.send = AsyncMock(side_effect=server_send)
    server_channel.recv = AsyncMock(side_effect=server_recv)

    return client_channel, server_channel


class TestServerUTxOByAddress:
    """Server correctly handles QueryUTxOByAddress."""

    @pytest.mark.asyncio
    async def test_utxo_by_address_returns_matching(self) -> None:
        """UTxO by address query returns entries matching the requested address."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        # Set up a ledger with some UTxOs
        key1 = b"\x01" * 34
        key2 = b"\x02" * 34
        key3 = b"\x03" * 34
        utxos = {
            key1: {"address": "addr_test1abc", "value": 5000000, "tx_hash": b"\x01" * 32, "tx_index": 0, "datum_hash": b"", "key": key1},
            key2: {"address": "addr_test1xyz", "value": 3000000, "tx_hash": b"\x02" * 32, "tx_index": 0, "datum_hash": b"", "key": key2},
            key3: {"address": "addr_test1abc", "value": 2000000, "tx_hash": b"\x03" * 32, "tx_index": 0, "datum_hash": b"", "key": key3},
        }
        ledgerdb = _MockLedgerDB(utxos)

        client_ch, server_ch = _make_connected_channels()

        # Server side
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(
            server_runner, ledgerdb,
            protocol_params={"min_fee_a": 44, "min_fee_b": 155381},
        )

        # Client side
        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        # Run server in background
        server_task = asyncio.create_task(server.run())

        # Client: acquire -> query UTxO by address -> release -> done
        await client_runner.send_message(LsqMsgAcquire(point=None))
        acquired_msg = await client_runner.recv_message()
        assert isinstance(acquired_msg, LsqMsgAcquired)

        # Query UTxO by address
        q = Query(QueryType.UTxOByAddress, params=["addr_test1abc"])
        await client_runner.send_message(LsqMsgQuery(query=q))
        result_msg = await client_runner.recv_message()
        assert isinstance(result_msg, LsqMsgResult)

        result = result_msg.result
        # Should have 2 UTxOs matching addr_test1abc
        assert len(result) == 2
        assert key1 in result
        assert key3 in result
        assert key2 not in result

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())

        await server_task


class TestServerProtocolParams:
    """Server correctly handles QueryProtocolParameters."""

    @pytest.mark.asyncio
    async def test_protocol_params_returns_current(self) -> None:
        """Protocol params query returns the configured params."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        params = {
            "min_fee_a": 44,
            "min_fee_b": 155381,
            "max_block_size": 90112,
            "max_tx_size": 16384,
            "key_deposit": 2000000,
            "pool_deposit": 500000000,
        }

        ledgerdb = _MockLedgerDB()
        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(
            server_runner, ledgerdb,
            protocol_params=params,
        )

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Acquire
        await client_runner.send_message(LsqMsgAcquire(point=None))
        await client_runner.recv_message()

        # Query protocol params
        q = Query(QueryType.ProtocolParameters)
        await client_runner.send_message(LsqMsgQuery(query=q))
        result_msg = await client_runner.recv_message()
        assert isinstance(result_msg, LsqMsgResult)
        assert result_msg.result == params

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())
        await server_task


class TestServerEpochInfo:
    """Server correctly handles QueryEpochInfo."""

    @pytest.mark.asyncio
    async def test_epoch_info_returns_correct_values(self) -> None:
        """Epoch info query returns (epoch_no, slot_in_epoch, slots_remaining)."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        ledgerdb = _MockLedgerDB()
        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(
            server_runner, ledgerdb,
            epoch_no=400,
            slot_in_epoch=50000,
            epoch_length=432000,
        )

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Acquire
        await client_runner.send_message(LsqMsgAcquire(point=None))
        await client_runner.recv_message()

        # Query epoch info
        q = Query(QueryType.EpochInfo)
        await client_runner.send_message(LsqMsgQuery(query=q))
        result_msg = await client_runner.recv_message()
        assert isinstance(result_msg, LsqMsgResult)
        assert result_msg.result == [400, 50000, 382000]

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())
        await server_task


class TestServerFailedAcquisition:
    """Server handles acquisition failure correctly."""

    @pytest.mark.asyncio
    async def test_acquire_unknown_point_fails(self) -> None:
        """Acquiring at a point not on chain returns MsgFailure."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        ledgerdb = _MockLedgerDB()
        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        # Server with a specific chain tip
        tip = Point(slot=1000, block_hash=b"\xaa" * 32)
        server = LocalStateQueryServer(
            server_runner, ledgerdb, chain_tip=tip,
        )

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Try to acquire at a point that's not the tip
        unknown_point = Point(slot=999, block_hash=b"\xff" * 32)
        await client_runner.send_message(LsqMsgAcquire(point=unknown_point))
        response = await client_runner.recv_message()
        assert isinstance(response, LsqMsgFailure)
        assert response.reason == AcquireFailureReason.AcquireFailurePointNotOnChain

        # State should be back to StIdle — we can try again or quit
        await client_runner.send_message(LsqMsgDone())
        await server_task


class TestServerMultipleQueries:
    """Server handles multiple queries in one session."""

    @pytest.mark.asyncio
    async def test_multiple_queries_same_session(self) -> None:
        """Multiple different queries against the same acquired state."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        key1 = b"\x01" * 34
        utxos = {
            key1: {
                "address": "addr_test1abc", "value": 5000000,
                "tx_hash": b"\x01" * 32, "tx_index": 0,
                "datum_hash": b"", "key": key1,
            },
        }
        ledgerdb = _MockLedgerDB(utxos)
        params = {"min_fee_a": 44, "max_tx_size": 16384}

        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(
            server_runner, ledgerdb,
            protocol_params=params,
            epoch_no=100,
            slot_in_epoch=5000,
            epoch_length=432000,
        )

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Acquire
        await client_runner.send_message(LsqMsgAcquire(point=None))
        await client_runner.recv_message()

        # Query 1: protocol params
        await client_runner.send_message(
            LsqMsgQuery(query=Query(QueryType.ProtocolParameters))
        )
        r1 = await client_runner.recv_message()
        assert isinstance(r1, LsqMsgResult)
        assert r1.result == params

        # Query 2: epoch info
        await client_runner.send_message(
            LsqMsgQuery(query=Query(QueryType.EpochInfo))
        )
        r2 = await client_runner.recv_message()
        assert isinstance(r2, LsqMsgResult)
        assert r2.result == [100, 5000, 427000]

        # Query 3: UTxO by address
        await client_runner.send_message(
            LsqMsgQuery(query=Query(QueryType.UTxOByAddress, params=["addr_test1abc"]))
        )
        r3 = await client_runner.recv_message()
        assert isinstance(r3, LsqMsgResult)
        assert len(r3.result) == 1

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())
        await server_task


class TestServerUTxOByTxIn:
    """Server correctly handles QueryUTxOByTxIn."""

    @pytest.mark.asyncio
    async def test_utxo_by_txin_returns_matching(self) -> None:
        """UTxO by TxIn query returns entries matching the requested inputs."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        key1 = b"\x01" * 34
        key2 = b"\x02" * 34
        utxos = {
            key1: {"address": "addr1", "value": 5000000, "tx_hash": b"\x01" * 32, "tx_index": 0, "datum_hash": b"", "key": key1},
            key2: {"address": "addr2", "value": 3000000, "tx_hash": b"\x02" * 32, "tx_index": 0, "datum_hash": b"", "key": key2},
        }
        ledgerdb = _MockLedgerDB(utxos)
        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(server_runner, ledgerdb)

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Acquire
        await client_runner.send_message(LsqMsgAcquire(point=None))
        await client_runner.recv_message()

        # Query UTxO by TxIn — only request key1
        q = Query(QueryType.UTxOByTxIn, params=[key1])
        await client_runner.send_message(LsqMsgQuery(query=q))
        result_msg = await client_runner.recv_message()
        assert isinstance(result_msg, LsqMsgResult)
        assert key1 in result_msg.result
        assert key2 not in result_msg.result

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())
        await server_task


class TestServerStakeDistribution:
    """Server correctly handles QueryStakeDistribution."""

    @pytest.mark.asyncio
    async def test_stake_distribution_returns_data(self) -> None:
        """Stake distribution query returns per-pool fractions."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        pool1 = b"\x01" * 28
        pool2 = b"\x02" * 28
        stake_dist = {
            pool1: Fraction(3, 10),
            pool2: Fraction(7, 10),
        }

        ledgerdb = _MockLedgerDB()
        client_ch, server_ch = _make_connected_channels()

        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=server_ch,
        )
        server = LocalStateQueryServer(
            server_runner, ledgerdb,
            stake_distribution=stake_dist,
        )

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalStateQueryProtocol(),
            codec=LocalStateQueryCodec(),
            channel=client_ch,
        )

        server_task = asyncio.create_task(server.run())

        # Acquire
        await client_runner.send_message(LsqMsgAcquire(point=None))
        await client_runner.recv_message()

        # Query stake distribution
        q = Query(QueryType.StakeDistribution)
        await client_runner.send_message(LsqMsgQuery(query=q))
        result_msg = await client_runner.recv_message()
        assert isinstance(result_msg, LsqMsgResult)
        result = result_msg.result
        assert pool1.hex() in result
        assert result[pool1.hex()] == [3, 10]
        assert pool2.hex() in result
        assert result[pool2.hex()] == [7, 10]

        # Release and done
        await client_runner.send_message(LsqMsgRelease())
        await client_runner.send_message(LsqMsgDone())
        await server_task


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


class TestHypothesis:
    """Property-based tests for CBOR round-trip encoding."""

    @given(slot=st.integers(min_value=0, max_value=2**63))
    @settings(max_examples=100)
    def test_acquire_round_trip(self, slot: int) -> None:
        """For any valid slot, acquire encode->decode is identity."""
        block_hash = b"\xab" * 32
        p = Point(slot=slot, block_hash=block_hash)
        encoded = encode_acquire(p)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgAcquire)
        assert decoded.point is not None
        assert decoded.point.slot == slot
        assert decoded.point.block_hash == block_hash

    def test_all_failure_reasons_round_trip(self) -> None:
        """All AcquireFailureReason values round-trip correctly."""
        for reason in AcquireFailureReason:
            encoded = encode_failure(reason)
            decoded = decode_message(encoded)
            assert isinstance(decoded, MsgFailure)
            assert decoded.reason == reason

    def test_all_parameterless_query_types_round_trip(self) -> None:
        """All parameterless query types round-trip correctly."""
        parameterless = [
            QueryType.LedgerTip,
            QueryType.UTxOWhole,
            QueryType.ProtocolParameters,
            QueryType.StakeDistribution,
            QueryType.EpochInfo,
            QueryType.GenesisConfig,
            QueryType.GovernanceState,
        ]
        for qt in parameterless:
            q = Query(qt)
            encoded = encode_query(q)
            decoded = decode_message(encoded)
            assert isinstance(decoded, MsgQuery)
            assert decoded.query.query_type == qt

    @given(result_val=st.integers(min_value=0, max_value=2**32))
    @settings(max_examples=100)
    def test_result_round_trip(self, result_val: int) -> None:
        """For any integer result, encode->decode is identity."""
        encoded = encode_result(result_val)
        decoded = decode_message(encoded)
        assert isinstance(decoded, MsgResult)
        assert decoded.result == result_val
