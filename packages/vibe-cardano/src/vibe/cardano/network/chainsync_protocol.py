"""Chain-Sync miniprotocol — typed protocol FSM, codec, and client.

Implements the chain-sync miniprotocol as a typed state machine following
the Ouroboros typed-protocols pattern. The protocol has four states:

    StIdle      — Client has agency (can RequestNext, FindIntersect, or Done)
    StNext      — Server has agency (will RollForward, RollBackward, or AwaitReply)
    StIntersect — Server has agency (will IntersectFound or IntersectNotFound)
    StDone      — Nobody has agency (terminal)

The Haskell spec distinguishes two sub-states within StNext:
    TokCanAwait  — server may respond with AwaitReply, RollForward, or RollBackward
    TokMustReply — server must respond with RollForward or RollBackward (no AwaitReply)

After MsgAwaitReply, the protocol transitions from StNext(CanAwait) to
StNext(MustReply). We model this with a single StNext enum value and
track the can_await / must_reply distinction at the client level, since
the wire protocol uses the same state for both and the distinction only
affects which server responses are valid.

Haskell reference:
    Ouroboros/Network/Protocol/ChainSync/Type.hs (ChainSync protocol type)
    Ouroboros/Network/Protocol/ChainSync/Client.hs (ChainSyncClient)
    Ouroboros/Network/Protocol/ChainSync/Codec.hs  (codecChainSync)

Spec reference:
    Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Callable, Awaitable, Union

from vibe.core.protocols.agency import (
    Agency,
    Message,
    Protocol,
    ProtocolError,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner
from vibe.core.protocols.agency import PeerRole

from vibe.cardano.network.chainsync import (
    MsgRequestNext,
    MsgAwaitReply,
    MsgRollForward,
    MsgRollBackward,
    MsgFindIntersect,
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgDone,
    Point,
    Origin,
    ORIGIN,
    Tip,
    PointOrOrigin,
    encode_request_next,
    encode_find_intersect,
    encode_done,
    encode_await_reply,
    encode_roll_forward,
    encode_roll_backward,
    encode_intersect_found,
    encode_intersect_not_found,
    decode_server_message,
    decode_client_message,
)

__all__ = [
    "ChainSyncState",
    "ChainSyncProtocol",
    "ChainSyncCodec",
    "ChainSyncClient",
    "ChainProvider",
    "run_chain_sync",
    "run_chain_sync_server",
    # Re-export message wrappers for convenience
    "CsMsgRequestNext",
    "CsMsgAwaitReply",
    "CsMsgRollForward",
    "CsMsgRollBackward",
    "CsMsgFindIntersect",
    "CsMsgIntersectFound",
    "CsMsgIntersectNotFound",
    "CsMsgDone",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class ChainSyncState(enum.Enum):
    """States of the chain-sync miniprotocol state machine.

    Haskell reference: ChainSync type, with constructors
        StIdle, StNext (StCanAwait | StMustReply), StIntersect, StDone.

    We collapse StNext's two sub-states into a single value here.
    The TokCanAwait/TokMustReply distinction is tracked at the client
    level since it only affects which server responses are valid, not
    the fundamental agency assignment.
    """

    StIdle = "st_idle"
    StNext = "st_next"
    StIntersect = "st_intersect"
    StDone = "st_done"


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------
# These wrap the plain dataclass messages from chainsync.py, adding
# from_state/to_state as required by the typed-protocols framework.
# The naming convention uses "Cs" prefix to avoid colliding with the
# underlying message dataclasses.


class CsMsgRequestNext(Message[ChainSyncState]):
    """Client -> Server: request next chain update.

    Transition: StIdle -> StNext
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=ChainSyncState.StIdle,
            to_state=ChainSyncState.StNext,
        )
        self.inner = MsgRequestNext()


class CsMsgAwaitReply(Message[ChainSyncState]):
    """Server -> Client: consumer is caught up, wait for new data.

    Transition: StNext -> StNext

    In the Haskell spec this transitions from StNext(TokCanAwait) to
    StNext(TokMustReply). Since we model both as StNext, this is a
    self-transition. The client tracks must_reply state internally.
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=ChainSyncState.StNext,
            to_state=ChainSyncState.StNext,
        )
        self.inner = MsgAwaitReply()


class CsMsgRollForward(Message[ChainSyncState]):
    """Server -> Client: extend chain with this header.

    Transition: StNext -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, header: bytes, tip: Tip) -> None:
        super().__init__(
            from_state=ChainSyncState.StNext,
            to_state=ChainSyncState.StIdle,
        )
        self.inner = MsgRollForward(header=header, tip=tip)

    @property
    def header(self) -> bytes:
        return self.inner.header

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class CsMsgRollBackward(Message[ChainSyncState]):
    """Server -> Client: roll back to this point.

    Transition: StNext -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, point: PointOrOrigin, tip: Tip) -> None:
        super().__init__(
            from_state=ChainSyncState.StNext,
            to_state=ChainSyncState.StIdle,
        )
        self.inner = MsgRollBackward(point=point, tip=tip)

    @property
    def point(self) -> PointOrOrigin:
        return self.inner.point

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class CsMsgFindIntersect(Message[ChainSyncState]):
    """Client -> Server: find intersection from candidate points.

    Transition: StIdle -> StIntersect
    """

    __slots__ = ("inner",)

    def __init__(self, points: list[PointOrOrigin]) -> None:
        super().__init__(
            from_state=ChainSyncState.StIdle,
            to_state=ChainSyncState.StIntersect,
        )
        self.inner = MsgFindIntersect(points=points)

    @property
    def points(self) -> list[PointOrOrigin]:
        return self.inner.points


class CsMsgIntersectFound(Message[ChainSyncState]):
    """Server -> Client: intersection found at this point.

    Transition: StIntersect -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, point: PointOrOrigin, tip: Tip) -> None:
        super().__init__(
            from_state=ChainSyncState.StIntersect,
            to_state=ChainSyncState.StIdle,
        )
        self.inner = MsgIntersectFound(point=point, tip=tip)

    @property
    def point(self) -> PointOrOrigin:
        return self.inner.point

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class CsMsgIntersectNotFound(Message[ChainSyncState]):
    """Server -> Client: no intersection found.

    Transition: StIntersect -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, tip: Tip) -> None:
        super().__init__(
            from_state=ChainSyncState.StIntersect,
            to_state=ChainSyncState.StIdle,
        )
        self.inner = MsgIntersectNotFound(tip=tip)

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class CsMsgDone(Message[ChainSyncState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=ChainSyncState.StIdle,
            to_state=ChainSyncState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages — avoids allocating every call.
_IDLE_MESSAGES: frozenset[type[Message[ChainSyncState]]] = frozenset(
    {CsMsgRequestNext, CsMsgFindIntersect, CsMsgDone}
)
_NEXT_MESSAGES: frozenset[type[Message[ChainSyncState]]] = frozenset(
    {CsMsgAwaitReply, CsMsgRollForward, CsMsgRollBackward}
)
_INTERSECT_MESSAGES: frozenset[type[Message[ChainSyncState]]] = frozenset(
    {CsMsgIntersectFound, CsMsgIntersectNotFound}
)
_DONE_MESSAGES: frozenset[type[Message[ChainSyncState]]] = frozenset()


class ChainSyncProtocol(Protocol[ChainSyncState]):
    """Chain-sync miniprotocol state machine definition.

    Agency map:
        StIdle      -> Client (Initiator sends)
        StNext      -> Server (Responder sends)
        StIntersect -> Server (Responder sends)
        StDone      -> Nobody (terminal)

    Haskell reference:
        instance Protocol (ChainSync header point tip) where
            type ClientHasAgency st = st ~ 'StIdle
            type ServerHasAgency st = ...  (StNext or StIntersect)
            type NobodyHasAgency st = st ~ 'StDone
    """

    _AGENCY_MAP = {
        ChainSyncState.StIdle: Agency.Client,
        ChainSyncState.StNext: Agency.Server,
        ChainSyncState.StIntersect: Agency.Server,
        ChainSyncState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        ChainSyncState.StIdle: _IDLE_MESSAGES,
        ChainSyncState.StNext: _NEXT_MESSAGES,
        ChainSyncState.StIntersect: _INTERSECT_MESSAGES,
        ChainSyncState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> ChainSyncState:
        return ChainSyncState.StIdle

    def agency(self, state: ChainSyncState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown chain-sync state: {state!r}")

    def valid_messages(
        self, state: ChainSyncState
    ) -> frozenset[type[Message[ChainSyncState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown chain-sync state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class ChainSyncCodec:
    """CBOR codec for chain-sync miniprotocol messages.

    Wraps the encode/decode functions from chainsync.py, translating
    between typed Message wrappers (CsMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[ChainSyncState]) -> bytes:
        """Encode a typed chain-sync message to CBOR bytes.

        Dispatches to the appropriate encode_* function based on
        the message type.
        """
        if isinstance(message, CsMsgRequestNext):
            return encode_request_next()
        elif isinstance(message, CsMsgFindIntersect):
            return encode_find_intersect(message.points)
        elif isinstance(message, CsMsgDone):
            return encode_done()
        elif isinstance(message, CsMsgAwaitReply):
            return encode_await_reply()
        elif isinstance(message, CsMsgRollForward):
            return encode_roll_forward(message.header, message.tip)
        elif isinstance(message, CsMsgRollBackward):
            return encode_roll_backward(message.point, message.tip)
        elif isinstance(message, CsMsgIntersectFound):
            return encode_intersect_found(message.point, message.tip)
        elif isinstance(message, CsMsgIntersectNotFound):
            return encode_intersect_not_found(message.tip)
        else:
            raise CodecError(
                f"Unknown chain-sync message type: {type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[ChainSyncState]:
        """Decode CBOR bytes into a typed chain-sync message.

        Tries server-side decode first, then client-side. This allows
        the codec to work for both client and server roles.
        """
        try:
            return self._decode_server(data)
        except ValueError:
            pass
        try:
            return self._decode_client(data)
        except ValueError:
            pass
        raise CodecError(f"Failed to decode chain-sync message ({len(data)} bytes)")

    def _decode_server(self, data: bytes) -> Message[ChainSyncState]:
        """Decode a server-to-client message."""
        msg = decode_server_message(data)

        if isinstance(msg, MsgAwaitReply):
            return CsMsgAwaitReply()
        elif isinstance(msg, MsgRollForward):
            return CsMsgRollForward(header=msg.header, tip=msg.tip)
        elif isinstance(msg, MsgRollBackward):
            return CsMsgRollBackward(point=msg.point, tip=msg.tip)
        elif isinstance(msg, MsgIntersectFound):
            return CsMsgIntersectFound(point=msg.point, tip=msg.tip)
        elif isinstance(msg, MsgIntersectNotFound):
            return CsMsgIntersectNotFound(tip=msg.tip)
        else:
            raise ValueError(f"Unexpected server message: {type(msg).__name__}")

    def _decode_client(self, data: bytes) -> Message[ChainSyncState]:
        """Decode a client-to-server message."""
        msg = decode_client_message(data)

        if isinstance(msg, MsgRequestNext):
            return CsMsgRequestNext()
        elif isinstance(msg, MsgFindIntersect):
            return CsMsgFindIntersect(points=msg.points)
        elif isinstance(msg, MsgDone):
            return CsMsgDone()
        else:
            raise ValueError(f"Unexpected client message: {type(msg).__name__}")


# ---------------------------------------------------------------------------
# High-level client
# ---------------------------------------------------------------------------


class ChainSyncClient:
    """High-level chain-sync client that uses ProtocolRunner.

    Provides ergonomic async methods for the three client-side actions:
    find_intersection, request_next, and done. Handles the AwaitReply
    sub-state internally, blocking until the server provides a real
    response (RollForward or RollBackward).

    Parameters
    ----------
    runner : ProtocolRunner[ChainSyncState]
        A protocol runner already set up with ChainSyncProtocol, codec,
        and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: ProtocolRunner[ChainSyncState]) -> None:
        self._runner = runner

    @property
    def state(self) -> ChainSyncState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def find_intersection(
        self, points: list[PointOrOrigin]
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Send FindIntersect and return the result.

        Parameters
        ----------
        points : list[PointOrOrigin]
            Candidate intersection points, highest slot first.

        Returns
        -------
        tuple[PointOrOrigin | None, Tip]
            The intersection point (or None if not found) and the
            server's current tip.

        Raises
        ------
        ProtocolError
            If not in StIdle state.
        """
        await self._runner.send_message(CsMsgFindIntersect(points))
        response = await self._runner.recv_message()

        if isinstance(response, CsMsgIntersectFound):
            return (response.point, response.tip)
        elif isinstance(response, CsMsgIntersectNotFound):
            return (None, response.tip)
        else:
            raise ProtocolError(
                f"Unexpected response to FindIntersect: "
                f"{type(response).__name__}"
            )

    async def request_next(
        self,
    ) -> CsMsgRollForward | CsMsgRollBackward | CsMsgAwaitReply:
        """Send RequestNext and return the server's response.

        If the server responds with AwaitReply, this returns immediately
        with the AwaitReply message. The caller can then wait and call
        recv_after_await() to get the actual roll forward/backward.

        Returns
        -------
        CsMsgRollForward | CsMsgRollBackward | CsMsgAwaitReply
            The server's response.
        """
        await self._runner.send_message(CsMsgRequestNext())
        response = await self._runner.recv_message()

        if isinstance(response, (CsMsgRollForward, CsMsgRollBackward, CsMsgAwaitReply)):
            return response
        else:
            raise ProtocolError(
                f"Unexpected response to RequestNext: "
                f"{type(response).__name__}"
            )

    async def recv_after_await(self) -> CsMsgRollForward | CsMsgRollBackward:
        """Receive the server's response after an AwaitReply.

        After AwaitReply, the protocol is in StNext(MustReply) — the
        server MUST send RollForward or RollBackward. No further
        AwaitReply is permitted.

        Returns
        -------
        CsMsgRollForward | CsMsgRollBackward
            The server's response with chain data.

        Raises
        ------
        ProtocolError
            If the server sends an unexpected message (including another
            AwaitReply, which violates the MustReply invariant).
        """
        response = await self._runner.recv_message()

        if isinstance(response, (CsMsgRollForward, CsMsgRollBackward)):
            return response
        elif isinstance(response, CsMsgAwaitReply):
            raise ProtocolError(
                "Server sent AwaitReply after AwaitReply — violates "
                "TokMustReply invariant. After AwaitReply, the server "
                "must respond with RollForward or RollBackward."
            )
        else:
            raise ProtocolError(
                f"Unexpected message after AwaitReply: "
                f"{type(response).__name__}"
            )

    async def done(self) -> None:
        """Send Done to terminate the protocol.

        After calling this, no further messages can be sent or received.
        """
        await self._runner.send_message(CsMsgDone())


# ---------------------------------------------------------------------------
# High-level sync loop
# ---------------------------------------------------------------------------

#: Type alias for roll-forward callback.
OnRollForward = Callable[[bytes, Tip], Awaitable[None]]

#: Type alias for roll-backward callback.
OnRollBackward = Callable[[PointOrOrigin, Tip], Awaitable[None]]


async def run_chain_sync(
    channel: object,
    known_points: list[PointOrOrigin],
    on_roll_forward: OnRollForward,
    on_roll_backward: OnRollBackward,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the chain-sync protocol loop.

    This is the main entry point for syncing the chain. It:
    1. Creates a ProtocolRunner with ChainSyncProtocol and codec.
    2. Finds the intersection from known_points.
    3. Loops: request_next, dispatch to callbacks.
    4. Handles AwaitReply (waits for server to produce new block).
    5. Stops when stop_event is set or the channel closes.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for chain-sync.
    known_points : list[PointOrOrigin]
        Points to find intersection from (highest slot first).
        If empty, Origin will be used.
    on_roll_forward : OnRollForward
        Async callback invoked on each roll-forward with (header, tip).
    on_roll_backward : OnRollBackward
        Async callback invoked on each roll-backward with (point, tip).
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.

    Raises
    ------
    ProtocolError
        If intersection is not found (no common point with the server).
    """
    protocol = ChainSyncProtocol()
    codec = ChainSyncCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = ChainSyncClient(runner)

    # Step 1: Find intersection
    if not known_points:
        known_points = [ORIGIN]

    intersection, tip = await client.find_intersection(known_points)
    if intersection is None:
        raise ProtocolError(
            "No intersection found with the server. The consumer's "
            "known points do not overlap with the producer's chain."
        )

    logger.info(
        "Chain-sync intersection found: %s (server tip: block %d)",
        intersection,
        tip.block_number,
    )

    # Step 2: Sync loop
    while True:
        # Check stop condition
        if stop_event is not None and stop_event.is_set():
            logger.info("Chain-sync stop requested, sending Done")
            await client.done()
            return

        response = await client.request_next()

        if isinstance(response, CsMsgRollForward):
            await on_roll_forward(response.header, response.tip)

        elif isinstance(response, CsMsgRollBackward):
            await on_roll_backward(response.point, response.tip)

        elif isinstance(response, CsMsgAwaitReply):
            logger.debug("Chain-sync: at tip, awaiting new block")
            # Server said "nothing new" — wait for actual data.
            # In StNext(MustReply) now, server MUST send roll fwd/bwd.
            response = await client.recv_after_await()

            if isinstance(response, CsMsgRollForward):
                await on_roll_forward(response.header, response.tip)
            elif isinstance(response, CsMsgRollBackward):
                await on_roll_backward(response.point, response.tip)


# ---------------------------------------------------------------------------
# Chain provider interface (for the server)
# ---------------------------------------------------------------------------


class ChainProvider:
    """Interface for providing chain data to the chain-sync server.

    The server calls these methods to answer client requests. Implementations
    can wrap ChainDB, an in-memory chain, or any other block source.

    Haskell reference:
        Ouroboros.Consensus.MiniProtocol.ChainSync.Server (chainSyncServerForFollower)
        The Haskell server uses a "follower" that tracks each client's read pointer.
    """

    async def get_tip(self) -> Tip:
        """Return the current chain tip."""
        raise NotImplementedError

    async def find_intersect(
        self, points: list[PointOrOrigin]
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find the best intersection point from the client's known points.

        Returns (intersection_point, tip) where intersection_point is None
        if no common point exists.
        """
        raise NotImplementedError

    async def next_block(
        self, client_point: PointOrOrigin
    ) -> tuple[str, bytes | None, PointOrOrigin | None, Tip]:
        """Get the next update after the client's current position.

        Returns a tuple of (action, header, point, tip) where action is:
        - "roll_forward": header and tip are set, point is the new position
        - "roll_backward": point and tip are set (rollback target)
        - "await": client is at tip, no new data

        The server should block when "await" would be returned, until a
        new block arrives or stop is requested.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# N2N chain-sync server
# ---------------------------------------------------------------------------


async def run_chain_sync_server(
    channel: object,
    chain_provider: ChainProvider,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the server side of the N2N chain-sync protocol.

    Responds to client MsgFindIntersect and MsgRequestNext messages by
    querying the chain_provider for block data.

    Haskell reference:
        Ouroboros/Network/Protocol/ChainSync/Server.hs (chainSyncServerPeer)

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for chain-sync (responder direction).
    chain_provider : ChainProvider
        Source of chain data (blocks, tip, intersection).
    stop_event : asyncio.Event | None
        If provided, the server exits when this event is set.
    """
    protocol = ChainSyncProtocol()
    codec = ChainSyncCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    client_point: PointOrOrigin = ORIGIN

    logger.info("Chain-sync server started")

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        # In StIdle, the client has agency — wait for their message.
        msg = await runner.recv_message()

        if isinstance(msg, CsMsgFindIntersect):
            # Client wants to find intersection.
            intersect, tip = await chain_provider.find_intersect(msg.points)
            if intersect is not None:
                client_point = intersect
                await runner.send_message(
                    CsMsgIntersectFound(point=intersect, tip=tip)
                )
            else:
                await runner.send_message(CsMsgIntersectNotFound(tip=tip))

        elif isinstance(msg, CsMsgRequestNext):
            # Client wants the next block.
            action, header, point, tip = await chain_provider.next_block(
                client_point
            )

            if action == "roll_forward" and header is not None:
                client_point = point  # type: ignore[assignment]
                await runner.send_message(
                    CsMsgRollForward(header=header, tip=tip)
                )
            elif action == "roll_backward" and point is not None:
                client_point = point
                await runner.send_message(
                    CsMsgRollBackward(point=point, tip=tip)
                )
            elif action == "await":
                # Send AwaitReply, then block until new data.
                await runner.send_message(CsMsgAwaitReply())
                # Now in StNext(MustReply) — must send roll_forward or
                # roll_backward next. Wait for chain_provider to have data.
                while True:
                    if stop_event is not None and stop_event.is_set():
                        return
                    action2, header2, point2, tip2 = (
                        await chain_provider.next_block(client_point)
                    )
                    if action2 == "roll_forward" and header2 is not None:
                        client_point = point2  # type: ignore[assignment]
                        await runner.send_message(
                            CsMsgRollForward(header=header2, tip=tip2)
                        )
                        break
                    elif action2 == "roll_backward" and point2 is not None:
                        client_point = point2
                        await runner.send_message(
                            CsMsgRollBackward(point=point2, tip=tip2)
                        )
                        break
                    # Still no data — brief sleep to avoid busy-wait.
                    await asyncio.sleep(0.1)

        elif isinstance(msg, CsMsgDone):
            logger.info("Chain-sync server: client sent Done")
            return

        else:
            logger.warning(
                "Chain-sync server: unexpected message %s",
                type(msg).__name__,
            )
