"""Local Chain-Sync (N2C) miniprotocol — typed protocol FSM, codec, and server.

Implements the node-to-client chain-sync miniprotocol as a typed state machine.
The protocol states and transitions are identical to N2N chain-sync:

    StIdle      — Client has agency (can RequestNext, FindIntersect, or Done)
    StNext      — Server has agency (will RollForward, RollBackward, or AwaitReply)
    StIntersect — Server has agency (will IntersectFound or IntersectNotFound)
    StDone      — Nobody has agency (terminal)

The critical difference from N2N is:
- **MsgRollForward carries a full block, not just a header.**
- **We implement the SERVER side** (the node serves local clients).
- The protocol ID is 5 (N2C) instead of 2 (N2N).

The server implements a "follower" pattern: it tracks each client's read
pointer into the chain and notifies when new blocks arrive.

Haskell reference:
    Ouroboros/Network/Protocol/ChainSync/Type.hs (protocol type — same for N2N/N2C)
    Ouroboros/Network/Protocol/ChainSync/Server.hs (ChainSyncServer)
    Ouroboros/Network/Protocol/ChainSync/Codec.hs  (codecChainSync)

Spec reference:
    Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
    The N2C variant is the same protocol with different type parameters.
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Protocol as TypingProtocol, runtime_checkable, Union

from vibe.core.protocols.agency import (
    Agency,
    Message,
    Protocol,
    ProtocolError,
    PeerRole,
)
from vibe.core.protocols.codec import Codec, CodecError
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.chainsync import (
    MsgRequestNext,
    MsgAwaitReply,
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
    encode_roll_backward,
    encode_intersect_found,
    encode_intersect_not_found,
    decode_client_message,
)
from vibe.cardano.network.local_chainsync import (
    N2CMsgRollForward,
    encode_n2c_roll_forward,
    decode_n2c_server_message,
)

__all__ = [
    "LocalChainSyncState",
    "LocalChainSyncProtocol",
    "LocalChainSyncCodec",
    "LocalChainSyncServer",
    "ChainDB",
    # Re-export typed messages
    "LcsMsgRequestNext",
    "LcsMsgAwaitReply",
    "LcsMsgRollForward",
    "LcsMsgRollBackward",
    "LcsMsgFindIntersect",
    "LcsMsgIntersectFound",
    "LcsMsgIntersectNotFound",
    "LcsMsgDone",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states (identical to N2N chain-sync)
# ---------------------------------------------------------------------------


class LocalChainSyncState(enum.Enum):
    """States of the local chain-sync miniprotocol state machine.

    These are identical to the N2N chain-sync states. The protocol
    structure is the same — only the payload semantics differ.
    """

    StIdle = "st_idle"
    StNext = "st_next"
    StIntersect = "st_intersect"
    StDone = "st_done"


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------
# Prefix "Lcs" (Local Chain Sync) to distinguish from N2N "Cs" prefix.


class LcsMsgRequestNext(Message[LocalChainSyncState]):
    """Client -> Server: request next chain update.

    Transition: StIdle -> StNext
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StIdle,
            to_state=LocalChainSyncState.StNext,
        )
        self.inner = MsgRequestNext()


class LcsMsgAwaitReply(Message[LocalChainSyncState]):
    """Server -> Client: consumer is caught up, wait for new data.

    Transition: StNext -> StNext
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StNext,
            to_state=LocalChainSyncState.StNext,
        )
        self.inner = MsgAwaitReply()


class LcsMsgRollForward(Message[LocalChainSyncState]):
    """Server -> Client: extend chain with this full block (N2C).

    Transition: StNext -> StIdle

    Unlike the N2N variant, this carries a full serialised block.
    """

    __slots__ = ("inner",)

    def __init__(self, block: bytes, tip: Tip) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StNext,
            to_state=LocalChainSyncState.StIdle,
        )
        self.inner = N2CMsgRollForward(block=block, tip=tip)

    @property
    def block(self) -> bytes:
        return self.inner.block

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class LcsMsgRollBackward(Message[LocalChainSyncState]):
    """Server -> Client: roll back to this point.

    Transition: StNext -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, point: PointOrOrigin, tip: Tip) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StNext,
            to_state=LocalChainSyncState.StIdle,
        )
        self.inner = MsgRollBackward(point=point, tip=tip)

    @property
    def point(self) -> PointOrOrigin:
        return self.inner.point

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class LcsMsgFindIntersect(Message[LocalChainSyncState]):
    """Client -> Server: find intersection from candidate points.

    Transition: StIdle -> StIntersect
    """

    __slots__ = ("inner",)

    def __init__(self, points: list[PointOrOrigin]) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StIdle,
            to_state=LocalChainSyncState.StIntersect,
        )
        self.inner = MsgFindIntersect(points=points)

    @property
    def points(self) -> list[PointOrOrigin]:
        return self.inner.points


class LcsMsgIntersectFound(Message[LocalChainSyncState]):
    """Server -> Client: intersection found at this point.

    Transition: StIntersect -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, point: PointOrOrigin, tip: Tip) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StIntersect,
            to_state=LocalChainSyncState.StIdle,
        )
        self.inner = MsgIntersectFound(point=point, tip=tip)

    @property
    def point(self) -> PointOrOrigin:
        return self.inner.point

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class LcsMsgIntersectNotFound(Message[LocalChainSyncState]):
    """Server -> Client: no intersection found.

    Transition: StIntersect -> StIdle
    """

    __slots__ = ("inner",)

    def __init__(self, tip: Tip) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StIntersect,
            to_state=LocalChainSyncState.StIdle,
        )
        self.inner = MsgIntersectNotFound(tip=tip)

    @property
    def tip(self) -> Tip:
        return self.inner.tip


class LcsMsgDone(Message[LocalChainSyncState]):
    """Client -> Server: terminate the protocol.

    Transition: StIdle -> StDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=LocalChainSyncState.StIdle,
            to_state=LocalChainSyncState.StDone,
        )
        self.inner = MsgDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

_IDLE_MESSAGES: frozenset[type[Message[LocalChainSyncState]]] = frozenset(
    {LcsMsgRequestNext, LcsMsgFindIntersect, LcsMsgDone}
)
_NEXT_MESSAGES: frozenset[type[Message[LocalChainSyncState]]] = frozenset(
    {LcsMsgAwaitReply, LcsMsgRollForward, LcsMsgRollBackward}
)
_INTERSECT_MESSAGES: frozenset[type[Message[LocalChainSyncState]]] = frozenset(
    {LcsMsgIntersectFound, LcsMsgIntersectNotFound}
)
_DONE_MESSAGES: frozenset[type[Message[LocalChainSyncState]]] = frozenset()


class LocalChainSyncProtocol(Protocol[LocalChainSyncState]):
    """Local chain-sync (N2C) miniprotocol state machine definition.

    Agency map (identical to N2N):
        StIdle      -> Client (Initiator sends)
        StNext      -> Server (Responder sends)
        StIntersect -> Server (Responder sends)
        StDone      -> Nobody (terminal)

    The agency is the same as N2N because the protocol structure is
    identical. The difference is only in the payload types.
    """

    _AGENCY_MAP = {
        LocalChainSyncState.StIdle: Agency.Client,
        LocalChainSyncState.StNext: Agency.Server,
        LocalChainSyncState.StIntersect: Agency.Server,
        LocalChainSyncState.StDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        LocalChainSyncState.StIdle: _IDLE_MESSAGES,
        LocalChainSyncState.StNext: _NEXT_MESSAGES,
        LocalChainSyncState.StIntersect: _INTERSECT_MESSAGES,
        LocalChainSyncState.StDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> LocalChainSyncState:
        return LocalChainSyncState.StIdle

    def agency(self, state: LocalChainSyncState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown local chain-sync state: {state!r}")

    def valid_messages(
        self, state: LocalChainSyncState
    ) -> frozenset[type[Message[LocalChainSyncState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown local chain-sync state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class LocalChainSyncCodec:
    """CBOR codec for local chain-sync (N2C) miniprotocol messages.

    The wire format is identical to N2N chain-sync. The only difference
    is that MsgRollForward carries a full block (decoded as N2CMsgRollForward)
    rather than a header.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[LocalChainSyncState]) -> bytes:
        """Encode a typed local chain-sync message to CBOR bytes."""
        if isinstance(message, LcsMsgRequestNext):
            return encode_request_next()
        elif isinstance(message, LcsMsgFindIntersect):
            return encode_find_intersect(message.points)
        elif isinstance(message, LcsMsgDone):
            return encode_done()
        elif isinstance(message, LcsMsgAwaitReply):
            return encode_await_reply()
        elif isinstance(message, LcsMsgRollForward):
            return encode_n2c_roll_forward(message.block, message.tip)
        elif isinstance(message, LcsMsgRollBackward):
            return encode_roll_backward(message.point, message.tip)
        elif isinstance(message, LcsMsgIntersectFound):
            return encode_intersect_found(message.point, message.tip)
        elif isinstance(message, LcsMsgIntersectNotFound):
            return encode_intersect_not_found(message.tip)
        else:
            raise CodecError(
                f"Unknown local chain-sync message type: {type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[LocalChainSyncState]:
        """Decode CBOR bytes into a typed local chain-sync message.

        Tries server-side decode first (N2C variant), then client-side.
        """
        try:
            return self._decode_server(data)
        except ValueError:
            pass
        try:
            return self._decode_client(data)
        except ValueError:
            pass
        raise CodecError(
            f"Failed to decode local chain-sync message ({len(data)} bytes)"
        )

    def _decode_server(self, data: bytes) -> Message[LocalChainSyncState]:
        """Decode a server-to-client message (N2C variant)."""
        msg = decode_n2c_server_message(data)

        if isinstance(msg, MsgAwaitReply):
            return LcsMsgAwaitReply()
        elif isinstance(msg, N2CMsgRollForward):
            return LcsMsgRollForward(block=msg.block, tip=msg.tip)
        elif isinstance(msg, MsgRollBackward):
            return LcsMsgRollBackward(point=msg.point, tip=msg.tip)
        elif isinstance(msg, MsgIntersectFound):
            return LcsMsgIntersectFound(point=msg.point, tip=msg.tip)
        elif isinstance(msg, MsgIntersectNotFound):
            return LcsMsgIntersectNotFound(tip=msg.tip)
        else:
            raise ValueError(f"Unexpected N2C server message: {type(msg).__name__}")

    def _decode_client(self, data: bytes) -> Message[LocalChainSyncState]:
        """Decode a client-to-server message."""
        msg = decode_client_message(data)

        if isinstance(msg, MsgRequestNext):
            return LcsMsgRequestNext()
        elif isinstance(msg, MsgFindIntersect):
            return LcsMsgFindIntersect(points=msg.points)
        elif isinstance(msg, MsgDone):
            return LcsMsgDone()
        else:
            raise ValueError(f"Unexpected client message: {type(msg).__name__}")


# ---------------------------------------------------------------------------
# ChainDB interface (protocol for dependency injection)
# ---------------------------------------------------------------------------


@runtime_checkable
class ChainDB(TypingProtocol):
    """Interface for the chain database used by LocalChainSyncServer.

    This defines the minimal API the server needs from the storage layer.
    Implementations can be a real ChainDB or a mock for testing.

    The server uses a "follower" pattern: it reads blocks sequentially
    from the chain, tracking the client's position via a read pointer.

    Haskell reference:
        Ouroboros.Consensus.Storage.ChainDB.API
        - getTipPoint, getBlockAtPoint, pointOnChain, readBlockAfter
    """

    def get_tip(self) -> Tip:
        """Return the current chain tip."""
        ...

    def find_intersect(self, points: list[PointOrOrigin]) -> PointOrOrigin | None:
        """Find the best intersection from candidate points.

        Returns the first point from the list that exists on the current
        chain, or None if no intersection is found. Points are tried in
        order (highest slot first by convention).
        """
        ...

    def read_block_after(self, point: PointOrOrigin) -> tuple[bytes, Point] | None:
        """Read the next block after the given point.

        Returns (block_cbor, block_point) or None if there is no next block
        (i.e., the point is at the tip or beyond).
        """
        ...

    def read_block_at(self, point: PointOrOrigin) -> bytes | None:
        """Read the block at the given point.

        Returns the CBOR-encoded block bytes, or None if the point is not
        on the chain.
        """
        ...

    async def wait_for_new_block(self) -> None:
        """Wait until a new block is added to the chain.

        This is used when the client is caught up to the tip and the
        server needs to wait for new data. The method should return
        when a new block becomes available.
        """
        ...

    def get_fork_point(self, client_point: PointOrOrigin) -> PointOrOrigin | None:
        """If the client's point is no longer on the current chain (fork),
        return the point to roll back to.

        Returns the fork point (the last common ancestor), or None if
        the client's point is still on the chain.
        """
        ...


# ---------------------------------------------------------------------------
# Server implementation
# ---------------------------------------------------------------------------


class LocalChainSyncServer:
    """Node-to-client local chain-sync server.

    Serves full blocks to local clients (wallets, explorers, tools) over
    a Unix domain socket. Implements the server side of the chain-sync
    protocol using the follower pattern.

    The server tracks each client's read position and serves blocks
    sequentially. When the client is caught up, it sends AwaitReply
    and waits for new blocks from the ChainDB.

    Parameters
    ----------
    runner : ProtocolRunner[LocalChainSyncState]
        Protocol runner configured with LocalChainSyncProtocol and codec.
    chaindb : ChainDB
        The chain database to serve blocks from.

    Haskell reference:
        Ouroboros/Network/Protocol/ChainSync/Server.hs
        chainSyncServerPeer — drives the server-side peer.
    """

    __slots__ = ("_runner", "_chaindb", "_client_point")

    def __init__(
        self,
        runner: ProtocolRunner[LocalChainSyncState],
        chaindb: ChainDB,
    ) -> None:
        self._runner = runner
        self._chaindb = chaindb
        self._client_point: PointOrOrigin = ORIGIN

    @property
    def state(self) -> LocalChainSyncState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    @property
    def client_point(self) -> PointOrOrigin:
        """The client's current read position on the chain."""
        return self._client_point

    async def handle_find_intersect(self, points: list[PointOrOrigin]) -> None:
        """Handle a MsgFindIntersect from the client.

        Finds the best intersection point and responds with either
        IntersectFound or IntersectNotFound. Updates the client's
        read pointer on success.

        Parameters
        ----------
        points : list[PointOrOrigin]
            Client's candidate intersection points.
        """
        tip = self._chaindb.get_tip()
        intersect = self._chaindb.find_intersect(points)

        if intersect is not None:
            self._client_point = intersect
            await self._runner.send_message(
                LcsMsgIntersectFound(point=intersect, tip=tip)
            )
        else:
            await self._runner.send_message(
                LcsMsgIntersectNotFound(tip=tip)
            )

    async def handle_request_next(self) -> None:
        """Handle a MsgRequestNext from the client.

        Checks if the client's position is still on the current chain
        (handles forks via rollback), then serves the next block or
        waits for a new block if caught up.
        """
        # Check for fork — if client's point is no longer on our chain,
        # we need to roll backward to the fork point.
        fork_point = self._chaindb.get_fork_point(self._client_point)
        if fork_point is not None:
            tip = self._chaindb.get_tip()
            self._client_point = fork_point
            await self._runner.send_message(
                LcsMsgRollBackward(point=fork_point, tip=tip)
            )
            return

        # Try to read the next block after the client's position.
        result = self._chaindb.read_block_after(self._client_point)

        if result is not None:
            block_cbor, block_point = result
            tip = self._chaindb.get_tip()
            self._client_point = block_point
            await self._runner.send_message(
                LcsMsgRollForward(block=block_cbor, tip=tip)
            )
        else:
            # Client is caught up to the tip — send AwaitReply, then
            # wait for a new block and serve it.
            await self._runner.send_message(LcsMsgAwaitReply())

            # Wait for new data from the chain.
            await self._chaindb.wait_for_new_block()

            # Check for fork again after waking up.
            fork_point = self._chaindb.get_fork_point(self._client_point)
            if fork_point is not None:
                tip = self._chaindb.get_tip()
                self._client_point = fork_point
                await self._runner.send_message(
                    LcsMsgRollBackward(point=fork_point, tip=tip)
                )
                return

            # Serve the new block.
            result = self._chaindb.read_block_after(self._client_point)
            if result is not None:
                block_cbor, block_point = result
                tip = self._chaindb.get_tip()
                self._client_point = block_point
                await self._runner.send_message(
                    LcsMsgRollForward(block=block_cbor, tip=tip)
                )
            else:
                # Edge case: woke up but no new block. Send rollforward
                # with current tip. In practice this shouldn't happen if
                # wait_for_new_block is implemented correctly.
                tip = self._chaindb.get_tip()
                await self._runner.send_message(
                    LcsMsgRollBackward(point=self._client_point, tip=tip)
                )

    async def run(self) -> None:
        """Run the server loop until the client sends Done.

        Receives client messages and dispatches to the appropriate
        handler. The server loop is:

        1. Wait for client message (we're in StIdle, client has agency)
        2. Dispatch: FindIntersect -> handle_find_intersect
                     RequestNext   -> handle_request_next
                     Done          -> exit
        3. Repeat
        """
        while not self.is_done:
            msg = await self._runner.recv_message()

            if isinstance(msg, LcsMsgFindIntersect):
                await self.handle_find_intersect(msg.points)

            elif isinstance(msg, LcsMsgRequestNext):
                await self.handle_request_next()

            elif isinstance(msg, LcsMsgDone):
                logger.info("Local chain-sync client sent Done, terminating")
                return

            else:
                raise ProtocolError(
                    f"Unexpected message in StIdle: {type(msg).__name__}"
                )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def create_local_chainsync_server(
    channel: object,
    chaindb: ChainDB,
) -> LocalChainSyncServer:
    """Create a LocalChainSyncServer connected to a mux channel.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for local chain-sync.
    chaindb : ChainDB
        The chain database to serve blocks from.

    Returns
    -------
    LocalChainSyncServer
        Ready-to-run server instance.
    """
    protocol = LocalChainSyncProtocol()
    codec = LocalChainSyncCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    return LocalChainSyncServer(runner=runner, chaindb=chaindb)
