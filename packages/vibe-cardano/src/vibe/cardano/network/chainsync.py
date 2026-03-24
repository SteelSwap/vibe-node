"""Chain-Sync miniprotocol CBOR message codec.

Implements encode/decode for the chain-sync miniprotocol (N2N protocol ID 2,
N2C protocol ID 5).  The on-wire format follows the Haskell reference
implementation in ouroboros-network ``codecChainSync``.

Wire format summary (CBOR arrays):

    MsgRequestNext       [0]
    MsgAwaitReply        [1]
    MsgRollForward       [2, header, tip]
    MsgRollBackward      [3, point, tip]
    MsgFindIntersect     [4, [point, ...]]
    MsgIntersectFound    [5, point, tip]
    MsgIntersectNotFound [6, tip]
    MsgDone              [7]

Point encoding (from ``encodePoint`` / ``decodePoint`` in ouroboros-network):
    Origin      -> CBOR list of length 0  (``[]``)
    BlockPoint  -> CBOR list of length 2  (``[slot, hash]``)

Tip encoding (from ``encodeTip`` / ``decodeTip``):
    CBOR list of length 2: ``[point, block_number]``
    When tip is genesis, point is Origin and block_number is 0.

Spec reference: ouroboros-network, Network.Protocol.ChainSync.Codec
Haskell source: ouroboros-network/ouroboros-network-protocols/src/
                Ouroboros/Network/Protocol/ChainSync/Codec.hs
"""

from __future__ import annotations

import dataclasses
from typing import Union

import cbor2pure as cbor2

# ---------------------------------------------------------------------------
# Message ID constants — index 0 of the CBOR array
# ---------------------------------------------------------------------------

MSG_REQUEST_NEXT: int = 0
MSG_AWAIT_REPLY: int = 1
MSG_ROLL_FORWARD: int = 2
MSG_ROLL_BACKWARD: int = 3
MSG_FIND_INTERSECT: int = 4
MSG_INTERSECT_FOUND: int = 5
MSG_INTERSECT_NOT_FOUND: int = 6
MSG_DONE: int = 7

# Miniprotocol numbers
CHAIN_SYNC_N2N_ID: int = 2
CHAIN_SYNC_N2C_ID: int = 5


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class Origin:
    """Sentinel for the genesis point (origin of the chain).

    On the wire this is encoded as an empty CBOR list ``[]``.
    In the Haskell implementation this corresponds to ``GenesisPoint``.
    """

    _instance: Origin | None = None

    def __new__(cls) -> Origin:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "Origin"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Origin)

    def __hash__(self) -> int:
        return hash("Origin")


#: Module-level singleton so callers can use ``ORIGIN`` directly.
ORIGIN = Origin()


@dataclasses.dataclass(frozen=True, slots=True)
class Point:
    """A point on the chain identified by slot number and block header hash.

    For the genesis/origin point, use :data:`ORIGIN` instead.

    Attributes:
    ----------
    slot : int
        Absolute slot number.
    hash : bytes
        32-byte block header hash.
    """

    slot: int
    hash: bytes

    def __repr__(self) -> str:
        return f"Point(slot={self.slot}, hash={self.hash.hex()[:16]}...)"


#: A chain point is either a concrete ``Point`` or ``Origin``.
PointOrOrigin = Union[Point, Origin]


@dataclasses.dataclass(frozen=True, slots=True)
class Tip:
    """The tip of the producer's chain.

    Attributes:
    ----------
    point : PointOrOrigin
        The point at the tip (or Origin for genesis tip).
    block_number : int
        Block number at the tip.  For genesis tip this is 0, matching
        the Haskell encoding where ``fromWithOrigin (BlockNo 0)`` is used.
    """

    point: PointOrOrigin
    block_number: int


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRequestNext:
    """Client -> Server: request the next chain update."""

    msg_id: int = dataclasses.field(default=MSG_REQUEST_NEXT, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgAwaitReply:
    """Server -> Client: consumer is caught up, wait for new data."""

    msg_id: int = dataclasses.field(default=MSG_AWAIT_REPLY, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRollForward:
    """Server -> Client: extend the chain with this header.

    Attributes:
    ----------
    header : bytes
        CBOR-encoded block header bytes.  For N2N chain-sync this is
        a wrapped header (era-tagged).  We keep it as opaque bytes at
        the codec layer; higher layers decode the header.
    tip : Tip
        The producer's current chain tip.
    """

    header: bytes
    tip: Tip
    msg_id: int = dataclasses.field(default=MSG_ROLL_FORWARD, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRollBackward:
    """Server -> Client: roll back to this point.

    Attributes:
    ----------
    point : PointOrOrigin
        The point to roll back to (or Origin).
    tip : Tip
        The producer's current chain tip.
    """

    point: PointOrOrigin
    tip: Tip
    msg_id: int = dataclasses.field(default=MSG_ROLL_BACKWARD, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgFindIntersect:
    """Client -> Server: find the best intersection from these points.

    Attributes:
    ----------
    points : list[PointOrOrigin]
        Candidate points, ordered by preference (highest slot first).
    """

    points: list[PointOrOrigin]
    msg_id: int = dataclasses.field(default=MSG_FIND_INTERSECT, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgIntersectFound:
    """Server -> Client: intersection found at this point.

    Attributes:
    ----------
    point : PointOrOrigin
        The intersection point.
    tip : Tip
        The producer's current chain tip.
    """

    point: PointOrOrigin
    tip: Tip
    msg_id: int = dataclasses.field(default=MSG_INTERSECT_FOUND, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgIntersectNotFound:
    """Server -> Client: no intersection found.

    Attributes:
    ----------
    tip : Tip
        The producer's current chain tip.
    """

    tip: Tip
    msg_id: int = dataclasses.field(default=MSG_INTERSECT_NOT_FOUND, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: protocol termination."""

    msg_id: int = dataclasses.field(default=MSG_DONE, init=False)


#: Union of all server-to-client message types.
ServerMessage = Union[
    MsgAwaitReply,
    MsgRollForward,
    MsgRollBackward,
    MsgIntersectFound,
    MsgIntersectNotFound,
]


# ---------------------------------------------------------------------------
# Point / Tip CBOR helpers
# ---------------------------------------------------------------------------


def _encode_point(point: PointOrOrigin) -> list:
    """Encode a point to a CBOR-friendly list.

    Origin  -> []
    Point   -> [slot, hash]

    Matches Haskell ``encodePoint``.
    """
    if isinstance(point, Origin):
        return []
    return [point.slot, point.hash]


def _decode_point(raw: list) -> PointOrOrigin:
    """Decode a CBOR list to a Point or Origin.

    Matches Haskell ``decodePoint``: list length 0 = Origin,
    list length 2 = BlockPoint(slot, hash).
    """
    if len(raw) == 0:
        return ORIGIN
    if len(raw) == 2:
        slot, hash_bytes = raw
        if isinstance(hash_bytes, memoryview):
            hash_bytes = bytes(hash_bytes)
        return Point(slot=slot, hash=hash_bytes)
    raise ValueError(f"Invalid point encoding: list length {len(raw)}")


def _encode_tip(tip: Tip) -> list:
    """Encode a Tip to a CBOR-friendly list: [point, block_number].

    Matches Haskell ``encodeTip``.
    """
    return [_encode_point(tip.point), tip.block_number]


def _decode_tip(raw: list) -> Tip:
    """Decode a CBOR list [point, block_number] to a Tip.

    Matches Haskell ``decodeTip``.
    """
    if len(raw) != 2:
        raise ValueError(f"Invalid tip encoding: list length {len(raw)}")
    point = _decode_point(raw[0])
    block_number = raw[1]
    return Tip(point=point, block_number=block_number)


# ---------------------------------------------------------------------------
# Encode — client messages
# ---------------------------------------------------------------------------


def encode_request_next() -> bytes:
    """Encode MsgRequestNext: ``[0]``.

    Returns CBOR bytes ready for the multiplexer.
    """
    return cbor2.dumps([MSG_REQUEST_NEXT])


def encode_find_intersect(points: list[PointOrOrigin]) -> bytes:
    """Encode MsgFindIntersect: ``[4, [point, ...]]``.

    Parameters
    ----------
    points : list[PointOrOrigin]
        Candidate intersection points, ordered by preference.

    Returns CBOR bytes ready for the multiplexer.
    """
    encoded_points = [_encode_point(p) for p in points]
    return cbor2.dumps([MSG_FIND_INTERSECT, encoded_points])


def encode_done() -> bytes:
    """Encode MsgDone: ``[7]``.

    Returns CBOR bytes ready for the multiplexer.
    """
    return cbor2.dumps([MSG_DONE])


# ---------------------------------------------------------------------------
# Encode — server messages (useful for testing and future server role)
# ---------------------------------------------------------------------------


def encode_await_reply() -> bytes:
    """Encode MsgAwaitReply: ``[1]``."""
    return cbor2.dumps([MSG_AWAIT_REPLY])


def encode_roll_forward(header: bytes, tip: Tip) -> bytes:
    """Encode MsgRollForward: ``[2, header, tip]``.

    The header is passed through as raw CBOR-tagged bytes.
    """
    return cbor2.dumps([MSG_ROLL_FORWARD, header, _encode_tip(tip)])


def encode_roll_backward(point: PointOrOrigin, tip: Tip) -> bytes:
    """Encode MsgRollBackward: ``[3, point, tip]``."""
    return cbor2.dumps([MSG_ROLL_BACKWARD, _encode_point(point), _encode_tip(tip)])


def encode_intersect_found(point: PointOrOrigin, tip: Tip) -> bytes:
    """Encode MsgIntersectFound: ``[5, point, tip]``."""
    return cbor2.dumps([MSG_INTERSECT_FOUND, _encode_point(point), _encode_tip(tip)])


def encode_intersect_not_found(tip: Tip) -> bytes:
    """Encode MsgIntersectNotFound: ``[6, tip]``."""
    return cbor2.dumps([MSG_INTERSECT_NOT_FOUND, _encode_tip(tip)])


# ---------------------------------------------------------------------------
# Decode — server-to-client messages
# ---------------------------------------------------------------------------


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client chain-sync message from CBOR bytes.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload (one complete message).

    Returns:
    -------
    ServerMessage
        One of: MsgAwaitReply, MsgRollForward, MsgRollBackward,
        MsgIntersectFound, MsgIntersectNotFound.

    Raises:
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_AWAIT_REPLY:
        if len(msg) != 1:
            raise ValueError(f"MsgAwaitReply: expected 1 element, got {len(msg)}")
        return MsgAwaitReply()

    elif msg_id == MSG_ROLL_FORWARD:
        if len(msg) != 3:
            raise ValueError(f"MsgRollForward: expected 3 elements, got {len(msg)}")
        header = msg[1]
        if isinstance(header, memoryview):
            header = bytes(header)
        tip = _decode_tip(msg[2])
        return MsgRollForward(header=header, tip=tip)

    elif msg_id == MSG_ROLL_BACKWARD:
        if len(msg) != 3:
            raise ValueError(f"MsgRollBackward: expected 3 elements, got {len(msg)}")
        point = _decode_point(msg[1])
        tip = _decode_tip(msg[2])
        return MsgRollBackward(point=point, tip=tip)

    elif msg_id == MSG_INTERSECT_FOUND:
        if len(msg) != 3:
            raise ValueError(f"MsgIntersectFound: expected 3 elements, got {len(msg)}")
        point = _decode_point(msg[1])
        tip = _decode_tip(msg[2])
        return MsgIntersectFound(point=point, tip=tip)

    elif msg_id == MSG_INTERSECT_NOT_FOUND:
        if len(msg) != 2:
            raise ValueError(f"MsgIntersectNotFound: expected 2 elements, got {len(msg)}")
        tip = _decode_tip(msg[1])
        return MsgIntersectNotFound(tip=tip)

    else:
        raise ValueError(f"Unknown server message ID: {msg_id}")


# ---------------------------------------------------------------------------
# Decode — client-to-server messages (for future server role)
# ---------------------------------------------------------------------------


#: Union of all client-to-server message types.
ClientMessage = Union[MsgRequestNext, MsgFindIntersect, MsgDone]


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server chain-sync message from CBOR bytes.

    Returns:
    -------
    ClientMessage
        One of: MsgRequestNext, MsgFindIntersect, MsgDone.

    Raises:
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_REQUEST_NEXT:
        if len(msg) != 1:
            raise ValueError(f"MsgRequestNext: expected 1 element, got {len(msg)}")
        return MsgRequestNext()

    elif msg_id == MSG_FIND_INTERSECT:
        if len(msg) != 2:
            raise ValueError(f"MsgFindIntersect: expected 2 elements, got {len(msg)}")
        points = [_decode_point(p) for p in msg[1]]
        return MsgFindIntersect(points=points)

    elif msg_id == MSG_DONE:
        if len(msg) != 1:
            raise ValueError(f"MsgDone: expected 1 element, got {len(msg)}")
        return MsgDone()

    else:
        raise ValueError(f"Unknown client message ID: {msg_id}")
