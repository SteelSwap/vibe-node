"""Block-Fetch miniprotocol -- typed protocol FSM, codec, and client.

Implements the block-fetch miniprotocol as a typed state machine following
the Ouroboros typed-protocols pattern. The protocol has four states:

    BFIdle      -- Client has agency (can RequestRange or ClientDone)
    BFBusy      -- Server has agency (responds with StartBatch or NoBlocks)
    BFStreaming  -- Server has agency (sends Block... then BatchDone)
    BFDone      -- Nobody has agency (terminal)

Size limits per state (from the Ouroboros spec):
    BFIdle      -> 65535 bytes
    BFBusy      -> 65535 bytes
    BFStreaming  -> 2500000 bytes

Time limits per state:
    BFIdle      -> None (no timeout)
    BFBusy      -> 60 seconds
    BFStreaming  -> 60 seconds

Haskell reference:
    Ouroboros/Network/Protocol/BlockFetch/Type.hs (BlockFetch protocol type)
    Ouroboros/Network/Protocol/BlockFetch/Client.hs (BlockFetchClient)
    Ouroboros/Network/Protocol/BlockFetch/Codec.hs  (codecBlockFetch)

Spec reference:
    Ouroboros network spec, Section 3.3 "Block Fetch Mini-Protocol"
"""

from __future__ import annotations

import asyncio
import enum
import logging
from typing import Callable, Awaitable

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
    Point,
    Origin,
    ORIGIN,
    PointOrOrigin,
)
from vibe.cardano.network.blockfetch import (
    MsgRequestRange,
    MsgClientDone,
    MsgStartBatch,
    MsgNoBlocks,
    MsgBlock,
    MsgBatchDone,
    encode_request_range,
    encode_client_done,
    encode_start_batch,
    encode_no_blocks,
    encode_block,
    encode_batch_done,
    decode_server_message,
    decode_client_message,
)

__all__ = [
    "BlockFetchState",
    "BlockFetchProtocol",
    "BlockFetchCodec",
    "BlockFetchClient",
    "run_block_fetch",
    "run_block_fetch_continuous",
    "run_block_fetch_server",
    "BlockProvider",
    # Re-export message wrappers for convenience
    "BfMsgRequestRange",
    "BfMsgClientDone",
    "BfMsgStartBatch",
    "BfMsgNoBlocks",
    "BfMsgBlock",
    "BfMsgBatchDone",
    # Size and time limits
    "BLOCK_FETCH_SIZE_LIMITS",
    "BLOCK_FETCH_TIME_LIMITS",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol states
# ---------------------------------------------------------------------------


class BlockFetchState(enum.Enum):
    """States of the block-fetch miniprotocol state machine.

    Haskell reference: BlockFetch type, with constructors
        BFIdle, BFBusy, BFStreaming, BFDone.
    """

    BFIdle = "bf_idle"
    BFBusy = "bf_busy"
    BFStreaming = "bf_streaming"
    BFDone = "bf_done"


# ---------------------------------------------------------------------------
# Size and time limits (from the Ouroboros spec)
# ---------------------------------------------------------------------------

#: Maximum message size in bytes per protocol state.
BLOCK_FETCH_SIZE_LIMITS: dict[BlockFetchState, int] = {
    BlockFetchState.BFIdle: 65535,
    BlockFetchState.BFBusy: 65535,
    BlockFetchState.BFStreaming: 2500000,
}

#: Timeout in seconds per protocol state. None means no timeout.
BLOCK_FETCH_TIME_LIMITS: dict[BlockFetchState, float | None] = {
    BlockFetchState.BFIdle: None,
    BlockFetchState.BFBusy: 60.0,
    BlockFetchState.BFStreaming: 60.0,
}


# ---------------------------------------------------------------------------
# Typed messages (Message wrappers with state transitions)
# ---------------------------------------------------------------------------


class BfMsgRequestRange(Message[BlockFetchState]):
    """Client -> Server: request blocks in range.

    Transition: BFIdle -> BFBusy
    """

    __slots__ = ("inner",)

    def __init__(self, point_from: PointOrOrigin, point_to: PointOrOrigin) -> None:
        super().__init__(
            from_state=BlockFetchState.BFIdle,
            to_state=BlockFetchState.BFBusy,
        )
        self.inner = MsgRequestRange(point_from=point_from, point_to=point_to)

    @property
    def point_from(self) -> PointOrOrigin:
        return self.inner.point_from

    @property
    def point_to(self) -> PointOrOrigin:
        return self.inner.point_to


class BfMsgClientDone(Message[BlockFetchState]):
    """Client -> Server: terminate the protocol.

    Transition: BFIdle -> BFDone
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=BlockFetchState.BFIdle,
            to_state=BlockFetchState.BFDone,
        )
        self.inner = MsgClientDone()


class BfMsgStartBatch(Message[BlockFetchState]):
    """Server -> Client: server will stream blocks.

    Transition: BFBusy -> BFStreaming
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=BlockFetchState.BFBusy,
            to_state=BlockFetchState.BFStreaming,
        )
        self.inner = MsgStartBatch()


class BfMsgNoBlocks(Message[BlockFetchState]):
    """Server -> Client: no blocks in the requested range.

    Transition: BFBusy -> BFIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=BlockFetchState.BFBusy,
            to_state=BlockFetchState.BFIdle,
        )
        self.inner = MsgNoBlocks()


class BfMsgBlock(Message[BlockFetchState]):
    """Server -> Client: a single block in the batch.

    Transition: BFStreaming -> BFStreaming (self-loop)
    """

    __slots__ = ("inner",)

    def __init__(self, block_cbor: bytes) -> None:
        super().__init__(
            from_state=BlockFetchState.BFStreaming,
            to_state=BlockFetchState.BFStreaming,
        )
        self.inner = MsgBlock(block_cbor=block_cbor)

    @property
    def block_cbor(self) -> bytes:
        return self.inner.block_cbor


class BfMsgBatchDone(Message[BlockFetchState]):
    """Server -> Client: all blocks in the batch have been sent.

    Transition: BFStreaming -> BFIdle
    """

    __slots__ = ("inner",)

    def __init__(self) -> None:
        super().__init__(
            from_state=BlockFetchState.BFStreaming,
            to_state=BlockFetchState.BFIdle,
        )
        self.inner = MsgBatchDone()


# ---------------------------------------------------------------------------
# Protocol definition
# ---------------------------------------------------------------------------

# Pre-computed frozen sets for valid_messages.
_IDLE_MESSAGES: frozenset[type[Message[BlockFetchState]]] = frozenset(
    {BfMsgRequestRange, BfMsgClientDone}
)
_BUSY_MESSAGES: frozenset[type[Message[BlockFetchState]]] = frozenset(
    {BfMsgStartBatch, BfMsgNoBlocks}
)
_STREAMING_MESSAGES: frozenset[type[Message[BlockFetchState]]] = frozenset(
    {BfMsgBlock, BfMsgBatchDone}
)
_DONE_MESSAGES: frozenset[type[Message[BlockFetchState]]] = frozenset()


class BlockFetchProtocol(Protocol[BlockFetchState]):
    """Block-fetch miniprotocol state machine definition.

    Agency map:
        BFIdle      -> Client (Initiator sends)
        BFBusy      -> Server (Responder sends)
        BFStreaming  -> Server (Responder sends)
        BFDone      -> Nobody (terminal)

    Haskell reference:
        instance Protocol (BlockFetch block point) where
            type ClientHasAgency st = st ~ 'BFIdle
            type ServerHasAgency st = ...  (BFBusy or BFStreaming)
            type NobodyHasAgency st = st ~ 'BFDone
    """

    _AGENCY_MAP = {
        BlockFetchState.BFIdle: Agency.Client,
        BlockFetchState.BFBusy: Agency.Server,
        BlockFetchState.BFStreaming: Agency.Server,
        BlockFetchState.BFDone: Agency.Nobody,
    }

    _VALID_MESSAGES = {
        BlockFetchState.BFIdle: _IDLE_MESSAGES,
        BlockFetchState.BFBusy: _BUSY_MESSAGES,
        BlockFetchState.BFStreaming: _STREAMING_MESSAGES,
        BlockFetchState.BFDone: _DONE_MESSAGES,
    }

    def initial_state(self) -> BlockFetchState:
        return BlockFetchState.BFIdle

    def agency(self, state: BlockFetchState) -> Agency:
        try:
            return self._AGENCY_MAP[state]
        except KeyError:
            raise ProtocolError(f"Unknown block-fetch state: {state!r}")

    def valid_messages(
        self, state: BlockFetchState
    ) -> frozenset[type[Message[BlockFetchState]]]:
        try:
            return self._VALID_MESSAGES[state]
        except KeyError:
            raise ProtocolError(f"Unknown block-fetch state: {state!r}")


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


class BlockFetchCodec:
    """CBOR codec for block-fetch miniprotocol messages.

    Wraps the encode/decode functions from blockfetch.py, translating
    between typed Message wrappers (BfMsg*) and raw CBOR bytes.

    Implements the Codec protocol (structural typing).
    """

    def encode(self, message: Message[BlockFetchState]) -> bytes:
        """Encode a typed block-fetch message to CBOR bytes."""
        if isinstance(message, BfMsgRequestRange):
            return encode_request_range(message.point_from, message.point_to)
        elif isinstance(message, BfMsgClientDone):
            return encode_client_done()
        elif isinstance(message, BfMsgStartBatch):
            return encode_start_batch()
        elif isinstance(message, BfMsgNoBlocks):
            return encode_no_blocks()
        elif isinstance(message, BfMsgBlock):
            return encode_block(message.block_cbor)
        elif isinstance(message, BfMsgBatchDone):
            return encode_batch_done()
        else:
            raise CodecError(
                f"Unknown block-fetch message type: {type(message).__name__}"
            )

    def decode(self, data: bytes) -> Message[BlockFetchState]:
        """Decode CBOR bytes into a typed block-fetch message.

        Tries server-side decode first, then client-side.
        """
        try:
            return self._decode_server(data)
        except ValueError:
            pass
        try:
            return self._decode_client(data)
        except ValueError:
            pass
        raise CodecError(f"Failed to decode block-fetch message ({len(data)} bytes)")

    def _decode_server(self, data: bytes) -> Message[BlockFetchState]:
        """Decode a server-to-client message."""
        msg = decode_server_message(data)

        if isinstance(msg, MsgStartBatch):
            return BfMsgStartBatch()
        elif isinstance(msg, MsgNoBlocks):
            return BfMsgNoBlocks()
        elif isinstance(msg, MsgBlock):
            return BfMsgBlock(block_cbor=msg.block_cbor)
        elif isinstance(msg, MsgBatchDone):
            return BfMsgBatchDone()
        else:
            raise ValueError(f"Unexpected server message: {type(msg).__name__}")

    def _decode_client(self, data: bytes) -> Message[BlockFetchState]:
        """Decode a client-to-server message."""
        msg = decode_client_message(data)

        if isinstance(msg, MsgRequestRange):
            return BfMsgRequestRange(
                point_from=msg.point_from, point_to=msg.point_to
            )
        elif isinstance(msg, MsgClientDone):
            return BfMsgClientDone()
        else:
            raise ValueError(f"Unexpected client message: {type(msg).__name__}")


# ---------------------------------------------------------------------------
# High-level client
# ---------------------------------------------------------------------------


class BlockFetchClient:
    """High-level block-fetch client that uses ProtocolRunner.

    Provides ergonomic async methods for requesting block ranges and
    receiving streamed blocks.

    Parameters
    ----------
    runner : ProtocolRunner[BlockFetchState]
        A protocol runner already set up with BlockFetchProtocol, codec,
        and a connected mux channel.
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: ProtocolRunner[BlockFetchState]) -> None:
        self._runner = runner

    @property
    def state(self) -> BlockFetchState:
        """Current protocol state."""
        return self._runner.state

    @property
    def is_done(self) -> bool:
        """Whether the protocol has terminated."""
        return self._runner.is_done

    async def request_range(
        self, point_from: PointOrOrigin, point_to: PointOrOrigin
    ) -> list[bytes] | None:
        """Request a range of blocks and return them.

        Parameters
        ----------
        point_from : PointOrOrigin
            Start of the range (inclusive).
        point_to : PointOrOrigin
            End of the range (inclusive).

        Returns
        -------
        list[bytes] | None
            List of block CBOR bytes if the server had blocks, or None
            if the server responded with MsgNoBlocks.

        Raises
        ------
        ProtocolError
            If not in BFIdle state or server sends unexpected messages.
        """
        await self._runner.send_message(
            BfMsgRequestRange(point_from, point_to)
        )
        response = await self._runner.recv_message()

        if isinstance(response, BfMsgNoBlocks):
            return None

        if not isinstance(response, BfMsgStartBatch):
            raise ProtocolError(
                f"Unexpected response to RequestRange: "
                f"{type(response).__name__}"
            )

        # Collect blocks until BatchDone
        blocks: list[bytes] = []
        while True:
            msg = await self._runner.recv_message()
            if isinstance(msg, BfMsgBlock):
                blocks.append(msg.block_cbor)
            elif isinstance(msg, BfMsgBatchDone):
                return blocks
            else:
                raise ProtocolError(
                    f"Unexpected message during streaming: "
                    f"{type(msg).__name__}"
                )

    async def done(self) -> None:
        """Send ClientDone to terminate the protocol.

        After calling this, no further messages can be sent or received.
        """
        await self._runner.send_message(BfMsgClientDone())


# ---------------------------------------------------------------------------
# High-level fetch loop
# ---------------------------------------------------------------------------

#: Type alias for block-received callback.
OnBlockReceived = Callable[[bytes], Awaitable[None]]

#: Type alias for no-blocks callback.
OnNoBlocks = Callable[[PointOrOrigin, PointOrOrigin], Awaitable[None]]


async def run_block_fetch(
    channel: object,
    ranges: list[tuple[PointOrOrigin, PointOrOrigin]],
    on_block_received: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the block-fetch protocol for a list of ranges.

    This is the main entry point for fetching blocks. It:
    1. Creates a ProtocolRunner with BlockFetchProtocol and codec.
    2. Iterates through the requested ranges.
    3. For each range, dispatches blocks to the callback.
    4. Sends ClientDone when all ranges are fetched or stop_event is set.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    ranges : list[tuple[PointOrOrigin, PointOrOrigin]]
        List of (from_point, to_point) ranges to fetch.
    on_block_received : OnBlockReceived
        Async callback invoked for each block received.
    on_no_blocks : OnNoBlocks | None
        Async callback invoked when server has no blocks for a range.
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.
    """
    protocol = BlockFetchProtocol()
    codec = BlockFetchCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = BlockFetchClient(runner)

    for point_from, point_to in ranges:
        if stop_event is not None and stop_event.is_set():
            logger.info("Block-fetch stop requested, sending ClientDone")
            break

        blocks = await client.request_range(point_from, point_to)
        if blocks is None:
            logger.debug(
                "Block-fetch: no blocks for range %s -> %s",
                point_from,
                point_to,
            )
            if on_no_blocks is not None:
                await on_no_blocks(point_from, point_to)
        else:
            for block_cbor in blocks:
                await on_block_received(block_cbor)

    await client.done()


async def run_block_fetch_continuous(
    channel: object,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run block-fetch in continuous mode — pulls ranges from a queue.

    Unlike run_block_fetch(), this keeps the protocol alive between
    ranges. The BlockFetchClient loops in BFIdle, sending RequestRange
    for each item from the queue. Only sends ClientDone on stop.

    The FSM naturally supports this: BatchDone -> BFIdle allows
    another RequestRange without recreating the runner.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    range_queue : asyncio.Queue
        Queue of (point_from, point_to) tuples to fetch.
    on_block_received : OnBlockReceived
        Async callback invoked for each block received.
    on_no_blocks : OnNoBlocks | None
        Async callback when server has no blocks for a range.
    stop_event : asyncio.Event | None
        If provided, the loop exits when this event is set.
    """
    protocol = BlockFetchProtocol()
    codec = BlockFetchCodec()
    runner = ProtocolRunner(
        role=PeerRole.Initiator,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )
    client = BlockFetchClient(runner)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            try:
                point_from, point_to = await asyncio.wait_for(
                    range_queue.get(), timeout=1.0
                )
            except TimeoutError:
                continue

            blocks = await client.request_range(point_from, point_to)
            if blocks is None:
                if on_no_blocks is not None:
                    await on_no_blocks(point_from, point_to)
            else:
                for block_cbor in blocks:
                    await on_block_received(block_cbor)
    finally:
        try:
            await client.done()
        except (ProtocolError, Exception):
            pass  # Channel may already be closed on shutdown


# ---------------------------------------------------------------------------
# Block provider interface (for the server)
# ---------------------------------------------------------------------------


class BlockProvider:
    """Interface for providing block data to the block-fetch server.

    Implementations can wrap ChainDB, an in-memory block store, or any
    other source of CBOR-encoded blocks.

    Haskell reference:
        Ouroboros.Consensus.MiniProtocol.BlockFetch.Server
    """

    async def get_blocks(
        self, point_from: PointOrOrigin, point_to: PointOrOrigin
    ) -> list[bytes] | None:
        """Get all blocks in the range [point_from, point_to] inclusive.

        Returns a list of CBOR-encoded blocks, or None if the range
        is not available (triggers NoBlocks response).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Server-side block-fetch runner
# ---------------------------------------------------------------------------


async def run_block_fetch_server(
    channel: object,
    block_provider: BlockProvider,
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the server side of the block-fetch miniprotocol.

    Receives MsgRequestRange from the client, fetches blocks from the
    provider, and streams them back with StartBatch/Block.../BatchDone
    or responds with NoBlocks if unavailable.

    Haskell ref:
        ``Ouroboros.Network.Protocol.BlockFetch.Server``

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch (responder direction).
    block_provider : BlockProvider
        Source of block data.
    stop_event : asyncio.Event | None
        If provided, the server exits when this event is set.
    """
    protocol = BlockFetchProtocol()
    codec = BlockFetchCodec()
    runner = ProtocolRunner(
        role=PeerRole.Responder,
        protocol=protocol,
        codec=codec,
        channel=channel,
    )

    logger.debug("Block-fetch server started")

    while True:
        if stop_event is not None and stop_event.is_set():
            return

        # In BFIdle, client has agency — wait for their message.
        msg = await runner.recv_message()

        if isinstance(msg, BfMsgRequestRange):
            # Fetch blocks for the requested range.
            blocks = await block_provider.get_blocks(
                msg.point_from, msg.point_to
            )

            if blocks is None or len(blocks) == 0:
                # No blocks available for this range.
                await runner.send_message(BfMsgNoBlocks())
                logger.debug(
                    "Block-fetch server: NoBlocks for range %s -> %s",
                    msg.point_from, msg.point_to,
                )
            else:
                # Stream the blocks.
                await runner.send_message(BfMsgStartBatch())
                for block_cbor in blocks:
                    await runner.send_message(BfMsgBlock(block_cbor=block_cbor))
                await runner.send_message(BfMsgBatchDone())
                logger.debug(
                    "Block-fetch server: sent %d blocks for range %s -> %s",
                    len(blocks), msg.point_from, msg.point_to,
                )

        elif isinstance(msg, BfMsgClientDone):
            logger.debug("Block-fetch server: client sent Done")
            return

        else:
            logger.warning(
                "Block-fetch server: unexpected message %s",
                type(msg).__name__,
            )
            return
