"""Tests for persistent (continuous) block-fetch client.

Tests cover:
- Multiple ranges processed on a single ProtocolRunner session
- stop_event terminates the loop cleanly with ClientDone
- MsgNoBlocks callback fires correctly in continuous mode
- Empty queue with stop_event exits without error
"""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.blockfetch_protocol import (
    BfMsgBatchDone,
    BfMsgBlock,
    BfMsgNoBlocks,
    BfMsgStartBatch,
    BlockFetchCodec,
    run_block_fetch_continuous,
)
from vibe.cardano.network.chainsync import Point, PointOrOrigin

# ---------------------------------------------------------------------------
# Fake channel (same pattern as test_blockfetch_pipelined.py)
# ---------------------------------------------------------------------------


class FakeBlockFetchChannel:
    """Simulates a MiniProtocolChannel for block-fetch."""

    def __init__(self) -> None:
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()

    async def send(self, payload: bytes) -> None:
        await self._outbound.put(payload)

    async def recv(self) -> bytes:
        return await self._inbound.get()

    async def feed_response(self, payload: bytes) -> None:
        await self._inbound.put(payload)

    async def get_sent(self) -> bytes:
        return await self._outbound.get()


def _point(slot: int) -> Point:
    """Create a test point."""
    return Point(slot=slot, hash=slot.to_bytes(32, "big"))


_codec = BlockFetchCodec()


def _encode(msg: object) -> bytes:
    return _codec.encode(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBlockFetchContinuousMultipleRanges:
    """Verify multiple ranges work on a single persistent session."""

    @pytest.mark.asyncio
    async def test_two_ranges_same_session(self) -> None:
        """Two ranges are fetched without tearing down the runner."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        # Enqueue two ranges.
        await range_queue.put((_point(0), _point(100)))
        await range_queue.put((_point(101), _point(200)))

        async def server() -> None:
            # Range 1: 2 blocks.
            await channel.get_sent()  # RequestRange
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-0")))
            await channel.feed_response(_encode(BfMsgBlock(b"block-1")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            # Range 2: 1 block.
            await channel.get_sent()  # RequestRange
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-2")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            # Signal stop after processing both ranges.
            # Give the client a moment to process the last batch.
            await asyncio.sleep(0.05)
            stop_event.set()

            # Consume ClientDone.
            await channel.get_sent()

        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop_event,
        )

        await server_task

        assert received_blocks == [b"block-0", b"block-1", b"block-2"]

    @pytest.mark.asyncio
    async def test_three_ranges_all_blocks_arrive(self) -> None:
        """Three ranges produce correct total block count."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        for i in range(3):
            await range_queue.put((_point(i * 100), _point(i * 100 + 99)))

        async def server() -> None:
            for range_idx in range(3):
                await channel.get_sent()  # RequestRange
                await channel.feed_response(_encode(BfMsgStartBatch()))
                for block_idx in range(2):
                    data = f"r{range_idx}-b{block_idx}".encode()
                    await channel.feed_response(_encode(BfMsgBlock(data)))
                await channel.feed_response(_encode(BfMsgBatchDone()))

            await asyncio.sleep(0.05)
            stop_event.set()
            await channel.get_sent()  # ClientDone

        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop_event,
        )

        await server_task

        expected = [f"r{r}-b{b}".encode() for r in range(3) for b in range(2)]
        assert received_blocks == expected


class TestBlockFetchContinuousStopEvent:
    """Verify stop_event terminates the loop cleanly."""

    @pytest.mark.asyncio
    async def test_stop_event_on_empty_queue(self) -> None:
        """stop_event exits even when queue is empty."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        async def on_block(block_cbor: bytes) -> None:
            pytest.fail("No blocks should be received")

        async def trigger_stop() -> None:
            await asyncio.sleep(0.1)
            stop_event.set()

        # Server just needs to consume ClientDone.
        async def server() -> None:
            await channel.get_sent()  # ClientDone

        stop_task = asyncio.create_task(trigger_stop())
        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop_event,
        )

        await stop_task
        await server_task

    @pytest.mark.asyncio
    async def test_stop_after_one_range(self) -> None:
        """Process one range, then stop_event terminates before next."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        await range_queue.put((_point(0), _point(10)))

        async def server() -> None:
            await channel.get_sent()  # RequestRange
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"only-block")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            # Set stop after first range processed.
            await asyncio.sleep(0.05)
            stop_event.set()
            await channel.get_sent()  # ClientDone

        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop_event,
        )

        await server_task

        assert received_blocks == [b"only-block"]


class TestBlockFetchContinuousNoBlocks:
    """Verify MsgNoBlocks callback works in continuous mode."""

    @pytest.mark.asyncio
    async def test_no_blocks_callback_fires(self) -> None:
        """on_no_blocks is invoked when server responds with NoBlocks."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        no_blocks_calls: list[tuple[PointOrOrigin, PointOrOrigin]] = []

        async def on_block(block_cbor: bytes) -> None:
            pytest.fail("No blocks should be received")

        async def on_no_blocks(p_from: PointOrOrigin, p_to: PointOrOrigin) -> None:
            no_blocks_calls.append((p_from, p_to))

        await range_queue.put((_point(0), _point(100)))

        async def server() -> None:
            await channel.get_sent()  # RequestRange
            await channel.feed_response(_encode(BfMsgNoBlocks()))

            await asyncio.sleep(0.05)
            stop_event.set()
            await channel.get_sent()  # ClientDone

        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            on_no_blocks=on_no_blocks,
            stop_event=stop_event,
        )

        await server_task

        assert len(no_blocks_calls) == 1
        assert no_blocks_calls[0] == (_point(0), _point(100))

    @pytest.mark.asyncio
    async def test_mixed_no_blocks_and_blocks(self) -> None:
        """Mix of NoBlocks and block-bearing ranges in continuous mode."""
        channel = FakeBlockFetchChannel()
        range_queue: asyncio.Queue[tuple[PointOrOrigin, PointOrOrigin]] = asyncio.Queue()
        stop_event = asyncio.Event()

        received_blocks: list[bytes] = []
        no_blocks_count = 0

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        async def on_no_blocks(p_from: PointOrOrigin, p_to: PointOrOrigin) -> None:
            nonlocal no_blocks_count
            no_blocks_count += 1

        await range_queue.put((_point(0), _point(100)))  # Has blocks
        await range_queue.put((_point(101), _point(200)))  # Empty
        await range_queue.put((_point(201), _point(300)))  # Has blocks

        async def server() -> None:
            # Range 1: blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-a")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            # Range 2: no blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgNoBlocks()))

            # Range 3: blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-b")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            await asyncio.sleep(0.05)
            stop_event.set()
            await channel.get_sent()  # ClientDone

        server_task = asyncio.create_task(server())

        await run_block_fetch_continuous(
            channel=channel,
            range_queue=range_queue,
            on_block_received=on_block,
            on_no_blocks=on_no_blocks,
            stop_event=stop_event,
        )

        await server_task

        assert received_blocks == [b"block-a", b"block-b"]
        assert no_blocks_count == 1
