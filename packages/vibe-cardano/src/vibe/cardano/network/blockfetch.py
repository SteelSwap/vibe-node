"""Block-Fetch miniprotocol CBOR message codec.

Implements encode/decode for the block-fetch miniprotocol (N2N protocol ID 3).
The on-wire format follows the Haskell reference implementation in
ouroboros-network ``codecBlockFetch``.

Wire format summary (CBOR arrays):

    MsgRequestRange  [0, point_from, point_to]
    MsgClientDone    [1]
    MsgStartBatch    [2]
    MsgNoBlocks      [3]
    MsgBlock         [4, block_cbor]
    MsgBatchDone     [5]

Point encoding reuses the chain-sync Point type:
    Origin      -> CBOR list of length 0  (``[]``)
    BlockPoint  -> CBOR list of length 2  (``[slot, hash]``)

Spec reference: ouroboros-network, Network.Protocol.BlockFetch.Codec
Haskell source: ouroboros-network/ouroboros-network-protocols/src/
                Ouroboros/Network/Protocol/BlockFetch/Codec.hs
"""

from __future__ import annotations

import dataclasses
from typing import Union

import cbor2

from vibe.cardano.network.chainsync import (
    Point,
    Origin,
    ORIGIN,
    PointOrOrigin,
    _encode_point,
    _decode_point,
)

# ---------------------------------------------------------------------------
# Message ID constants -- index 0 of the CBOR array
# ---------------------------------------------------------------------------

MSG_REQUEST_RANGE: int = 0
MSG_CLIENT_DONE: int = 1
MSG_START_BATCH: int = 2
MSG_NO_BLOCKS: int = 3
MSG_BLOCK: int = 4
MSG_BATCH_DONE: int = 5

# Miniprotocol number
BLOCK_FETCH_N2N_ID: int = 3


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRequestRange:
    """Client -> Server: request blocks in the given range.

    Attributes
    ----------
    point_from : PointOrOrigin
        Start of the range (inclusive).
    point_to : PointOrOrigin
        End of the range (inclusive).
    """

    point_from: PointOrOrigin
    point_to: PointOrOrigin
    msg_id: int = dataclasses.field(default=MSG_REQUEST_RANGE, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgClientDone:
    """Client -> Server: client is done, terminate the protocol."""

    msg_id: int = dataclasses.field(default=MSG_CLIENT_DONE, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgStartBatch:
    """Server -> Client: server will stream blocks for the requested range."""

    msg_id: int = dataclasses.field(default=MSG_START_BATCH, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgNoBlocks:
    """Server -> Client: server has no blocks in the requested range."""

    msg_id: int = dataclasses.field(default=MSG_NO_BLOCKS, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgBlock:
    """Server -> Client: a single block in the batch.

    Attributes
    ----------
    block_cbor : bytes
        CBOR-encoded block body bytes.  We keep it as opaque bytes at
        the codec layer; higher layers decode the block.
    """

    block_cbor: bytes
    msg_id: int = dataclasses.field(default=MSG_BLOCK, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgBatchDone:
    """Server -> Client: all blocks in the batch have been sent."""

    msg_id: int = dataclasses.field(default=MSG_BATCH_DONE, init=False)


#: Union of all server-to-client message types.
ServerMessage = Union[MsgStartBatch, MsgNoBlocks, MsgBlock, MsgBatchDone]

#: Union of all client-to-server message types.
ClientMessage = Union[MsgRequestRange, MsgClientDone]


# ---------------------------------------------------------------------------
# Encode -- client messages
# ---------------------------------------------------------------------------


def encode_request_range(point_from: PointOrOrigin, point_to: PointOrOrigin) -> bytes:
    """Encode MsgRequestRange: ``[0, point_from, point_to]``.

    Returns CBOR bytes ready for the multiplexer.
    """
    return cbor2.dumps([MSG_REQUEST_RANGE, _encode_point(point_from), _encode_point(point_to)])


def encode_client_done() -> bytes:
    """Encode MsgClientDone: ``[1]``.

    Returns CBOR bytes ready for the multiplexer.
    """
    return cbor2.dumps([MSG_CLIENT_DONE])


# ---------------------------------------------------------------------------
# Encode -- server messages
# ---------------------------------------------------------------------------


def encode_start_batch() -> bytes:
    """Encode MsgStartBatch: ``[2]``."""
    return cbor2.dumps([MSG_START_BATCH])


def encode_no_blocks() -> bytes:
    """Encode MsgNoBlocks: ``[3]``."""
    return cbor2.dumps([MSG_NO_BLOCKS])


def encode_block(block_cbor: bytes) -> bytes:
    """Encode MsgBlock: ``[4, block_cbor]``.

    The block_cbor is passed through as raw CBOR-tagged bytes.
    """
    return cbor2.dumps([MSG_BLOCK, block_cbor])


def encode_batch_done() -> bytes:
    """Encode MsgBatchDone: ``[5]``."""
    return cbor2.dumps([MSG_BATCH_DONE])


# ---------------------------------------------------------------------------
# Decode -- server-to-client messages
# ---------------------------------------------------------------------------


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client block-fetch message from CBOR bytes.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload (one complete message).

    Returns
    -------
    ServerMessage
        One of: MsgStartBatch, MsgNoBlocks, MsgBlock, MsgBatchDone.

    Raises
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_START_BATCH:
        if len(msg) != 1:
            raise ValueError(f"MsgStartBatch: expected 1 element, got {len(msg)}")
        return MsgStartBatch()

    elif msg_id == MSG_NO_BLOCKS:
        if len(msg) != 1:
            raise ValueError(f"MsgNoBlocks: expected 1 element, got {len(msg)}")
        return MsgNoBlocks()

    elif msg_id == MSG_BLOCK:
        if len(msg) != 2:
            raise ValueError(f"MsgBlock: expected 2 elements, got {len(msg)}")
        block_cbor = msg[1]
        if isinstance(block_cbor, memoryview):
            block_cbor = bytes(block_cbor)
        return MsgBlock(block_cbor=block_cbor)

    elif msg_id == MSG_BATCH_DONE:
        if len(msg) != 1:
            raise ValueError(f"MsgBatchDone: expected 1 element, got {len(msg)}")
        return MsgBatchDone()

    else:
        raise ValueError(f"Unknown server message ID: {msg_id}")


# ---------------------------------------------------------------------------
# Decode -- client-to-server messages
# ---------------------------------------------------------------------------


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server block-fetch message from CBOR bytes.

    Returns
    -------
    ClientMessage
        One of: MsgRequestRange, MsgClientDone.

    Raises
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_REQUEST_RANGE:
        if len(msg) != 3:
            raise ValueError(
                f"MsgRequestRange: expected 3 elements, got {len(msg)}"
            )
        point_from = _decode_point(msg[1])
        point_to = _decode_point(msg[2])
        return MsgRequestRange(point_from=point_from, point_to=point_to)

    elif msg_id == MSG_CLIENT_DONE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgClientDone: expected 1 element, got {len(msg)}"
            )
        return MsgClientDone()

    else:
        raise ValueError(f"Unknown client message ID: {msg_id}")
