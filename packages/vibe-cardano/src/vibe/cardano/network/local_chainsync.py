"""Local Chain-Sync (N2C) miniprotocol CBOR message codec.

Implements encode/decode for the node-to-client chain-sync miniprotocol
(N2C protocol ID 5). The wire format is identical to N2N chain-sync
(same message IDs, same CBOR array structure), with one critical difference:

    **MsgRollForward carries a full serialised block, not just a header.**

This is the fundamental distinction between N2N and N2C chain-sync:
- N2N: MsgRollForward [2, header, tip]  — header is a wrapped block header
- N2C: MsgRollForward [2, block, tip]   — block is a full serialised block

We reuse the message ID constants, Point/Tip types, and point/tip encoding
from the N2N chainsync module. The encode/decode functions here are thin
wrappers that make the N2C semantics explicit in the type system.

Wire format summary (CBOR arrays — same IDs as N2N):

    MsgRequestNext       [0]
    MsgAwaitReply        [1]
    MsgRollForward       [2, block, tip]    <- block, not header
    MsgRollBackward      [3, point, tip]
    MsgFindIntersect     [4, [point, ...]]
    MsgIntersectFound    [5, point, tip]
    MsgIntersectNotFound [6, tip]
    MsgDone              [7]

Spec reference: ouroboros-network, Network.Protocol.ChainSync.Codec
    The same codec (codecChainSync) is used for both N2N and N2C.
    The type parameter determines whether the payload is a header or block.
Haskell source: ouroboros-network/ouroboros-network-protocols/src/
                Ouroboros/Network/Protocol/ChainSync/Codec.hs
"""

from __future__ import annotations

import dataclasses
from typing import Union

import cbor2pure as cbor2

from vibe.cardano.network.chainsync import (
    CHAIN_SYNC_N2C_ID,
    # Message ID constants — same for N2N and N2C
    MSG_AWAIT_REPLY,
    MSG_INTERSECT_FOUND,
    MSG_INTERSECT_NOT_FOUND,
    MSG_ROLL_BACKWARD,
    MSG_ROLL_FORWARD,
    MsgAwaitReply,
    MsgDone,
    MsgFindIntersect,
    # Client messages — identical between N2N and N2C
    MsgRequestNext,
    # Domain types — shared between N2N and N2C
    Tip,
    # Point/tip encoding helpers — wire format is identical
    _decode_point,
    _decode_tip,
    _encode_tip,
    # Decode for client messages — identical
    decode_client_message,
    encode_await_reply,
    encode_done,
    encode_find_intersect,
    encode_intersect_found,
    encode_intersect_not_found,
    # Encode functions for messages that are identical
    encode_request_next,
    encode_roll_backward,
)

__all__ = [
    "N2CMsgRollForward",
    "N2CServerMessage",
    "encode_n2c_roll_forward",
    "decode_n2c_server_message",
    # Re-exports from N2N for convenience
    "MsgRequestNext",
    "MsgAwaitReply",
    "MsgFindIntersect",
    "MsgDone",
    "MsgRollBackward",
    "MsgIntersectFound",
    "MsgIntersectNotFound",
    "encode_request_next",
    "encode_find_intersect",
    "encode_done",
    "encode_await_reply",
    "encode_roll_backward",
    "encode_intersect_found",
    "encode_intersect_not_found",
    "decode_client_message",
    "CHAIN_SYNC_N2C_ID",
]


# ---------------------------------------------------------------------------
# N2C-specific message: MsgRollForward carries a full block
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class N2CMsgRollForward:
    """Server -> Client: extend the chain with this block (N2C).

    Unlike the N2N variant (which carries a block header), the N2C local
    chain-sync MsgRollForward carries the **full serialised block**.

    Attributes
    ----------
    block : bytes
        CBOR-encoded full block bytes. For N2C chain-sync this is the
        complete era-tagged block. Kept as opaque bytes at the codec
        layer; higher layers decode as needed.
    tip : Tip
        The producer's current chain tip.
    """

    block: bytes
    tip: Tip
    msg_id: int = dataclasses.field(default=MSG_ROLL_FORWARD, init=False)


# Re-import MsgRollBackward, MsgIntersectFound, MsgIntersectNotFound
# from N2N — these are identical for N2C.
from vibe.cardano.network.chainsync import (  # noqa: E402
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgRollBackward,
)

#: Union of all N2C server-to-client message types.
N2CServerMessage = Union[
    MsgAwaitReply,
    N2CMsgRollForward,
    MsgRollBackward,
    MsgIntersectFound,
    MsgIntersectNotFound,
]


# ---------------------------------------------------------------------------
# N2C-specific encode — MsgRollForward with full block
# ---------------------------------------------------------------------------


def encode_n2c_roll_forward(block: bytes, tip: Tip) -> bytes:
    """Encode N2C MsgRollForward: ``[2, block, tip]``.

    The block is the full serialised block (not just a header).
    Wire format is identical to N2N — the difference is semantic:
    the second element is a full block rather than a header.
    """
    return cbor2.dumps([MSG_ROLL_FORWARD, block, _encode_tip(tip)])


# ---------------------------------------------------------------------------
# N2C-specific decode — server-to-client messages
# ---------------------------------------------------------------------------


def decode_n2c_server_message(cbor_bytes: bytes) -> N2CServerMessage:
    """Decode a N2C server-to-client chain-sync message from CBOR bytes.

    The only difference from the N2N decoder is that MsgRollForward
    produces an N2CMsgRollForward (with ``block`` attribute) instead
    of a MsgRollForward (with ``header`` attribute).

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload (one complete message).

    Returns
    -------
    N2CServerMessage
        One of: MsgAwaitReply, N2CMsgRollForward, MsgRollBackward,
        MsgIntersectFound, MsgIntersectNotFound.

    Raises
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
        block = msg[1]
        if isinstance(block, memoryview):
            block = bytes(block)
        tip = _decode_tip(msg[2])
        return N2CMsgRollForward(block=block, tip=tip)

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
        raise ValueError(f"Unknown N2C server message ID: {msg_id}")
