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
import time
from collections.abc import Awaitable, Callable

from vibe.cardano.network.blockfetch import (
    MsgBatchDone,
    MsgBlock,
    MsgClientDone,
    MsgNoBlocks,
    MsgRequestRange,
    MsgStartBatch,
    decode_client_message,
    decode_server_message,
    encode_batch_done,
    encode_block,
    encode_client_done,
    encode_no_blocks,
    encode_request_range,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import (
    PointOrOrigin,
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
    "BlockFetchState",
    "BlockFetchProtocol",
    "BlockFetchCodec",
    "BlockFetchClient",
    "run_block_fetch",
    "run_block_fetch_continuous",
    "run_block_fetch_pipelined",
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

    def valid_messages(self, state: BlockFetchState) -> frozenset[type[Message[BlockFetchState]]]:
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
            raise CodecError(f"Unknown block-fetch message type: {type(message).__name__}")

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
            return BfMsgRequestRange(point_from=msg.point_from, point_to=msg.point_to)
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

        Returns:
        -------
        list[bytes] | None
            List of block CBOR bytes if the server had blocks, or None
            if the server responded with MsgNoBlocks.

        Raises:
        ------
        ProtocolError
            If not in BFIdle state or server sends unexpected messages.
        """
        await self._runner.send_message(BfMsgRequestRange(point_from, point_to))
        response = await self._runner.recv_message()

        if isinstance(response, BfMsgNoBlocks):
            return None

        if not isinstance(response, BfMsgStartBatch):
            raise ProtocolError(f"Unexpected response to RequestRange: {type(response).__name__}")

        # Collect blocks until BatchDone
        blocks: list[bytes] = []
        while True:
            msg = await self._runner.recv_message()
            if isinstance(msg, BfMsgBlock):
                blocks.append(msg.block_cbor)
            elif isinstance(msg, BfMsgBatchDone):
                return blocks
            else:
                raise ProtocolError(f"Unexpected message during streaming: {type(msg).__name__}")

    async def request_range_streaming(
        self,
        point_from: PointOrOrigin,
        point_to: PointOrOrigin,
        on_block: OnBlockReceived,
    ) -> bool:
        """Request a range and stream blocks via callback as they arrive.

        Instead of collecting all blocks into a list, each block is
        dispatched to the callback immediately upon receipt. This avoids
        buffering an entire batch in memory and lets downstream processing
        (decode, validate, store) overlap with network I/O.

        Haskell ref: blockFetchClient in BlockFetch.Client streams blocks
        through a ChainDB.AddBlockPromise rather than collecting them.

        Returns True if blocks were received, False if server sent NoBlocks.
        """
        await self._runner.send_message(BfMsgRequestRange(point_from, point_to))
        response = await self._runner.recv_message()

        if isinstance(response, BfMsgNoBlocks):
            return False

        if not isinstance(response, BfMsgStartBatch):
            raise ProtocolError(f"Unexpected response to RequestRange: {type(response).__name__}")

        while True:
            msg = await self._runner.recv_message()
            if isinstance(msg, BfMsgBlock):
                await on_block(msg.block_cbor)
            elif isinstance(msg, BfMsgBatchDone):
                return True
            else:
                raise ProtocolError(f"Unexpected message during streaming: {type(msg).__name__}")

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
            logger.debug("Block-fetch stop requested, sending ClientDone")
            break

        got_blocks = await client.request_range_streaming(
            point_from, point_to, on_block_received
        )
        if not got_blocks:
            logger.debug(
                "Block-fetch: no blocks for range %s -> %s",
                point_from,
                point_to,
            )
            if on_no_blocks is not None:
                await on_no_blocks(point_from, point_to)

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
                    range_queue.get(), timeout=0.5
                )
            except TimeoutError:
                continue

            got_blocks = await client.request_range_streaming(
                point_from, point_to, on_block_received
            )
            if not got_blocks:
                if on_no_blocks is not None:
                    await on_no_blocks(point_from, point_to)
    finally:
        try:
            await client.done()
        except (ProtocolError, Exception):
            pass  # Channel may already be closed on shutdown


async def run_block_fetch_pipelined(
    channel: object,
    range_queue: asyncio.Queue,
    on_block_received: OnBlockReceived | None = None,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    max_in_flight: int = 3,
    block_queue_size: int = 200,
    block_queue: asyncio.Queue | None = None,
    on_range_sent: Callable[[tuple], None] | None = None,
    on_range_complete: Callable[[tuple], None] | None = None,
) -> None:
    """Run block-fetch with pipelined range requests and decoupled processing.

    Three concurrent tasks:
    - Sender: pulls ranges from range_queue, sends MsgRequestRange on the
      raw channel, tracks in-flight batches (capped at max_in_flight).
    - Receiver: reads raw bytes from channel, decodes CBOR responses,
      puts block bytes onto block_queue.
    - Processor: pulls from block_queue, calls on_block_received.
      Skipped when an external block_queue is provided.

    Bypasses ProtocolRunner for raw channel access (same pattern as
    pipelined chain-sync). The sender pipelines multiple range requests
    so the next batch's RTT overlaps with the current batch's streaming.

    Haskell ref: blockFetchClient uses YieldPipelined / Collect to overlap
    range requests. addBlockRunner processes blocks on a background thread.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    range_queue : asyncio.Queue
        Queue of (point_from, point_to) tuples to fetch.
    on_block_received : OnBlockReceived | None
        Async callback invoked for each block received. Not needed when
        block_queue is provided externally.
    on_no_blocks : OnNoBlocks | None
        Async callback when server has no blocks for a range.
    stop_event : asyncio.Event | None
        If provided, all tasks exit when this event is set.
    max_in_flight : int
        Maximum concurrent range requests on the wire.
    block_queue_size : int
        Bounded size of the block processing queue (ignored if block_queue provided).
    block_queue : asyncio.Queue | None
        External block queue. When provided, blocks go here and no
        internal processor task runs.
    on_range_sent : Callable | None
        Called with (point_from, point_to) after a range request is sent.
    on_range_complete : Callable | None
        Called with (point_from, point_to) when a BatchDone is received.
    """
    import io as _io

    import cbor2pure as _cbor2

    from vibe.cardano.network.blockfetch import (
        MSG_BATCH_DONE,
        MSG_BLOCK,
        MSG_NO_BLOCKS,
        MSG_START_BATCH,
        encode_client_done,
        encode_request_range,
    )

    _external_queue = block_queue is not None
    if block_queue is None:
        block_queue = asyncio.Queue(maxsize=block_queue_size)
    in_flight = 0
    can_send = asyncio.Event()
    can_send.set()  # Start open — sender can send immediately
    _recv_buf = b""
    _range_fifo: list[tuple] = []  # FIFO of sent ranges for matching BatchDone/NoBlocks

    async def _sender() -> None:
        """Pull ranges from range_queue and send MsgRequestRange."""
        nonlocal in_flight
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return

                # Wait until we have capacity
                if in_flight >= max_in_flight:
                    can_send.clear()
                    await can_send.wait()
                    continue

                try:
                    point_from, point_to = await asyncio.wait_for(
                        range_queue.get(), timeout=0.5
                    )
                except TimeoutError:
                    continue

                current_range = (point_from, point_to)
                data = encode_request_range(point_from, point_to)
                await channel.send(data)
                in_flight += 1
                _range_fifo.append(current_range)
                if on_range_sent is not None:
                    on_range_sent(current_range)
        except asyncio.CancelledError:
            return

    async def _receiver() -> None:
        """Read responses from channel and dispatch to block_queue."""
        nonlocal in_flight, _recv_buf

        while True:
            if stop_event is not None and stop_event.is_set():
                return

            # Read from channel with timeout so we can check stop_event
            if _recv_buf:
                raw = _recv_buf
                _recv_buf = b""
            else:
                try:
                    raw = await asyncio.wait_for(channel.recv(), timeout=0.5)
                except TimeoutError:
                    continue
                except Exception:
                    return

            # Accumulate into a bytearray for multi-segment reassembly
            buf = bytearray(raw)

            # Decode all complete CBOR messages in this buffer
            while len(buf) > 0:
                try:
                    stream = _io.BytesIO(bytes(buf))
                    dec = _cbor2.CBORDecoder(stream)
                    msg = dec.decode()
                    consumed = stream.tell()
                except Exception:
                    # Incomplete CBOR — need more data
                    try:
                        more = await channel.recv()
                        buf.extend(more)
                    except Exception:
                        return
                    continue

                # Successfully decoded one message
                buf_snapshot = bytes(buf)  # preserve for raw byte slicing
                remainder = bytes(buf[consumed:])
                buf = bytearray()  # Clear — we'll process remainder below

                if not isinstance(msg, list) or len(msg) < 1:
                    logger.warning("block-fetch pipelined: unexpected CBOR: %s", type(msg))
                    if remainder:
                        buf = bytearray(remainder)
                    continue

                msg_id = msg[0]

                if msg_id == MSG_BLOCK:
                    # Extract block_cbor from element [1].
                    # Prefer raw byte slice over decoded object to avoid
                    # re-encoding (Haskell ref: BlockFetchSerialised).
                    block_data = msg[1] if len(msg) > 1 else b""
                    if isinstance(block_data, bytes):
                        block_cbor = block_data
                    elif isinstance(block_data, memoryview):
                        block_cbor = bytes(block_data)
                    else:
                        # block_data was fully decoded by cbor2 into a
                        # Python object. Slice original wire bytes instead
                        # of re-encoding (which mangles indefinite-length
                        # CBOR and breaks downstream hash computation).
                        try:
                            msg_bytes = buf_snapshot[:consumed]
                            # CBOR array header: 0x82 = 2-element array
                            # Skip array header (1 byte) + msg_id element
                            _s = _io.BytesIO(msg_bytes)
                            _hdr = msg_bytes[0] & 0x1F
                            _s.seek(1 if _hdr < 24 else 2)
                            _cbor2.CBORDecoder(_s).decode()  # skip msg_id
                            block_cbor = msg_bytes[_s.tell():consumed]
                        except Exception:
                            block_cbor = _cbor2.dumps(block_data)
                    await block_queue.put(block_cbor)
                elif msg_id == MSG_START_BATCH:
                    pass  # Expected — batch is starting
                elif msg_id == MSG_BATCH_DONE:
                    completed_range = _range_fifo.pop(0) if _range_fifo else None
                    in_flight -= 1
                    can_send.set()
                    if on_range_complete is not None and completed_range is not None:
                        on_range_complete(completed_range)
                elif msg_id == MSG_NO_BLOCKS:
                    failed_range = _range_fifo.pop(0) if _range_fifo else None
                    in_flight -= 1
                    can_send.set()
                    if on_no_blocks is not None and failed_range is not None:
                        try:
                            await on_no_blocks(failed_range[0], failed_range[1])
                        except Exception:
                            pass

                # Process any remainder
                if remainder:
                    buf = bytearray(remainder)

    async def _processor() -> None:
        """Pull blocks from block_queue and run on_block_received."""
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    # Drain remaining blocks before exiting
                    while not block_queue.empty():
                        try:
                            block_cbor = block_queue.get_nowait()
                            await on_block_received(block_cbor)
                        except asyncio.QueueEmpty:
                            break
                    return

                try:
                    block_cbor = await asyncio.wait_for(
                        block_queue.get(), timeout=0.5
                    )
                except TimeoutError:
                    continue
                await on_block_received(block_cbor)
        except asyncio.CancelledError:
            # Drain remaining
            while not block_queue.empty():
                try:
                    block_cbor = block_queue.get_nowait()
                    await on_block_received(block_cbor)
                except asyncio.QueueEmpty:
                    break

    # Launch sender and (optionally) processor as tasks; receiver runs in main coroutine
    sender_task = asyncio.create_task(_sender())
    processor_task = None
    if not _external_queue:
        processor_task = asyncio.create_task(_processor())

    try:
        await _receiver()
    except Exception as exc:
        logger.warning("block-fetch pipelined receiver error: %s", exc)
        if stop_event is not None:
            stop_event.set()
    finally:
        # Shutdown: cancel sender, let processor drain, then cancel
        sender_task.cancel()
        try:
            await sender_task
        except asyncio.CancelledError:
            pass

        # Send ClientDone if channel is still open
        try:
            await channel.send(encode_client_done())
        except Exception:
            pass

        # Signal processor to drain and exit (only if we created one)
        if processor_task is not None:
            if stop_event is not None:
                stop_event.set()
            try:
                await asyncio.wait_for(processor_task, timeout=0.5)
            except (TimeoutError, asyncio.CancelledError):
                processor_task.cancel()
                try:
                    await processor_task
                except asyncio.CancelledError:
                    pass


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
            t_recv = time.monotonic()
            blocks = await block_provider.get_blocks(msg.point_from, msg.point_to)
            t_lookup = time.monotonic()

            if blocks is None or len(blocks) == 0:
                # No blocks available for this range.
                await runner.send_message(BfMsgNoBlocks())
                logger.info(
                    "BlockFetch.Server.NoBlocks: range=%s..%s",
                    msg.point_from, msg.point_to,
                )
            else:
                # Stream the blocks.
                await runner.send_message(BfMsgStartBatch())
                for block_cbor in blocks:
                    await runner.send_message(BfMsgBlock(block_cbor=block_cbor))
                await runner.send_message(BfMsgBatchDone())
                t_sent = time.monotonic()
                logger.info(
                    "BlockFetch.Server.Timing: lookup=%.1fms send=%.1fms total=%.1fms blocks=%d",
                    (t_lookup - t_recv) * 1000,
                    (t_sent - t_lookup) * 1000,
                    (t_sent - t_recv) * 1000,
                    len(blocks),
                )
                logger.info(
                    "BlockFetch.Server.SendBlock: range=%s..%s blocks=%d",
                    msg.point_from, msg.point_to, len(blocks),
                )
                logger.debug(
                    "Block-fetch server: sent %d blocks for range %s -> %s",
                    len(blocks),
                    msg.point_from,
                    msg.point_to,
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
