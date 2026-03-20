"""Keep-Alive miniprotocol CBOR message types (N2N protocol ID 8).

Implements the keep-alive ping/pong miniprotocol defined in the Ouroboros
network specification and the Haskell reference implementation:

* **MsgKeepAlive(cookie)** — client sends a ping with a 16-bit cookie
* **MsgKeepAliveResponse(cookie)** — server echoes back the same cookie
* **MsgDone** — client terminates the protocol

Wire format references:
    - ``codecKeepAlive`` in ``Ouroboros.Network.Protocol.KeepAlive.Codec``
    - ``KeepAlive`` protocol type in ``Ouroboros.Network.Protocol.KeepAlive.Type``

CBOR encoding:
    MsgKeepAlive          [0, cookie :: uint16]
    MsgKeepAliveResponse  [1, cookie :: uint16]
    MsgDone               [2]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

import cbor2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KEEP_ALIVE_PROTOCOL_ID: int = 8
"""Keep-alive is miniprotocol number 8 (N2N)."""

# CBOR message tags (first element of the outer list).
_MSG_KEEP_ALIVE: int = 0
_MSG_KEEP_ALIVE_RESPONSE: int = 1
_MSG_DONE: int = 2

# Cookie range: uint16 (0..65535)
COOKIE_MIN: int = 0
COOKIE_MAX: int = 0xFFFF


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MsgKeepAlive:
    """Client -> Server: ping with a 16-bit cookie.

    Wire format: ``[0, cookie]``

    The cookie is an opaque uint16 that the server must echo back
    in its MsgKeepAliveResponse. This allows the client to match
    responses to requests and detect stale connections.
    """

    cookie: int
    msg_id: int = field(default=_MSG_KEEP_ALIVE, init=False)


@dataclass(frozen=True, slots=True)
class MsgKeepAliveResponse:
    """Server -> Client: pong echoing back the cookie.

    Wire format: ``[1, cookie]``

    The cookie MUST match the value from the corresponding MsgKeepAlive.
    """

    cookie: int
    msg_id: int = field(default=_MSG_KEEP_ALIVE_RESPONSE, init=False)


@dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: terminate the keep-alive protocol.

    Wire format: ``[2]``
    """

    msg_id: int = field(default=_MSG_DONE, init=False)


#: Union of all client-to-server message types.
ClientMessage = Union[MsgKeepAlive, MsgDone]

#: Union of all server-to-client message types.
ServerMessage = MsgKeepAliveResponse

#: Union of all keep-alive message types.
KeepAliveMessage = Union[MsgKeepAlive, MsgKeepAliveResponse, MsgDone]


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def encode_keep_alive(cookie: int) -> bytes:
    """Encode MsgKeepAlive: ``[0, cookie]``.

    Args:
        cookie: A uint16 value (0..65535).

    Returns:
        CBOR-encoded bytes ready for the multiplexer.

    Raises:
        ValueError: If the cookie is out of the uint16 range.
    """
    if not (COOKIE_MIN <= cookie <= COOKIE_MAX):
        raise ValueError(
            f"Cookie must be uint16 (0..65535), got: {cookie}"
        )
    return cbor2.dumps([_MSG_KEEP_ALIVE, cookie])


def encode_keep_alive_response(cookie: int) -> bytes:
    """Encode MsgKeepAliveResponse: ``[1, cookie]``.

    Args:
        cookie: The cookie echoed from the client's MsgKeepAlive.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.

    Raises:
        ValueError: If the cookie is out of the uint16 range.
    """
    if not (COOKIE_MIN <= cookie <= COOKIE_MAX):
        raise ValueError(
            f"Cookie must be uint16 (0..65535), got: {cookie}"
        )
    return cbor2.dumps([_MSG_KEEP_ALIVE_RESPONSE, cookie])


def encode_done() -> bytes:
    """Encode MsgDone: ``[2]``.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_DONE])


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def _validate_cookie(cookie: object) -> int:
    """Validate and return a cookie value from decoded CBOR.

    Raises:
        ValueError: If the cookie is not a valid uint16 integer.
    """
    if not isinstance(cookie, int) or isinstance(cookie, bool):
        raise ValueError(f"Cookie must be an integer, got: {cookie!r}")
    if not (COOKIE_MIN <= cookie <= COOKIE_MAX):
        raise ValueError(
            f"Cookie must be uint16 (0..65535), got: {cookie}"
        )
    return cookie


def decode_message(cbor_bytes: bytes) -> KeepAliveMessage:
    """Decode any keep-alive message from CBOR bytes.

    Handles all three message types: MsgKeepAlive, MsgKeepAliveResponse,
    and MsgDone.

    Args:
        cbor_bytes: Raw CBOR payload (one complete message).

    Returns:
        One of: MsgKeepAlive, MsgKeepAliveResponse, MsgDone.

    Raises:
        ValueError: If the message ID is unknown or the payload is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    if not isinstance(msg, list) or len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == _MSG_KEEP_ALIVE:
        if len(msg) != 2:
            raise ValueError(
                f"MsgKeepAlive: expected 2 elements, got {len(msg)}"
            )
        cookie = _validate_cookie(msg[1])
        return MsgKeepAlive(cookie=cookie)

    elif msg_id == _MSG_KEEP_ALIVE_RESPONSE:
        if len(msg) != 2:
            raise ValueError(
                f"MsgKeepAliveResponse: expected 2 elements, got {len(msg)}"
            )
        cookie = _validate_cookie(msg[1])
        return MsgKeepAliveResponse(cookie=cookie)

    elif msg_id == _MSG_DONE:
        if len(msg) != 1:
            raise ValueError(
                f"MsgDone: expected 1 element, got {len(msg)}"
            )
        return MsgDone()

    else:
        raise ValueError(f"Unknown keep-alive message ID: {msg_id}")


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client keep-alive message from CBOR bytes.

    The only server message is MsgKeepAliveResponse.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        MsgKeepAliveResponse.

    Raises:
        ValueError: If the message is not a valid server message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, MsgKeepAliveResponse):
        raise ValueError(
            f"Expected server message (MsgKeepAliveResponse), "
            f"got: {type(msg).__name__}"
        )
    return msg


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server keep-alive message from CBOR bytes.

    Client messages are MsgKeepAlive and MsgDone.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        One of: MsgKeepAlive, MsgDone.

    Raises:
        ValueError: If the message is not a valid client message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgKeepAlive, MsgDone)):
        raise ValueError(
            f"Expected client message (MsgKeepAlive or MsgDone), "
            f"got: {type(msg).__name__}"
        )
    return msg
