"""Local State-Query miniprotocol CBOR message types (N2C protocol ID 7).

Implements the node-to-client local state-query miniprotocol defined in
the Ouroboros network specification. This is the most complex N2C protocol:
clients can query UTxO, stake distribution, protocol parameters, epoch
info, and governance state against an acquired ledger state at a specific
chain point.

Wire format references:
    - ``codecLocalStateQuery`` in ``Ouroboros.Network.Protocol.LocalStateQuery.Codec``
    - ``LocalStateQuery`` protocol type in ``Ouroboros.Network.Protocol.LocalStateQuery.Type``

CBOR encoding:
    MsgAcquire       [0, point]
    MsgFailure       [1, reason]
    MsgAcquired      [2]
    MsgQuery         [3, query]
    MsgResult        [4, result]
    MsgRelease       [5]
    MsgReAcquire     [6, point]
    MsgDone          [7]

Query types are wrapped in CBOR arrays with their own sub-tags. The Haskell
implementation uses a nested BlockQuery wrapper for era-specific queries:
    [0, era_index, era_query]  -- Shelley/Allegra/Mary/Alonzo/Babbage/Conway

Era-specific query sub-tags (within the era query):
    [0]              -> QueryLedgerTip (not listed in task but useful)
    [1, credentials] -> QueryStakeAddresses
    [2, addresses]   -> QueryUTxOByAddress
    [3]              -> QueryUTxOWhole
    [4]              -> QueryProtocolParameters
    [5, tx_ins]      -> QueryUTxOByTxIn
    [6]              -> QueryStakeDistribution
    [7]              -> QueryEpochInfo
    [8]              -> QueryGenesisConfig
    [10]             -> QueryGovernanceState (Conway)

Spec reference:
    Ouroboros network spec, "Local State Query Mini-Protocol"
    ouroboros-network-protocols/src/Ouroboros/Network/Protocol/LocalStateQuery/
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Union

import cbor2pure as cbor2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCAL_STATE_QUERY_PROTOCOL_ID: int = 7
"""Local state-query is miniprotocol number 7 (N2C)."""

# CBOR message tags (first element of the outer list).
_MSG_ACQUIRE: int = 0
_MSG_FAILURE: int = 1
_MSG_ACQUIRED: int = 2
_MSG_QUERY: int = 3
_MSG_RESULT: int = 4
_MSG_RELEASE: int = 5
_MSG_REACQUIRE: int = 6
_MSG_DONE: int = 7

# Era-specific query sub-tags.
_QUERY_LEDGER_TIP: int = 0
_QUERY_STAKE_ADDRESSES: int = 1
_QUERY_UTXO_BY_ADDRESS: int = 2
_QUERY_UTXO_WHOLE: int = 3
_QUERY_PROTOCOL_PARAMS: int = 4
_QUERY_UTXO_BY_TXIN: int = 5
_QUERY_STAKE_DISTRIBUTION: int = 6
_QUERY_EPOCH_INFO: int = 7
_QUERY_GENESIS_CONFIG: int = 8
_QUERY_GOVERNANCE_STATE: int = 10


# ---------------------------------------------------------------------------
# Failure reasons
# ---------------------------------------------------------------------------


class AcquireFailureReason(enum.Enum):
    """Reason for acquisition failure.

    Haskell ref: AcquireFailure in
        Ouroboros.Network.Protocol.LocalStateQuery.Type
    """

    AcquireFailurePointTooOld = 0
    """The requested point has been pruned (beyond k blocks back)."""

    AcquireFailurePointNotOnChain = 1
    """The requested point is not on the current chain."""


# ---------------------------------------------------------------------------
# Query type enum
# ---------------------------------------------------------------------------


class QueryType(enum.Enum):
    """Discriminator for the type of ledger query."""

    LedgerTip = "ledger_tip"
    StakeAddresses = "stake_addresses"
    UTxOByAddress = "utxo_by_address"
    UTxOWhole = "utxo_whole"
    ProtocolParameters = "protocol_parameters"
    UTxOByTxIn = "utxo_by_txin"
    StakeDistribution = "stake_distribution"
    EpochInfo = "epoch_info"
    GenesisConfig = "genesis_config"
    GovernanceState = "governance_state"


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Point:
    """A chain point: slot number + block header hash.

    Wire format: [slot :: uint64, hash :: bytes(32)]
    Origin is represented as an empty list: []

    Haskell ref: Point in Ouroboros.Network.Block
    """

    slot: int
    block_hash: bytes

    def to_cbor_list(self) -> list:
        """Convert to CBOR-encodable list."""
        return [self.slot, self.block_hash]

    @classmethod
    def from_cbor_list(cls, data: list) -> Point:
        """Construct from a decoded CBOR list [slot, hash]."""
        if len(data) != 2:
            raise ValueError(f"Point: expected 2 elements [slot, hash], got {len(data)}")
        slot = data[0]
        block_hash = data[1]
        if isinstance(block_hash, memoryview):
            block_hash = bytes(block_hash)
        return cls(slot=slot, block_hash=block_hash)


# Sentinel for origin point.
ORIGIN: list = []


@dataclass(frozen=True, slots=True)
class Query:
    """A ledger query with its type and optional parameters.

    This is a simplified representation — the actual wire format uses
    nested CBOR arrays with era indexes.
    """

    query_type: QueryType
    params: Any = None
    era_index: int = 5
    """Era index: 0=Byron, 1=Shelley, ..., 5=Conway (default)."""


@dataclass(frozen=True, slots=True)
class MsgAcquire:
    """Client -> Server: acquire ledger state at a specific chain point.

    Wire format: ``[0, point]``
    """

    point: Point | None
    """None means origin."""
    msg_id: int = field(default=_MSG_ACQUIRE, init=False)


@dataclass(frozen=True, slots=True)
class MsgFailure:
    """Server -> Client: acquisition or re-acquisition failed.

    Wire format: ``[1, reason]``
    """

    reason: AcquireFailureReason
    msg_id: int = field(default=_MSG_FAILURE, init=False)


@dataclass(frozen=True, slots=True)
class MsgAcquired:
    """Server -> Client: acquisition succeeded.

    Wire format: ``[2]``
    """

    msg_id: int = field(default=_MSG_ACQUIRED, init=False)


@dataclass(frozen=True, slots=True)
class MsgQuery:
    """Client -> Server: submit a query against the acquired state.

    Wire format: ``[3, query]``
    """

    query: Query
    msg_id: int = field(default=_MSG_QUERY, init=False)


@dataclass(frozen=True, slots=True)
class MsgResult:
    """Server -> Client: query result.

    Wire format: ``[4, result]``

    The result type depends on the query. We store it as Any and let
    the higher-level code interpret it.
    """

    result: Any
    msg_id: int = field(default=_MSG_RESULT, init=False)


@dataclass(frozen=True, slots=True)
class MsgRelease:
    """Client -> Server: release the acquired ledger state.

    Wire format: ``[5]``
    """

    msg_id: int = field(default=_MSG_RELEASE, init=False)


@dataclass(frozen=True, slots=True)
class MsgReAcquire:
    """Client -> Server: re-acquire at a different chain point.

    Wire format: ``[6, point]``
    """

    point: Point | None
    """None means origin."""
    msg_id: int = field(default=_MSG_REACQUIRE, init=False)


@dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: terminate the protocol.

    Wire format: ``[7]``
    """

    msg_id: int = field(default=_MSG_DONE, init=False)


#: Union of all client-to-server message types.
ClientMessage = Union[MsgAcquire, MsgQuery, MsgRelease, MsgReAcquire, MsgDone]

#: Union of all server-to-client message types.
ServerMessage = Union[MsgFailure, MsgAcquired, MsgResult]

#: Union of all local state-query message types.
LocalStateQueryMessage = Union[
    MsgAcquire,
    MsgFailure,
    MsgAcquired,
    MsgQuery,
    MsgResult,
    MsgRelease,
    MsgReAcquire,
    MsgDone,
]


# ---------------------------------------------------------------------------
# Encode — helper functions
# ---------------------------------------------------------------------------


def _encode_point(point: Point | None) -> list:
    """Encode a point for the wire format."""
    if point is None:
        return ORIGIN
    return point.to_cbor_list()


def _encode_query(query: Query) -> list:
    """Encode a Query to its CBOR wire representation.

    Wire format: [0, era_index, era_query]
    where era_query varies by QueryType.
    """
    qt = query.query_type

    if qt == QueryType.LedgerTip:
        era_query = [_QUERY_LEDGER_TIP]
    elif qt == QueryType.StakeAddresses:
        era_query = [_QUERY_STAKE_ADDRESSES, query.params]
    elif qt == QueryType.UTxOByAddress:
        era_query = [_QUERY_UTXO_BY_ADDRESS, query.params]
    elif qt == QueryType.UTxOWhole:
        era_query = [_QUERY_UTXO_WHOLE]
    elif qt == QueryType.ProtocolParameters:
        era_query = [_QUERY_PROTOCOL_PARAMS]
    elif qt == QueryType.UTxOByTxIn:
        era_query = [_QUERY_UTXO_BY_TXIN, query.params]
    elif qt == QueryType.StakeDistribution:
        era_query = [_QUERY_STAKE_DISTRIBUTION]
    elif qt == QueryType.EpochInfo:
        era_query = [_QUERY_EPOCH_INFO]
    elif qt == QueryType.GenesisConfig:
        era_query = [_QUERY_GENESIS_CONFIG]
    elif qt == QueryType.GovernanceState:
        era_query = [_QUERY_GOVERNANCE_STATE]
    else:
        raise ValueError(f"Unknown query type: {qt}")

    return [0, query.era_index, era_query]


# ---------------------------------------------------------------------------
# Encode — message functions
# ---------------------------------------------------------------------------


def encode_acquire(point: Point | None) -> bytes:
    """Encode MsgAcquire: ``[0, point]``.

    Args:
        point: The chain point to acquire, or None for origin.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_ACQUIRE, _encode_point(point)])


def encode_failure(reason: AcquireFailureReason) -> bytes:
    """Encode MsgFailure: ``[1, reason]``.

    Args:
        reason: The failure reason enum value.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_FAILURE, reason.value])


def encode_acquired() -> bytes:
    """Encode MsgAcquired: ``[2]``.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_ACQUIRED])


def encode_query(query: Query) -> bytes:
    """Encode MsgQuery: ``[3, query]``.

    Args:
        query: The query to encode.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_QUERY, _encode_query(query)])


def encode_result(result: Any) -> bytes:
    """Encode MsgResult: ``[4, result]``.

    Args:
        result: The query result (CBOR-serializable).

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_RESULT, result])


def encode_release() -> bytes:
    """Encode MsgRelease: ``[5]``.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_RELEASE])


def encode_reacquire(point: Point | None) -> bytes:
    """Encode MsgReAcquire: ``[6, point]``.

    Args:
        point: The new chain point to acquire, or None for origin.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_REACQUIRE, _encode_point(point)])


def encode_done() -> bytes:
    """Encode MsgDone: ``[7]``.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_DONE])


# ---------------------------------------------------------------------------
# Decode — helper functions
# ---------------------------------------------------------------------------


def _decode_point(data: Any) -> Point | None:
    """Decode a point from CBOR data."""
    if isinstance(data, list):
        if len(data) == 0:
            return None  # origin
        return Point.from_cbor_list(data)
    raise ValueError(f"Expected list for point, got {type(data).__name__}")


def _decode_query(data: Any) -> Query:
    """Decode a Query from its CBOR wire representation.

    Expected format: [0, era_index, era_query]
    """
    if not isinstance(data, list) or len(data) < 3:
        raise ValueError(f"Query: expected [0, era_index, era_query], got {data!r}")

    wrapper_tag = data[0]
    if wrapper_tag != 0:
        raise ValueError(f"Query: expected wrapper tag 0, got {wrapper_tag}")

    era_index = data[1]
    era_query = data[2]

    if not isinstance(era_query, list) or len(era_query) < 1:
        raise ValueError(f"Query: era_query must be non-empty list, got {era_query!r}")

    query_tag = era_query[0]

    if query_tag == _QUERY_LEDGER_TIP:
        return Query(QueryType.LedgerTip, era_index=era_index)
    elif query_tag == _QUERY_STAKE_ADDRESSES:
        params = era_query[1] if len(era_query) > 1 else None
        return Query(QueryType.StakeAddresses, params=params, era_index=era_index)
    elif query_tag == _QUERY_UTXO_BY_ADDRESS:
        params = era_query[1] if len(era_query) > 1 else None
        return Query(QueryType.UTxOByAddress, params=params, era_index=era_index)
    elif query_tag == _QUERY_UTXO_WHOLE:
        return Query(QueryType.UTxOWhole, era_index=era_index)
    elif query_tag == _QUERY_PROTOCOL_PARAMS:
        return Query(QueryType.ProtocolParameters, era_index=era_index)
    elif query_tag == _QUERY_UTXO_BY_TXIN:
        params = era_query[1] if len(era_query) > 1 else None
        return Query(QueryType.UTxOByTxIn, params=params, era_index=era_index)
    elif query_tag == _QUERY_STAKE_DISTRIBUTION:
        return Query(QueryType.StakeDistribution, era_index=era_index)
    elif query_tag == _QUERY_EPOCH_INFO:
        return Query(QueryType.EpochInfo, era_index=era_index)
    elif query_tag == _QUERY_GENESIS_CONFIG:
        return Query(QueryType.GenesisConfig, era_index=era_index)
    elif query_tag == _QUERY_GOVERNANCE_STATE:
        return Query(QueryType.GovernanceState, era_index=era_index)
    else:
        raise ValueError(f"Unknown era query tag: {query_tag}")


# ---------------------------------------------------------------------------
# Decode — message functions
# ---------------------------------------------------------------------------


def decode_message(cbor_bytes: bytes) -> LocalStateQueryMessage:
    """Decode any local state-query message from CBOR bytes.

    Args:
        cbor_bytes: Raw CBOR payload (one complete message).

    Returns:
        One of the message dataclasses.

    Raises:
        ValueError: If the message ID is unknown or the payload is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == _MSG_ACQUIRE:
        if len(msg) != 2:
            raise ValueError(f"MsgAcquire: expected 2 elements, got {len(msg)}")
        point = _decode_point(msg[1])
        return MsgAcquire(point=point)

    elif msg_id == _MSG_FAILURE:
        if len(msg) != 2:
            raise ValueError(f"MsgFailure: expected 2 elements, got {len(msg)}")
        try:
            reason = AcquireFailureReason(msg[1])
        except ValueError:
            raise ValueError(f"MsgFailure: unknown reason: {msg[1]}")
        return MsgFailure(reason=reason)

    elif msg_id == _MSG_ACQUIRED:
        if len(msg) != 1:
            raise ValueError(f"MsgAcquired: expected 1 element, got {len(msg)}")
        return MsgAcquired()

    elif msg_id == _MSG_QUERY:
        if len(msg) != 2:
            raise ValueError(f"MsgQuery: expected 2 elements, got {len(msg)}")
        query = _decode_query(msg[1])
        return MsgQuery(query=query)

    elif msg_id == _MSG_RESULT:
        if len(msg) != 2:
            raise ValueError(f"MsgResult: expected 2 elements, got {len(msg)}")
        return MsgResult(result=msg[1])

    elif msg_id == _MSG_RELEASE:
        if len(msg) != 1:
            raise ValueError(f"MsgRelease: expected 1 element, got {len(msg)}")
        return MsgRelease()

    elif msg_id == _MSG_REACQUIRE:
        if len(msg) != 2:
            raise ValueError(f"MsgReAcquire: expected 2 elements, got {len(msg)}")
        point = _decode_point(msg[1])
        return MsgReAcquire(point=point)

    elif msg_id == _MSG_DONE:
        if len(msg) != 1:
            raise ValueError(f"MsgDone: expected 1 element, got {len(msg)}")
        return MsgDone()

    else:
        raise ValueError(f"Unknown local state-query message ID: {msg_id}")


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client local state-query message from CBOR bytes.

    Server messages: MsgFailure, MsgAcquired, MsgResult.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        One of: MsgFailure, MsgAcquired, MsgResult.

    Raises:
        ValueError: If the message is not a valid server message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgFailure, MsgAcquired, MsgResult)):
        raise ValueError(
            f"Expected server message (MsgFailure, MsgAcquired, or MsgResult), "
            f"got: {type(msg).__name__}"
        )
    return msg


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server local state-query message from CBOR bytes.

    Client messages: MsgAcquire, MsgQuery, MsgRelease, MsgReAcquire, MsgDone.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        One of: MsgAcquire, MsgQuery, MsgRelease, MsgReAcquire, MsgDone.

    Raises:
        ValueError: If the message is not a valid client message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgAcquire, MsgQuery, MsgRelease, MsgReAcquire, MsgDone)):
        raise ValueError(
            f"Expected client message "
            f"(MsgAcquire, MsgQuery, MsgRelease, MsgReAcquire, or MsgDone), "
            f"got: {type(msg).__name__}"
        )
    return msg
