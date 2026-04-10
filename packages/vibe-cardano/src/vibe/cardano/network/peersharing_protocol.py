"""Peer-Sharing miniprotocol — typed protocol FSM, codec, and client/server.

Implements the peer-sharing miniprotocol as a typed state machine following
the Ouroboros typed-protocols pattern. The protocol allows nodes to share
peer addresses for peer discovery:

    StIdle  — Client has agency (sends MsgShareRequest or MsgDone)
    StBusy  — Server has agency (sends MsgSharePeers)
    StDone  — Nobody has agency (terminal)

Haskell reference:
    Ouroboros/Network/Protocol/PeerSharing/Type.hs   (PeerSharing protocol type)
    Ouroboros/Network/Protocol/PeerSharing/Client.hs  (PeerSharingClient)
    Ouroboros/Network/Protocol/PeerSharing/Server.hs  (PeerSharingServer)
    Ouroboros/Network/Protocol/PeerSharing/Codec.hs   (codecPeerSharing)

Spec reference:
    Ouroboros network spec, "Peer-Sharing Mini-Protocol"
"""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Awaitable, Callable

from vibe.cardano.network.peersharing import (
    MsgDone,
    MsgSharePeers,
    MsgShareRequest,
    PeerAddress,
    decode_message,
    encode_done,
    encode_share_peers,
    encode_share_request,
)
from vibe.core.protocols.agency import (
    Agency,
    Message,
    PeerRole,
    Protocol,
    ProtocolError,
)
from vibe.core.protocols.codec import CodecError
from vibe.core.protocols.runner import ProtocolRunner

__all__ = [
    "PeerSharingState",
    "PeerSharingProtocol",
    "PeerSharingCodec",
    "PsMsgShareRequest",
    "PsMsgSharePeers",
    "PsMsgDone",
    "run_peer_sharing_client",
    "run_peer_sharing_server",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class PeerSharingState(enum.Enum):
    """States of the peer-sharing miniprotocol state machine.

    Haskell reference: PeerSharing type, with constructors
        StIdle, StBusy, StDone.
    """

    StIdle = "idle"
    """Client has agency — sends MsgShareRequest or MsgDone."""

    StBusy = "busy"
    """Server has agency — sends MsgSharePeers."""

    StDone = "done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class PsMsgShareRequest(Message[PeerSharingState]):
    """Client -> Server: request up to N peer addresses.

    Transition: StIdle -> StBusy
    """

    __slots__ = ("inner",)

    def __init__(self, amount: int) -> None:
        super().__init__(
            from_state=PeerSharingState.StIdle,
            to_state=PeerSharingState.StBusy,
        )
        self.inner = MsgShareRequest(amount=amount)

    @property
    def amount(self) -> int:
        return self.inner.amount


class PsMsgSharePeers(Message[PeerSharingState]):
    """Server -> Client: respond with a list of peer addresses.

    Transition: StBusy -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, peers: tuple[PeerAddress, ...]) -> None:
        super().__init__(
            from_state=PeerSharingState.StBusy,
            to_state=PeerSharingState.StIdle,
        )
        self.inner = MsgSharePeers(peers=peers)

    @property
    def peers(self) -> tuple[PeerAddress, ...]:
        return self.inner.peers


class PsMsgDone(Message[PeerSharingState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=PeerSharingState.StIdle,
            to_state=PeerSharingState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_IDLE_MESSAGES: frozenset[type[Message[PeerSharingState]]] = frozenset(
    {PsMsgShareRequest, PsMsgDone}
)
_BUSY_MESSAGES: frozenset[type[Message[PeerSharingState]]] = frozenset(
    {PsMsgSharePeers}
)
_DONE_MESSAGES: frozenset[type[Message[PeerSharingState]]] = frozenset()


class PeerSharingProtocol(Protocol[PeerSharingState]):
    """Peer-sharing miniprotocol state machine definition.

    Agency map:
        StIdle -> Client (Initiator sends MsgShareRequest or MsgDone)
        StBusy -> Server (Responder sends MsgSharePeers)
        StDone -> Nobody (terminal)

    Haskell reference:
        instance Protocol PeerSharing where
            type ClientHasAgency st = st ~ 'StIdle
            type ServerHasAgency st = st ~ 'StBusy
            type NobodyHasAgency st = st ~ 'StDone
    """

    _AGENCY_MAP = {
        PeerSharingState.StIdle: Agency.Client,
        PeerSharingState.StBusy: Agency.Server,
        PeerSharingState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        PeerSharingState.StIdle: _IDLE_MESSAGES,
        PeerSharingState.StBusy: _BUSY_MESSAGES,
        PeerSharingState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> PeerSharingState:
        return PeerSharingState.StIdle

    def agency(self, state: PeerSharingState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown peer-sharing state: {state!r}")

    def valid_messages(
        self, state: PeerSharingState
    ) -> frozenset[type[Message[PeerSharingState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown peer-sharing state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class PeerSharingCodec:
    """CBOR codec for peer-sharing miniprotocol messages.

    Wraps the encode/decode functions from peersharing.py, translating
    between typed Message wrappers (PsMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[PeerSharingState]) -> bytes:
        """Encode a typed peer-sharing message to CBOR bytes."""
        if isinstance(message, PsMsgShareRequest):
            return encode_share_request(message.amount)
        elif isinstance(message, PsMsgSharePeers):
            return encode_share_peers(message.peers)
        elif isinstance(message, PsMsgDone):
            return encode_done()
        else:
            raise CodecError(
                f"Unknown peer-sharing message type: {type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[PeerSharingState]:
        """Decode CBOR bytes into a typed peer-sharing message."""
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgShareRequest):
            return PsMsgShareRequest(amount=msg.amount)
        elif isinstance(msg, MsgSharePeers):
            return PsMsgSharePeers(peers=msg.peers)
        elif isinstance(msg, MsgDone):
            return PsMsgDone()
        else:
            raise CodecError(
                f"Failed to decode peer-sharing message ({len(data)} bytes)"
            )


# ---------------------------------------------------------------------------
# Client runner
# ---------------------------------------------------------------------------


async def run_peer_sharing_client(
    channel: object,
    *,
    on_peers_received: Callable[[list[PeerAddress]], Awaitable[None]],
    request_interval: float = 60.0,
    max_peers_per_request: int = 10,
    stop_event: asyncio.Event | None = None,
    peer_info: str = "",
) -> None:
    """Run a peer-sharing client loop on the given channel.

    Periodically requests peer addresses from the server and delivers
    them to the ``on_peers_received`` callback. Terminates gracefully
    when ``stop_event`` is set.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for the peer-sharing miniprotocol.
    on_peers_received : Callable
        Async callback invoked with the list of received peers after
        each successful MsgSharePeers response.
    request_interval : float
        Seconds between peer-sharing requests (default: 60).
    max_peers_per_request : int
        Maximum peers to request per round (default: 10, capped at 255).
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.
    peer_info : str
        Human-readable peer identifier for log messages.
    """
    protocol = PeerSharingProtocol()
    codec = PeerSharingCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    # Clamp to word8 range
    amount = min(max_peers_per_request, 255)

    while True:
        # Check for stop before sending
        if stop_event is not None and stop_event.is_set():
            logger.debug("Peer-sharing stop requested, sending MsgDone")
            break

        # Wait for the request interval, exiting early on stop
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=request_interval)
                logger.debug("Peer-sharing stop requested during wait")
                break
            except TimeoutError:
                # Normal — interval elapsed without stop, send request.
                pass
        else:
            await asyncio.sleep(request_interval)

        # Double-check stop after waiting
        if stop_event is not None and stop_event.is_set():
            logger.debug("Peer-sharing stop requested after wait")
            break

        logger.debug(
            "Requesting %d peers from %s", amount, peer_info or "peer"
        )
        await runner.send_message(PsMsgShareRequest(amount=amount))

        response = await runner.recv_message()
        if not isinstance(response, PsMsgSharePeers):
            raise ProtocolError(
                f"Expected PsMsgSharePeers, got: {type(response).__name__}"
            )

        peers = list(response.peers)

        # Validate: server must not return more peers than requested
        if len(peers) > amount:
            logger.warning(
                "Server returned %d peers but we requested %d — truncating",
                len(peers),
                amount,
            )
            peers = peers[:amount]

        logger.info(
            "PeerSharing.Client: peer=%s received=%d peers",
            peer_info or "unknown",
            len(peers),
        )

        await on_peers_received(peers)

    # Send MsgDone to cleanly terminate the protocol
    await runner.send_message(PsMsgDone())


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------


async def run_peer_sharing_server(
    channel: object,
    *,
    peer_provider: Callable[[int], Awaitable[list[PeerAddress]]],
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the server side of the peer-sharing miniprotocol.

    Receives MsgShareRequest from the client, calls ``peer_provider``
    to get peer addresses, and responds with MsgSharePeers. Runs until
    the client sends MsgDone or the stop_event is set.

    Haskell ref:
        ``Ouroboros.Network.Protocol.PeerSharing.Server``

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for peer-sharing (responder direction).
    peer_provider : Callable
        Async function that takes the requested amount and returns a
        list of PeerAddress instances (may return fewer than requested).
    stop_event : asyncio.Event | None
        If provided, the server exits when this event is set.
    """
    protocol = PeerSharingProtocol()
    codec = PeerSharingCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    logger.debug("Peer-sharing server started")

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        msg = await runner.recv_message()

        if isinstance(msg, PsMsgShareRequest):
            amount = msg.amount
            peers = await peer_provider(amount)

            # Ensure we don't exceed the requested amount
            if len(peers) > amount:
                peers = peers[:amount]

            await runner.send_message(
                PsMsgSharePeers(peers=tuple(peers))
            )
            logger.debug(
                "Peer-sharing server: sent %d peers (requested %d)",
                len(peers),
                amount,
            )

        elif isinstance(msg, PsMsgDone):
            logger.debug("Peer-sharing server: client sent Done")
            return

        else:
            logger.warning(
                "Peer-sharing server: unexpected message %s",
                type(msg).__name__,
            )
            return
