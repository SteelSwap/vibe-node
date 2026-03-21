"""Local Tx-Monitor miniprotocol CBOR message codec (N2C protocol ID 9).

Implements encode/decode for the node-to-client local tx-monitor
miniprotocol. This protocol allows local clients to query the mempool:
acquire a consistent snapshot, iterate transactions, check membership,
and get size statistics.

Wire format summary (CBOR arrays):

    MsgAcquire          [0]
    MsgAcquired         [1, slot :: uint]
    MsgAwaitAcquire     [2]
    MsgRelease          [3]
    MsgNextTx           [4]
    MsgReplyNextTx      [5, Nothing] or [5, Just(era_id, tx_bytes)]
    MsgHasTx            [6, tx_id :: bstr]
    MsgReplyHasTx       [7, bool]
    MsgGetSizes         [8]
    MsgReplyGetSizes    [9, num_txs :: uint, total_size :: uint, num_bytes :: uint]
    MsgDone             [10]

The MsgReplyNextTx encoding uses a Maybe-style CBOR encoding:
    Nothing = [5, []]
    Just tx = [5, [era_id, tx_bytes]]

This matches the Haskell implementation in:
    Ouroboros/Network/Protocol/LocalTxMonitor/Codec.hs

Spec reference:
    ouroboros-network, Network.Protocol.LocalTxMonitor.Type
    ouroboros-network, Network.Protocol.LocalTxMonitor.Codec
"""

from __future__ import annotations

import dataclasses
from typing import Union

import cbor2

# ---------------------------------------------------------------------------
# Message ID constants -- index 0 of the CBOR array
# ---------------------------------------------------------------------------

MSG_ACQUIRE: int = 0
MSG_ACQUIRED: int = 1
MSG_AWAIT_ACQUIRE: int = 2
MSG_RELEASE: int = 3
MSG_NEXT_TX: int = 4
MSG_REPLY_NEXT_TX: int = 5
MSG_HAS_TX: int = 6
MSG_REPLY_HAS_TX: int = 7
MSG_GET_SIZES: int = 8
MSG_REPLY_GET_SIZES: int = 9
MSG_DONE: int = 10

# Miniprotocol number (N2C)
LOCAL_TX_MONITOR_ID: int = 9


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class MsgAcquire:
    """Client -> Server: request a mempool snapshot.

    Wire format: ``[0]``
    """

    msg_id: int = dataclasses.field(default=MSG_ACQUIRE, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgAcquired:
    """Server -> Client: mempool snapshot acquired at a given slot.

    Wire format: ``[1, slot]``

    Attributes
    ----------
    slot : int
        The slot number at which the mempool snapshot was taken.
    """

    slot: int
    msg_id: int = dataclasses.field(default=MSG_ACQUIRED, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgAwaitAcquire:
    """Client -> Server: wait for mempool change, then acquire.

    Wire format: ``[2]``

    Like MsgAcquire but the server will block until the mempool
    has changed since the last snapshot before responding.
    """

    msg_id: int = dataclasses.field(default=MSG_AWAIT_ACQUIRE, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRelease:
    """Client -> Server: release the current mempool snapshot.

    Wire format: ``[3]``
    """

    msg_id: int = dataclasses.field(default=MSG_RELEASE, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgNextTx:
    """Client -> Server: request the next transaction from the snapshot.

    Wire format: ``[4]``
    """

    msg_id: int = dataclasses.field(default=MSG_NEXT_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgReplyNextTx:
    """Server -> Client: reply with the next transaction or Nothing.

    Wire format:
        Nothing: ``[5, []]``
        Just:    ``[5, [era_id, tx_bytes]]``

    Attributes
    ----------
    tx : tuple[int, bytes] | None
        If not None, a (era_id, tx_bytes) pair for the next transaction.
        If None, there are no more transactions in the snapshot.
    """

    tx: tuple[int, bytes] | None
    msg_id: int = dataclasses.field(default=MSG_REPLY_NEXT_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgHasTx:
    """Client -> Server: check if a transaction is in the mempool.

    Wire format: ``[6, tx_id]``

    Attributes
    ----------
    tx_id : bytes
        Transaction ID (hash) to look up.
    """

    tx_id: bytes
    msg_id: int = dataclasses.field(default=MSG_HAS_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgReplyHasTx:
    """Server -> Client: whether the transaction is in the mempool.

    Wire format: ``[7, bool]``

    Attributes
    ----------
    has_tx : bool
        True if the transaction is in the mempool snapshot.
    """

    has_tx: bool
    msg_id: int = dataclasses.field(default=MSG_REPLY_HAS_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgGetSizes:
    """Client -> Server: request mempool size statistics.

    Wire format: ``[8]``
    """

    msg_id: int = dataclasses.field(default=MSG_GET_SIZES, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgReplyGetSizes:
    """Server -> Client: mempool size statistics.

    Wire format: ``[9, num_txs, total_size, num_bytes]``

    Attributes
    ----------
    num_txs : int
        Number of transactions in the mempool.
    total_size : int
        Total size of all transactions in bytes.
    num_bytes : int
        Number of bytes used by the mempool (may differ from total_size
        due to overhead).
    """

    num_txs: int
    total_size: int
    num_bytes: int
    msg_id: int = dataclasses.field(default=MSG_REPLY_GET_SIZES, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: terminate the protocol.

    Wire format: ``[10]``
    """

    msg_id: int = dataclasses.field(default=MSG_DONE, init=False)


#: Union of all client-to-server message types (client has agency).
ClientMessage = Union[
    MsgAcquire, MsgAwaitAcquire, MsgRelease,
    MsgNextTx, MsgHasTx, MsgGetSizes, MsgDone,
]

#: Union of all server-to-client message types (server has agency).
ServerMessage = Union[
    MsgAcquired, MsgReplyNextTx, MsgReplyHasTx, MsgReplyGetSizes,
]

#: Union of all local tx-monitor message types.
LocalTxMonitorMessage = Union[
    MsgAcquire, MsgAcquired, MsgAwaitAcquire, MsgRelease,
    MsgNextTx, MsgReplyNextTx, MsgHasTx, MsgReplyHasTx,
    MsgGetSizes, MsgReplyGetSizes, MsgDone,
]


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def encode_acquire() -> bytes:
    """Encode MsgAcquire: ``[0]``."""
    return cbor2.dumps([MSG_ACQUIRE])


def encode_acquired(slot: int) -> bytes:
    """Encode MsgAcquired: ``[1, slot]``."""
    return cbor2.dumps([MSG_ACQUIRED, slot])


def encode_await_acquire() -> bytes:
    """Encode MsgAwaitAcquire: ``[2]``."""
    return cbor2.dumps([MSG_AWAIT_ACQUIRE])


def encode_release() -> bytes:
    """Encode MsgRelease: ``[3]``."""
    return cbor2.dumps([MSG_RELEASE])


def encode_next_tx() -> bytes:
    """Encode MsgNextTx: ``[4]``."""
    return cbor2.dumps([MSG_NEXT_TX])


def encode_reply_next_tx(tx: tuple[int, bytes] | None) -> bytes:
    """Encode MsgReplyNextTx.

    Nothing: ``[5, []]``
    Just:    ``[5, [era_id, tx_bytes]]``

    Parameters
    ----------
    tx : tuple[int, bytes] | None
        The transaction (era_id, tx_bytes) or None.
    """
    if tx is None:
        return cbor2.dumps([MSG_REPLY_NEXT_TX, []])
    era_id, tx_bytes = tx
    return cbor2.dumps([MSG_REPLY_NEXT_TX, [era_id, tx_bytes]])


def encode_has_tx(tx_id: bytes) -> bytes:
    """Encode MsgHasTx: ``[6, tx_id]``."""
    return cbor2.dumps([MSG_HAS_TX, tx_id])


def encode_reply_has_tx(has_tx: bool) -> bytes:
    """Encode MsgReplyHasTx: ``[7, bool]``."""
    return cbor2.dumps([MSG_REPLY_HAS_TX, has_tx])


def encode_get_sizes() -> bytes:
    """Encode MsgGetSizes: ``[8]``."""
    return cbor2.dumps([MSG_GET_SIZES])


def encode_reply_get_sizes(
    num_txs: int, total_size: int, num_bytes: int
) -> bytes:
    """Encode MsgReplyGetSizes: ``[9, num_txs, total_size, num_bytes]``."""
    return cbor2.dumps([MSG_REPLY_GET_SIZES, num_txs, total_size, num_bytes])


def encode_done() -> bytes:
    """Encode MsgDone: ``[10]``."""
    return cbor2.dumps([MSG_DONE])


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def decode_message(cbor_bytes: bytes) -> LocalTxMonitorMessage:
    """Decode any local tx-monitor message from CBOR bytes.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload (one complete message).

    Returns
    -------
    LocalTxMonitorMessage
        The decoded message.

    Raises
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_ACQUIRE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgAcquire: expected 1 element, got {len(msg)}"
            )
        return MsgAcquire()

    elif msg_id == MSG_ACQUIRED:
        if len(msg) != 2:
            raise ValueError(
                f"MsgAcquired: expected 2 elements, got {len(msg)}"
            )
        slot = msg[1]
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ValueError(
                f"MsgAcquired: slot must be int, got {type(slot).__name__}"
            )
        return MsgAcquired(slot=slot)

    elif msg_id == MSG_AWAIT_ACQUIRE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgAwaitAcquire: expected 1 element, got {len(msg)}"
            )
        return MsgAwaitAcquire()

    elif msg_id == MSG_RELEASE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgRelease: expected 1 element, got {len(msg)}"
            )
        return MsgRelease()

    elif msg_id == MSG_NEXT_TX:
        if len(msg) != 1:
            raise ValueError(
                f"MsgNextTx: expected 1 element, got {len(msg)}"
            )
        return MsgNextTx()

    elif msg_id == MSG_REPLY_NEXT_TX:
        if len(msg) != 2:
            raise ValueError(
                f"MsgReplyNextTx: expected 2 elements, got {len(msg)}"
            )
        inner = msg[1]
        if not isinstance(inner, list):
            raise ValueError(
                f"MsgReplyNextTx: inner must be list, got "
                f"{type(inner).__name__}"
            )
        if len(inner) == 0:
            return MsgReplyNextTx(tx=None)
        elif len(inner) == 2:
            era_id = inner[0]
            tx_bytes = inner[1]
            if isinstance(tx_bytes, memoryview):
                tx_bytes = bytes(tx_bytes)
            if not isinstance(tx_bytes, bytes):
                raise ValueError(
                    f"MsgReplyNextTx: tx_bytes must be bytes, got "
                    f"{type(tx_bytes).__name__}"
                )
            return MsgReplyNextTx(tx=(era_id, tx_bytes))
        else:
            raise ValueError(
                f"MsgReplyNextTx: inner list must have 0 or 2 elements, "
                f"got {len(inner)}"
            )

    elif msg_id == MSG_HAS_TX:
        if len(msg) != 2:
            raise ValueError(
                f"MsgHasTx: expected 2 elements, got {len(msg)}"
            )
        tx_id = msg[1]
        if isinstance(tx_id, memoryview):
            tx_id = bytes(tx_id)
        if not isinstance(tx_id, bytes):
            raise ValueError(
                f"MsgHasTx: tx_id must be bytes, got {type(tx_id).__name__}"
            )
        return MsgHasTx(tx_id=tx_id)

    elif msg_id == MSG_REPLY_HAS_TX:
        if len(msg) != 2:
            raise ValueError(
                f"MsgReplyHasTx: expected 2 elements, got {len(msg)}"
            )
        has_tx = msg[1]
        if not isinstance(has_tx, bool):
            raise ValueError(
                f"MsgReplyHasTx: has_tx must be bool, got "
                f"{type(has_tx).__name__}"
            )
        return MsgReplyHasTx(has_tx=has_tx)

    elif msg_id == MSG_GET_SIZES:
        if len(msg) != 1:
            raise ValueError(
                f"MsgGetSizes: expected 1 element, got {len(msg)}"
            )
        return MsgGetSizes()

    elif msg_id == MSG_REPLY_GET_SIZES:
        if len(msg) != 4:
            raise ValueError(
                f"MsgReplyGetSizes: expected 4 elements, got {len(msg)}"
            )
        num_txs = msg[1]
        total_size = msg[2]
        num_bytes = msg[3]
        for name, val in [
            ("num_txs", num_txs),
            ("total_size", total_size),
            ("num_bytes", num_bytes),
        ]:
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(
                    f"MsgReplyGetSizes: {name} must be int, got "
                    f"{type(val).__name__}"
                )
        return MsgReplyGetSizes(
            num_txs=num_txs, total_size=total_size, num_bytes=num_bytes
        )

    elif msg_id == MSG_DONE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgDone: expected 1 element, got {len(msg)}"
            )
        return MsgDone()

    else:
        raise ValueError(f"Unknown local tx-monitor message ID: {msg_id}")


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server local tx-monitor message.

    Raises
    ------
    ValueError
        If the message is not a valid client message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(
        msg,
        (MsgAcquire, MsgAwaitAcquire, MsgRelease, MsgNextTx, MsgHasTx,
         MsgGetSizes, MsgDone),
    ):
        raise ValueError(
            f"Expected client message, got: {type(msg).__name__}"
        )
    return msg


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client local tx-monitor message.

    Raises
    ------
    ValueError
        If the message is not a valid server message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(
        msg,
        (MsgAcquired, MsgReplyNextTx, MsgReplyHasTx, MsgReplyGetSizes),
    ):
        raise ValueError(
            f"Expected server message, got: {type(msg).__name__}"
        )
    return msg
