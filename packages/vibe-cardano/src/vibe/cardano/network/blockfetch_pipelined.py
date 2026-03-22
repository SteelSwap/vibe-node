"""Pipelined block-fetch client — fetch multiple block ranges concurrently.

The standard block-fetch client sends MsgRequestRange, waits for the full
batch (StartBatch, Block..., BatchDone), then sends the next request.
Each range request incurs a full round-trip before the next range can begin.

The pipelined block-fetch client sends multiple MsgRequestRange messages
without waiting, then collects block batches asynchronously. This keeps
the server busy streaming blocks for range N+1 while we're still processing
blocks from range N.

Unlike chain-sync pipelining (which pipelines individual MsgRequestNext),
block-fetch pipelining operates at the range level. Each range request
triggers a multi-message response (StartBatch, Block*, BatchDone), so
the pipeline tracks ranges, not individual blocks.

Haskell reference:
    Ouroboros/Network/BlockFetch/Client.hs (blockFetchClient)
    The Haskell block-fetch client uses a decision loop that pipelines
    range requests based on the BlockFetchDecision from the consensus layer.
    Our version is simpler: given a list of ranges, pipeline them all.

Spec reference:
    Ouroboros network spec, Section 3.3 "Block Fetch Mini-Protocol"
    combined with Section 2.3 "Pipelining"
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from vibe.core.protocols.pipelining import PipelinedRunner
from vibe.core.protocols.agency import PeerRole, ProtocolError

from vibe.cardano.network.chainsync import PointOrOrigin
from vibe.cardano.network.blockfetch_protocol import (
    BlockFetchCodec,
    BlockFetchProtocol,
    BfMsgRequestRange,
    BfMsgClientDone,
    BfMsgStartBatch,
    BfMsgNoBlocks,
    BfMsgBlock,
    BfMsgBatchDone,
)

__all__ = [
    "PipelinedBlockFetchClient",
    "run_pipelined_block_fetch",
]

logger = logging.getLogger(__name__)

#: Type alias for block-received callback.
OnBlockReceived = Callable[[bytes], Awaitable[None]]

#: Type alias for no-blocks callback.
OnNoBlocks = Callable[[PointOrOrigin, PointOrOrigin], Awaitable[None]]


class PipelinedBlockFetchClient:
    """Pipelined block-fetch client for high-throughput block downloading.

    Sends multiple MsgRequestRange messages into the pipeline, then
    collects the multi-message responses (StartBatch, Block*, BatchDone)
    for each range.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    max_in_flight : int
        Maximum number of pipelined range requests. Default: 100.
        Note: each range may produce many blocks, so the effective
        pipeline depth in terms of data is much higher than this number.
    """

    __slots__ = ("_channel", "_max_in_flight", "_codec")

    def __init__(
        self,
        channel: Any,
        max_in_flight: int = 100,
    ) -> None:
        self._channel = channel
        self._max_in_flight = max_in_flight
        self._codec = BlockFetchCodec()

    async def run_pipelined_fetch(
        self,
        ranges: list[tuple[PointOrOrigin, PointOrOrigin]],
        on_block: OnBlockReceived,
        on_no_blocks: OnNoBlocks | None = None,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Fetch blocks for multiple ranges using pipelining.

        Sends range requests into the pipeline, then collects responses.
        For each range, the server responds with either:
        - MsgNoBlocks (empty range)
        - MsgStartBatch, MsgBlock*, MsgBatchDone (blocks in range)

        The pipeline ensures multiple ranges are in flight simultaneously,
        so the server can prepare the next range while we process the current.

        Parameters
        ----------
        ranges : list[tuple[PointOrOrigin, PointOrOrigin]]
            List of (from_point, to_point) ranges to fetch.
        on_block : OnBlockReceived
            Async callback invoked for each block (CBOR bytes).
        on_no_blocks : OnNoBlocks | None
            Async callback when server has no blocks for a range.
        stop_event : asyncio.Event | None
            If set, exit after the current range.
        """
        if not ranges:
            return

        pipeline = PipelinedRunner(
            channel=self._channel,
            codec=self._codec,
            max_in_flight=self._max_in_flight,
        )

        async with pipeline:
            # Sender task: pipeline all range requests.
            sender_task = asyncio.create_task(
                self._sender_loop(pipeline, ranges, stop_event),
                name="blockfetch-pipelined-sender",
            )

            try:
                await self._collector_loop(
                    pipeline, ranges, on_block, on_no_blocks, stop_event
                )
            finally:
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass

        # Send ClientDone after all ranges are processed.
        done_data = self._codec.encode(BfMsgClientDone())
        await self._channel.send(done_data)

    async def _sender_loop(
        self,
        pipeline: PipelinedRunner,
        ranges: list[tuple[PointOrOrigin, PointOrOrigin]],
        stop_event: asyncio.Event | None,
    ) -> None:
        """Send all range requests into the pipeline.

        The pipeline's backpressure (semaphore) throttles sending when
        max_in_flight is reached.
        """
        try:
            for point_from, point_to in ranges:
                if stop_event is not None and stop_event.is_set():
                    return
                msg = BfMsgRequestRange(point_from, point_to)
                await pipeline.send_request(msg)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Pipelined block-fetch sender error: %s", exc)
            raise

    async def _collector_loop(
        self,
        pipeline: PipelinedRunner,
        ranges: list[tuple[PointOrOrigin, PointOrOrigin]],
        on_block: OnBlockReceived,
        on_no_blocks: OnNoBlocks | None,
        stop_event: asyncio.Event | None,
    ) -> None:
        """Collect responses for each pipelined range request.

        For each range sent, we expect one of:
        - MsgNoBlocks
        - MsgStartBatch followed by MsgBlock* and MsgBatchDone

        Responses arrive in the same order as requests (TCP ordering).
        """
        for point_from, point_to in ranges:
            if stop_event is not None and stop_event.is_set():
                logger.debug("Pipelined block-fetch: stop requested")
                return

            # Collect the first response for this range.
            response = await pipeline.collect_response()

            if isinstance(response, BfMsgNoBlocks):
                logger.debug(
                    "Pipelined block-fetch: no blocks for range %s -> %s",
                    point_from,
                    point_to,
                )
                if on_no_blocks is not None:
                    await on_no_blocks(point_from, point_to)

            elif isinstance(response, BfMsgStartBatch):
                # Collect all blocks in this batch.
                while True:
                    msg = await pipeline.collect_response()
                    if isinstance(msg, BfMsgBlock):
                        await on_block(msg.block_cbor)
                    elif isinstance(msg, BfMsgBatchDone):
                        break
                    else:
                        raise ProtocolError(
                            f"Unexpected message during block streaming: "
                            f"{type(msg).__name__}"
                        )

            else:
                raise ProtocolError(
                    f"Unexpected response to RequestRange: "
                    f"{type(response).__name__}"
                )


async def run_pipelined_block_fetch(
    channel: Any,
    ranges: list[tuple[PointOrOrigin, PointOrOrigin]],
    on_block: OnBlockReceived,
    on_no_blocks: OnNoBlocks | None = None,
    *,
    max_in_flight: int = 100,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run a pipelined block-fetch session for a list of ranges.

    This is the main entry point for pipelined block fetching. It mirrors
    run_block_fetch() from blockfetch_protocol.py but uses pipelining for
    dramatically faster throughput.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for block-fetch.
    ranges : list[tuple[PointOrOrigin, PointOrOrigin]]
        List of (from_point, to_point) ranges to fetch.
    on_block : OnBlockReceived
        Async callback for each block received.
    on_no_blocks : OnNoBlocks | None
        Async callback when server has no blocks for a range.
    max_in_flight : int
        Maximum pipeline depth for range requests (default: 100).
    stop_event : asyncio.Event | None
        If set, exit after the current range.
    """
    client = PipelinedBlockFetchClient(
        channel=channel,
        max_in_flight=max_in_flight,
    )

    logger.info("Pipelined block-fetch starting (%d ranges, depth=%d)", len(ranges), max_in_flight, extra={"event": "blockfetch.pipelined.start", "range_count": len(ranges), "max_in_flight": max_in_flight})

    await client.run_pipelined_fetch(
        ranges=ranges,
        on_block=on_block,
        on_no_blocks=on_no_blocks,
        stop_event=stop_event,
    )
