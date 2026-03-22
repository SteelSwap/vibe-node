"""Keep-Alive miniprotocol — typed protocol FSM, codec, and client.

Implements the keep-alive miniprotocol as a typed state machine following
the Ouroboros typed-protocols pattern. The protocol is a simple ping/pong
used to detect dead connections:

    StClient  — Client has agency (sends MsgKeepAlive or MsgDone)
    StServer  — Server has agency (sends MsgKeepAliveResponse)
    StDone    — Nobody has agency (terminal)

Haskell reference:
    Ouroboros/Network/Protocol/KeepAlive/Type.hs   (KeepAlive protocol type)
    Ouroboros/Network/Protocol/KeepAlive/Client.hs  (KeepAliveClient)
    Ouroboros/Network/Protocol/KeepAlive/Codec.hs   (codecKeepAlive)

Spec reference:
    Ouroboros network spec, "Keep-Alive Mini-Protocol"
"""

from __future__ import annotations

import asyncio
import enum
import logging
import random

from vibe.core.protocols.agency import (
    Agency,
    Message,
    Protocol,
    ProtocolError,
    PeerRole,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.keepalive import (
    COOKIE_MAX,
    COOKIE_MIN,
    KEEP_ALIVE_PROTOCOL_ID,
    MsgDone,
    MsgKeepAlive,
    MsgKeepAliveResponse,
    decode_client_message,
    decode_message,
    decode_server_message,
    encode_done,
    encode_keep_alive,
    encode_keep_alive_response,
)

__all__ = [
    "KeepAliveState",
    "KeepAliveProtocol",
    "KeepAliveCodec",
    "KeepAliveClient",
    "KaMsgKeepAlive",
    "KaMsgKeepAliveResponse",
    "KaMsgDone",
    "run_keep_alive_client",
    "run_keep_alive_server",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class KeepAliveState(enum.Enum):
    """States of the keep-alive miniprotocol state machine.

    Haskell reference: KeepAlive type, with constructors
        StClient, StServer, StDone.
    """

    StClient = "client"
    """Client has agency — sends MsgKeepAlive or MsgDone."""

    StServer = "server"
    """Server has agency — sends MsgKeepAliveResponse."""

    StDone = "done"
    """Terminal state. Nobody has agency. Protocol complete."""


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class KaMsgKeepAlive(Message[KeepAliveState]):
    """Client -> Server: ping with a cookie.

    Transition: StClient -> StServer
    """

    __slots__ = ("inner",)

    def __init__(self, cookie: int) -> None:
        super().__init__(
            from_state=KeepAliveState.StClient,
            to_state=KeepAliveState.StServer,
        )
        self.inner = MsgKeepAlive(cookie=cookie)

    @property
    def cookie(self) -> int:
        return self.inner.cookie


class KaMsgKeepAliveResponse(Message[KeepAliveState]):
    """Server -> Client: pong echoing the cookie.

    Transition: StServer -> StClient
    """

    __slots__ = ("inner",)

    def __init__(self, cookie: int) -> None:
        super().__init__(
            from_state=KeepAliveState.StServer,
            to_state=KeepAliveState.StClient,
        )
        self.inner = MsgKeepAliveResponse(cookie=cookie)

    @property
    def cookie(self) -> int:
        return self.inner.cookie


class KaMsgDone(Message[KeepAliveState]):
    """Client -> Server: terminate the protocol.

    Transition: StClient -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=KeepAliveState.StClient,
            to_state=KeepAliveState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_CLIENT_MESSAGES: frozenset[type[Message[KeepAliveState]]] = frozenset(
    {KaMsgKeepAlive, KaMsgDone}
)
_SERVER_MESSAGES: frozenset[type[Message[KeepAliveState]]] = frozenset(
    {KaMsgKeepAliveResponse}
)
_DONE_MESSAGES: frozenset[type[Message[KeepAliveState]]] = frozenset()


class KeepAliveProtocol(Protocol[KeepAliveState]):
    """Keep-alive miniprotocol state machine definition.

    Agency map:
        StClient -> Client (Initiator sends MsgKeepAlive or MsgDone)
        StServer -> Server (Responder sends MsgKeepAliveResponse)
        StDone   -> Nobody (terminal)

    Haskell reference:
        instance Protocol KeepAlive where
            type ClientHasAgency st = st ~ 'StClient
            type ServerHasAgency st = st ~ 'StServer
            type NobodyHasAgency st = st ~ 'StDone
    """

    _AGENCY_MAP = {
        KeepAliveState.StClient: Agency.Client,
        KeepAliveState.StServer: Agency.Server,
        KeepAliveState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        KeepAliveState.StClient: _CLIENT_MESSAGES,
        KeepAliveState.StServer: _SERVER_MESSAGES,
        KeepAliveState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> KeepAliveState:
        return KeepAliveState.StClient

    def agency(self, state: KeepAliveState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown keep-alive state: {state!r}")

    def valid_messages(
        self, state: KeepAliveState
    ) -> frozenset[type[Message[KeepAliveState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown keep-alive state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class KeepAliveCodec:
    """CBOR codec for keep-alive miniprotocol messages.

    Wraps the encode/decode functions from keepalive.py, translating
    between typed Message wrappers (KaMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[KeepAliveState]) -> bytes:
        """Encode a typed keep-alive message to CBOR bytes."""
        if isinstance(message, KaMsgKeepAlive):
            return encode_keep_alive(message.cookie)
        elif isinstance(message, KaMsgKeepAliveResponse):
            return encode_keep_alive_response(message.cookie)
        elif isinstance(message, KaMsgDone):
            return encode_done()
        else:
            raise CodecError(
                f"Unknown keep-alive message type: {type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[KeepAliveState]:
        """Decode CBOR bytes into a typed keep-alive message."""
        try:
            msg = decode_message(data)
        except ValueError as exc:
            raise CodecError(str(exc)) from exc

        if isinstance(msg, MsgKeepAlive):
            return KaMsgKeepAlive(cookie=msg.cookie)
        elif isinstance(msg, MsgKeepAliveResponse):
            return KaMsgKeepAliveResponse(cookie=msg.cookie)
        elif isinstance(msg, MsgDone):
            return KaMsgDone()
        else:
            raise CodecError(
                f"Failed to decode keep-alive message ({len(data)} bytes)"
            )


# ---------------------------------------------------------------------------
# High-level client
# ---------------------------------------------------------------------------


class KeepAliveClient:
    """High-level keep-alive client that uses ProtocolRunner.

    Provides ergonomic async methods for sending pings and receiving pongs.

    Parameters
    ----------
    runner : ProtocolRunner[KeepAliveState]
        A protocol runner already set up with KeepAliveProtocol, codec,
        and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: ProtocolRunner[KeepAliveState]) -> None:
        self._runner = runner

    @property
    def state(self) -> KeepAliveState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def ping(self, cookie: int | None = None) -> int:
        """Send a keep-alive ping and wait for the pong.

        Parameters
        ----------
        cookie : int | None
            The cookie to send. If None, a random uint16 is generated.

        Returns
        -------
        int
            The cookie echoed by the server.

        Raises
        ------
        ProtocolError
            If not in StClient state, or if the server sends an
            unexpected message, or if the echoed cookie doesn't match.
        """
        if cookie is None:
            cookie = random.randint(COOKIE_MIN, COOKIE_MAX)

        await self._runner.send_message(KaMsgKeepAlive(cookie))
        response = await self._runner.recv_message()

        if not isinstance(response, KaMsgKeepAliveResponse):
            raise ProtocolError(
                f"Expected MsgKeepAliveResponse, got: "
                f"{type(response).__name__}"
            )

        if response.cookie != cookie:
            raise ProtocolError(
                f"Cookie mismatch: sent {cookie}, got {response.cookie}"
            )

        return response.cookie

    async def done(self) -> None:
        """Send MsgDone to terminate the protocol.

        After calling this, no further messages can be sent or received.
        """
        await self._runner.send_message(KaMsgDone())


# ---------------------------------------------------------------------------
# High-level keep-alive loop
# ---------------------------------------------------------------------------


async def run_keep_alive_client(
    channel: object,
    *,
    interval: float = 90.0,
    timeout: float = 30.0,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run a keep-alive ping loop on the given channel.

    Sends periodic MsgKeepAlive pings at the specified interval and
    validates that the server echoes the correct cookie. Terminates
    gracefully when stop_event is set.

    The default interval of 90 seconds follows the Haskell node's
    default keep-alive frequency. The timeout is the maximum time
    to wait for a pong response.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for the keep-alive miniprotocol.
    interval : float
        Seconds between pings (default: 90).
    timeout : float
        Seconds to wait for each pong response (default: 30).
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.

    Raises
    ------
    asyncio.TimeoutError
        If a pong is not received within ``timeout`` seconds.
    ProtocolError
        If the server sends an unexpected message or wrong cookie.
    """
    protocol = KeepAliveProtocol()
    codec = KeepAliveCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = KeepAliveClient(runner)

    while True:
        if stop_event is not None and stop_event.is_set():
            logger.debug("Keep-alive stop requested, sending MsgDone")
            break

        cookie = random.randint(COOKIE_MIN, COOKIE_MAX)
        logger.debug("Sending keep-alive ping, cookie=%d", cookie)

        async with asyncio.timeout(timeout):
            echoed = await client.ping(cookie)

        logger.debug("Keep-alive pong received, cookie=%d", echoed)

        # Wait for the next interval, but exit early if stop is requested.
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                logger.debug("Keep-alive stop requested during wait")
                break
            except TimeoutError:
                # Normal — interval elapsed without stop, send next ping.
                continue
        else:
            await asyncio.sleep(interval)

    await client.done()


# ---------------------------------------------------------------------------
# Server-side keep-alive runner
# ---------------------------------------------------------------------------


async def run_keep_alive_server(
    channel: object,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the server side of the keep-alive miniprotocol.

    Receives MsgKeepAlive pings from the client and echoes the cookie
    back as MsgKeepAliveResponse. Runs until the client sends MsgDone
    or the stop_event is set.

    Haskell ref:
        ``Ouroboros.Network.Protocol.KeepAlive.Server``

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for keep-alive (responder direction).
    stop_event : asyncio.Event | None
        If provided, the server exits when this event is set.
    """
    protocol = KeepAliveProtocol()
    codec = KeepAliveCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    logger.debug("Keep-alive server started")

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        msg = await runner.recv_message()

        if isinstance(msg, KaMsgKeepAlive):
            # Echo the cookie back
            await runner.send_message(KaMsgKeepAliveResponse(cookie=msg.cookie))
            logger.debug("Keep-alive server: echoed cookie %d", msg.cookie)

        elif isinstance(msg, KaMsgDone):
            logger.debug("Keep-alive server: client sent Done")
            return

        else:
            logger.warning(
                "Keep-alive server: unexpected message %s",
                type(msg).__name__,
            )
            return
