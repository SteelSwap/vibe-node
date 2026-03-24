"""Local Tx-Submission miniprotocol CBOR message codec (N2C protocol ID 6).

Implements encode/decode for the node-to-client local tx-submission
miniprotocol. Unlike the N2N tx-submission (pull-based, server-driven),
local tx-submission is a simple request-response protocol: the CLIENT
submits a transaction, the SERVER validates it and returns accept/reject.

Wire format summary (CBOR arrays):

    MsgSubmitTx   [0, era_id :: uint, tx_bytes :: bstr]
    MsgAcceptTx   [1]
    MsgRejectTx   [2, reason :: any]
    MsgDone       [3]

The era_id wraps the transaction in a HardForkSpecific tag so the server
knows which era's deserializer to use. This follows the Haskell
implementation in ouroboros-network:
    Ouroboros/Network/Protocol/LocalTxSubmission/Codec.hs

The reject reason is opaque CBOR -- the ledger returns era-specific
validation errors that we pass through as raw bytes. Clients must
understand the era-specific error format to interpret them.

Spec reference:
    ouroboros-network, Network.Protocol.LocalTxSubmission.Type
    ouroboros-network, Network.Protocol.LocalTxSubmission.Codec
    Haskell source: ouroboros-network/ouroboros-network-protocols/src/
                    Ouroboros/Network/Protocol/LocalTxSubmission/
"""

from __future__ import annotations

import dataclasses
from typing import Union

import cbor2pure as cbor2

# ---------------------------------------------------------------------------
# Message ID constants -- index 0 of the CBOR array
# ---------------------------------------------------------------------------

MSG_SUBMIT_TX: int = 0
MSG_ACCEPT_TX: int = 1
MSG_REJECT_TX: int = 2
MSG_DONE: int = 3

# Miniprotocol number (N2C)
LOCAL_TX_SUBMISSION_ID: int = 6


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class MsgSubmitTx:
    """Client -> Server: submit a transaction for validation.

    Wire format: ``[0, era_id, tx_bytes]``

    The era_id tells the server which era deserializer to use.
    tx_bytes is the CBOR-encoded transaction body.

    Attributes:
    ----------
    era_id : int
        Era identifier (e.g. 5 = Babbage, 6 = Conway).
    tx_bytes : bytes
        CBOR-encoded transaction.
    """

    era_id: int
    tx_bytes: bytes
    msg_id: int = dataclasses.field(default=MSG_SUBMIT_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgAcceptTx:
    """Server -> Client: transaction accepted (added to mempool).

    Wire format: ``[1]``
    """

    msg_id: int = dataclasses.field(default=MSG_ACCEPT_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgRejectTx:
    """Server -> Client: transaction rejected with a reason.

    Wire format: ``[2, reason]``

    The reason is opaque CBOR -- era-specific ledger validation errors.
    We store it as raw bytes so clients can decode it according to the
    era they're working with.

    Attributes:
    ----------
    reason : bytes
        CBOR-encoded rejection reason (era-specific).
    """

    reason: bytes
    msg_id: int = dataclasses.field(default=MSG_REJECT_TX, init=False)


@dataclasses.dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: terminate the protocol.

    Wire format: ``[3]``
    """

    msg_id: int = dataclasses.field(default=MSG_DONE, init=False)


#: Union of all client-to-server message types.
ClientMessage = Union[MsgSubmitTx, MsgDone]

#: Union of all server-to-client message types.
ServerMessage = Union[MsgAcceptTx, MsgRejectTx]

#: Union of all local tx-submission message types.
LocalTxSubmissionMessage = Union[MsgSubmitTx, MsgAcceptTx, MsgRejectTx, MsgDone]


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def encode_submit_tx(era_id: int, tx_bytes: bytes) -> bytes:
    """Encode MsgSubmitTx: ``[0, era_id, tx_bytes]``.

    Parameters
    ----------
    era_id : int
        Era identifier for the transaction.
    tx_bytes : bytes
        CBOR-encoded transaction body.

    Returns:
    -------
    bytes
        CBOR-encoded message ready for the multiplexer.
    """
    return cbor2.dumps([MSG_SUBMIT_TX, era_id, tx_bytes])


def encode_accept_tx() -> bytes:
    """Encode MsgAcceptTx: ``[1]``.

    Returns:
    -------
    bytes
        CBOR-encoded message ready for the multiplexer.
    """
    return cbor2.dumps([MSG_ACCEPT_TX])


def encode_reject_tx(reason: bytes) -> bytes:
    """Encode MsgRejectTx: ``[2, reason]``.

    Parameters
    ----------
    reason : bytes
        CBOR-encoded rejection reason.

    Returns:
    -------
    bytes
        CBOR-encoded message ready for the multiplexer.
    """
    # The reason is embedded as a CBOR-encoded blob inside the outer array.
    # We decode it first so it becomes a nested CBOR value in the array,
    # matching the Haskell wire format where the reason is inline CBOR.
    reason_value = cbor2.loads(reason)
    return cbor2.dumps([MSG_REJECT_TX, reason_value])


def encode_done() -> bytes:
    """Encode MsgDone: ``[3]``.

    Returns:
    -------
    bytes
        CBOR-encoded message ready for the multiplexer.
    """
    return cbor2.dumps([MSG_DONE])


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def decode_message(cbor_bytes: bytes) -> LocalTxSubmissionMessage:
    """Decode any local tx-submission message from CBOR bytes.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload (one complete message).

    Returns:
    -------
    LocalTxSubmissionMessage
        One of: MsgSubmitTx, MsgAcceptTx, MsgRejectTx, MsgDone.

    Raises:
    ------
    ValueError
        If the message ID is unknown or the payload structure is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == MSG_SUBMIT_TX:
        if len(msg) != 3:
            raise ValueError(f"MsgSubmitTx: expected 3 elements, got {len(msg)}")
        era_id = msg[1]
        if not isinstance(era_id, int) or isinstance(era_id, bool):
            raise ValueError(f"MsgSubmitTx: era_id must be int, got {type(era_id).__name__}")
        tx_bytes = msg[2]
        if isinstance(tx_bytes, memoryview):
            tx_bytes = bytes(tx_bytes)
        if not isinstance(tx_bytes, bytes):
            raise ValueError(f"MsgSubmitTx: tx_bytes must be bytes, got {type(tx_bytes).__name__}")
        return MsgSubmitTx(era_id=era_id, tx_bytes=tx_bytes)

    elif msg_id == MSG_ACCEPT_TX:
        if len(msg) != 1:
            raise ValueError(f"MsgAcceptTx: expected 1 element, got {len(msg)}")
        return MsgAcceptTx()

    elif msg_id == MSG_REJECT_TX:
        if len(msg) != 2:
            raise ValueError(f"MsgRejectTx: expected 2 elements, got {len(msg)}")
        # Re-encode the reason value back to CBOR bytes for storage.
        reason = cbor2.dumps(msg[1])
        return MsgRejectTx(reason=reason)

    elif msg_id == MSG_DONE:
        if len(msg) != 1:
            raise ValueError(f"MsgDone: expected 1 element, got {len(msg)}")
        return MsgDone()

    else:
        raise ValueError(f"Unknown local tx-submission message ID: {msg_id}")


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server local tx-submission message.

    Client messages are MsgSubmitTx and MsgDone.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload.

    Returns:
    -------
    ClientMessage
        One of: MsgSubmitTx, MsgDone.

    Raises:
    ------
    ValueError
        If the message is not a valid client message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgSubmitTx, MsgDone)):
        raise ValueError(
            f"Expected client message (MsgSubmitTx or MsgDone), got: {type(msg).__name__}"
        )
    return msg


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client local tx-submission message.

    Server messages are MsgAcceptTx and MsgRejectTx.

    Parameters
    ----------
    cbor_bytes : bytes
        Raw CBOR payload.

    Returns:
    -------
    ServerMessage
        One of: MsgAcceptTx, MsgRejectTx.

    Raises:
    ------
    ValueError
        If the message is not a valid server message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgAcceptTx, MsgRejectTx)):
        raise ValueError(
            f"Expected server message (MsgAcceptTx or MsgRejectTx), got: {type(msg).__name__}"
        )
    return msg
