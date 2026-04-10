"""Peer-Sharing miniprotocol CBOR message types (N2N protocol ID 10).

Implements the peer-sharing miniprotocol defined in the Ouroboros
network specification and the Haskell reference implementation:

* **MsgShareRequest(amount)** — client requests up to N peer addresses
* **MsgSharePeers(peers)** — server responds with a list of peer addresses
* **MsgDone** — client terminates the protocol

Wire format references:
    - ``codecPeerSharing`` in ``Ouroboros.Network.Protocol.PeerSharing.Codec``
    - ``PeerSharing`` protocol type in ``Ouroboros.Network.Protocol.PeerSharing.Type``

CBOR encoding:
    MsgShareRequest  [0, amount :: word8]
    MsgSharePeers    [1, [* peerAddress]]
    MsgDone          [2]

peerAddress:
    IPv4  [0, word32, word16]                         -- tag + 32-bit IP + port
    IPv6  [1, word32, word32, word32, word32, word16]  -- tag + 4x32-bit + port
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field
from typing import Sequence, Union

import cbor2pure as cbor2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PEER_SHARING_PROTOCOL_ID: int = 10
"""Peer-sharing is miniprotocol number 10 (N2N)."""

# CBOR message tags (first element of the outer list).
_MSG_SHARE_REQUEST: int = 0
_MSG_SHARE_PEERS: int = 1
_MSG_DONE: int = 2

# Amount range: word8 (0..255)
AMOUNT_MIN: int = 0
AMOUNT_MAX: int = 255

# Peer address tags
_PEER_ADDR_IPV4: int = 0
_PEER_ADDR_IPV6: int = 1


# ---------------------------------------------------------------------------
# Peer address dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeerAddress:
    """A peer's network address (IPv4 or IPv6).

    Attributes:
        ip: The IP address as a string (e.g., ``"192.168.1.1"`` or ``"::1"``).
        port: The TCP port number (0..65535).
        is_ipv6: Whether this is an IPv6 address.
    """

    ip: str
    port: int
    is_ipv6: bool = False


# ---------------------------------------------------------------------------
# Message dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MsgShareRequest:
    """Client -> Server: request up to N peer addresses.

    Wire format: ``[0, amount]``

    The amount is a word8 (0..255) indicating the maximum number of
    peer addresses the client would like to receive.
    """

    amount: int
    msg_id: int = field(default=_MSG_SHARE_REQUEST, init=False)


@dataclass(frozen=True, slots=True)
class MsgSharePeers:
    """Server -> Client: respond with a list of peer addresses.

    Wire format: ``[1, [* peerAddress]]``

    The peer list may be empty, and may contain fewer peers than
    requested. Each entry is a ``PeerAddress``.
    """

    peers: tuple[PeerAddress, ...]
    msg_id: int = field(default=_MSG_SHARE_PEERS, init=False)


@dataclass(frozen=True, slots=True)
class MsgDone:
    """Client -> Server: terminate the peer-sharing protocol.

    Wire format: ``[2]``
    """

    msg_id: int = field(default=_MSG_DONE, init=False)


#: Union of all client-to-server message types.
ClientMessage = Union[MsgShareRequest, MsgDone]

#: Union of all server-to-client message types.
ServerMessage = MsgSharePeers

#: Union of all peer-sharing message types.
PeerSharingMessage = Union[MsgShareRequest, MsgSharePeers, MsgDone]


# ---------------------------------------------------------------------------
# Peer address encode / decode
# ---------------------------------------------------------------------------


def encode_peer_address(addr: PeerAddress) -> list:
    """Encode a PeerAddress to a CBOR-compatible list.

    IPv4: ``[0, word32, word16]`` where word32 is the IP packed as big-endian.
    IPv6: ``[1, word32, word32, word32, word32, word16]`` where the IP is
    packed as four big-endian 32-bit words.

    Args:
        addr: The peer address to encode.

    Returns:
        A list suitable for inclusion in a CBOR-encoded MsgSharePeers.

    Raises:
        ValueError: If the address cannot be packed.
    """
    if addr.is_ipv6:
        packed = socket.inet_pton(socket.AF_INET6, addr.ip)
        w0, w1, w2, w3 = struct.unpack("!IIII", packed)
        return [_PEER_ADDR_IPV6, w0, w1, w2, w3, addr.port]
    else:
        packed = socket.inet_aton(addr.ip)
        (w,) = struct.unpack("!I", packed)
        return [_PEER_ADDR_IPV4, w, addr.port]


def decode_peer_address(term: list) -> PeerAddress:
    """Decode a CBOR-decoded list into a PeerAddress.

    Args:
        term: A list in one of the wire formats:
            - ``[0, word32, word16]`` for IPv4
            - ``[1, word32, word32, word32, word32, word16]`` for IPv6

    Returns:
        A PeerAddress instance.

    Raises:
        ValueError: If the term does not match a valid peer address format.
    """
    # Accept both list and indefinite-length CBOR sequences.
    if not isinstance(term, (list, tuple)):
        try:
            term = list(term)
        except TypeError:
            raise ValueError(f"Expected peer address list, got: {term!r}")
    if len(term) < 1:
        raise ValueError(f"Expected peer address list, got: {term!r}")

    tag = term[0]

    if tag == _PEER_ADDR_IPV4:
        if len(term) != 3:
            raise ValueError(
                f"IPv4 peer address: expected 3 elements, got {len(term)}"
            )
        w = term[1]
        port = term[2]
        if not isinstance(w, int) or not isinstance(port, int):
            raise ValueError(f"IPv4 peer address: expected integers, got {term!r}")
        packed = struct.pack("!I", w)
        ip = socket.inet_ntoa(packed)
        return PeerAddress(ip=ip, port=port, is_ipv6=False)

    elif tag == _PEER_ADDR_IPV6:
        if len(term) != 6:
            raise ValueError(
                f"IPv6 peer address: expected 6 elements, got {len(term)}"
            )
        w0, w1, w2, w3, port = term[1], term[2], term[3], term[4], term[5]
        if not all(isinstance(v, int) for v in (w0, w1, w2, w3, port)):
            raise ValueError(f"IPv6 peer address: expected integers, got {term!r}")
        packed = struct.pack("!IIII", w0, w1, w2, w3)
        ip = socket.inet_ntop(socket.AF_INET6, packed)
        return PeerAddress(ip=ip, port=port, is_ipv6=True)

    else:
        raise ValueError(f"Unknown peer address tag: {tag}")


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def encode_share_request(amount: int) -> bytes:
    """Encode MsgShareRequest: ``[0, amount]``.

    Args:
        amount: Number of peers to request (0..255).

    Returns:
        CBOR-encoded bytes ready for the multiplexer.

    Raises:
        ValueError: If the amount is out of the word8 range.
    """
    if not (AMOUNT_MIN <= amount <= AMOUNT_MAX):
        raise ValueError(f"Amount must be word8 (0..255), got: {amount}")
    return cbor2.dumps([_MSG_SHARE_REQUEST, amount])


def encode_share_peers(peers: Sequence[PeerAddress]) -> bytes:
    """Encode MsgSharePeers: ``[1, [* peerAddress]]``.

    Args:
        peers: Sequence of PeerAddress instances to encode.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_SHARE_PEERS, [encode_peer_address(p) for p in peers]])


def encode_done() -> bytes:
    """Encode MsgDone: ``[2]``.

    Returns:
        CBOR-encoded bytes ready for the multiplexer.
    """
    return cbor2.dumps([_MSG_DONE])


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def decode_message(cbor_bytes: bytes) -> PeerSharingMessage:
    """Decode any peer-sharing message from CBOR bytes.

    Handles all three message types: MsgShareRequest, MsgSharePeers,
    and MsgDone.

    Args:
        cbor_bytes: Raw CBOR payload (one complete message).

    Returns:
        One of: MsgShareRequest, MsgSharePeers, MsgDone.

    Raises:
        ValueError: If the message ID is unknown or the payload is invalid.
    """
    msg = cbor2.loads(cbor_bytes)

    # Normalize indefinite-length CBOR sequences to plain list.
    if not isinstance(msg, list):
        try:
            msg = list(msg)
        except TypeError:
            raise ValueError(f"Expected CBOR list, got: {type(msg).__name__}")
    if len(msg) < 1:
        raise ValueError(f"Expected CBOR list, got {type(msg).__name__}")

    msg_id = msg[0]

    if msg_id == _MSG_SHARE_REQUEST:
        if len(msg) != 2:
            raise ValueError(
                f"MsgShareRequest: expected 2 elements, got {len(msg)}"
            )
        amount = msg[1]
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise ValueError(f"Amount must be an integer, got: {amount!r}")
        if not (AMOUNT_MIN <= amount <= AMOUNT_MAX):
            raise ValueError(f"Amount must be word8 (0..255), got: {amount}")
        return MsgShareRequest(amount=amount)

    elif msg_id == _MSG_SHARE_PEERS:
        if len(msg) != 2:
            raise ValueError(
                f"MsgSharePeers: expected 2 elements, got {len(msg)}"
            )
        peer_list = msg[1]
        # Accept both definite (list) and indefinite-length CBOR lists.
        # Haskell encodes peer addresses with indefinite-length encoding
        # which cbor2 decodes as IndefiniteFrozenList, not plain list.
        try:
            peers = tuple(decode_peer_address(p) for p in peer_list)
        except TypeError:
            raise ValueError(
                f"MsgSharePeers: expected iterable of peers, got {type(peer_list).__name__}"
            )
        return MsgSharePeers(peers=peers)

    elif msg_id == _MSG_DONE:
        if len(msg) != 1:
            raise ValueError(f"MsgDone: expected 1 element, got {len(msg)}")
        return MsgDone()

    else:
        raise ValueError(f"Unknown peer-sharing message ID: {msg_id}")


def decode_server_message(cbor_bytes: bytes) -> ServerMessage:
    """Decode a server-to-client peer-sharing message from CBOR bytes.

    The only server message is MsgSharePeers.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        MsgSharePeers.

    Raises:
        ValueError: If the message is not a valid server message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, MsgSharePeers):
        raise ValueError(
            f"Expected server message (MsgSharePeers), got: {type(msg).__name__}"
        )
    return msg


def decode_client_message(cbor_bytes: bytes) -> ClientMessage:
    """Decode a client-to-server peer-sharing message from CBOR bytes.

    Client messages are MsgShareRequest and MsgDone.

    Args:
        cbor_bytes: Raw CBOR payload.

    Returns:
        One of: MsgShareRequest, MsgDone.

    Raises:
        ValueError: If the message is not a valid client message.
    """
    msg = decode_message(cbor_bytes)
    if not isinstance(msg, (MsgShareRequest, MsgDone)):
        raise ValueError(
            f"Expected client message (MsgShareRequest or MsgDone), got: {type(msg).__name__}"
        )
    return msg
