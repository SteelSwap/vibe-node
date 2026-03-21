"""Tests for pipelined block-fetch client.

Tests cover:
- All blocks received in correct order
- max_in_flight=1 equivalent to sequential
- MsgNoBlocks handling
- Multiple ranges with mixed empty/non-empty
- Hypothesis: pipelined fetch preserves block ordering
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.chainsync import Point, ORIGIN, PointOrOrigin
from vibe.cardano.network.blockfetch_protocol import (
    BlockFetchCodec,
    BfMsgRequestRange,
    BfMsgClientDone,
    BfMsgStartBatch,
    BfMsgNoBlocks,
    BfMsgBlock,
    BfMsgBatchDone,
)
from vibe.cardano.network.blockfetch_pipelined import (
    PipelinedBlockFetchClient,
    run_pipelined_block_fetch,
)


# ---------------------------------------------------------------------------
# Fake channel for block-fetch testing
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


def _encode(msg: object) -> bytes:
    """Encode a block-fetch message."""
    codec = BlockFetchCodec()
    return codec.encode(msg)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelinedBlockFetchClient:
    """Core pipelined block-fetch behavior."""

    @pytest.mark.asyncio
    async def test_single_range_all_blocks_received(self) -> None:
        """Fetch a single range and verify all blocks arrive."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=10)

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        ranges = [(_point(0), _point(100))]
        n_blocks = 5

        async def server() -> None:
            # Consume RequestRange.
            await channel.get_sent()
            # Send StartBatch, blocks, BatchDone.
            await channel.feed_response(_encode(BfMsgStartBatch()))
            for i in range(n_blocks):
                block_data = f"block-{i}".encode()
                await channel.feed_response(_encode(BfMsgBlock(block_data)))
            await channel.feed_response(_encode(BfMsgBatchDone()))
            # Consume ClientDone.
            await channel.get_sent()

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(
            ranges=ranges,
            on_block=on_block,
        )

        await server_task

        assert len(received_blocks) == n_blocks
        for i in range(n_blocks):
            assert received_blocks[i] == f"block-{i}".encode()

    @pytest.mark.asyncio
    async def test_multiple_ranges_in_order(self) -> None:
        """Fetch multiple ranges and verify block order is preserved."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=10)

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        ranges = [
            (_point(0), _point(100)),
            (_point(101), _point(200)),
            (_point(201), _point(300)),
        ]

        async def server() -> None:
            for range_idx in range(3):
                await channel.get_sent()  # Consume RequestRange.
                await channel.feed_response(_encode(BfMsgStartBatch()))
                for block_idx in range(3):
                    data = f"r{range_idx}-b{block_idx}".encode()
                    await channel.feed_response(_encode(BfMsgBlock(data)))
                await channel.feed_response(_encode(BfMsgBatchDone()))
            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(ranges=ranges, on_block=on_block)

        await server_task

        expected = []
        for r in range(3):
            for b in range(3):
                expected.append(f"r{r}-b{b}".encode())
        assert received_blocks == expected

    @pytest.mark.asyncio
    async def test_no_blocks_response(self) -> None:
        """MsgNoBlocks is handled correctly."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=10)

        received_blocks: list[bytes] = []
        no_blocks_calls: list[tuple[PointOrOrigin, PointOrOrigin]] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        async def on_no_blocks(p_from: PointOrOrigin, p_to: PointOrOrigin) -> None:
            no_blocks_calls.append((p_from, p_to))

        ranges = [(_point(0), _point(100))]

        async def server() -> None:
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgNoBlocks()))
            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(
            ranges=ranges, on_block=on_block, on_no_blocks=on_no_blocks,
        )

        await server_task

        assert len(received_blocks) == 0
        assert len(no_blocks_calls) == 1
        assert no_blocks_calls[0] == (_point(0), _point(100))

    @pytest.mark.asyncio
    async def test_mixed_empty_and_full_ranges(self) -> None:
        """Mix of empty (NoBlocks) and non-empty ranges."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=10)

        received_blocks: list[bytes] = []
        empty_ranges: list[int] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        async def on_no_blocks(p_from: PointOrOrigin, p_to: PointOrOrigin) -> None:
            empty_ranges.append(p_from.slot if isinstance(p_from, Point) else -1)

        ranges = [
            (_point(0), _point(100)),    # Has blocks
            (_point(101), _point(200)),   # Empty
            (_point(201), _point(300)),   # Has blocks
        ]

        async def server() -> None:
            # Range 0: has blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-a")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            # Range 1: no blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgNoBlocks()))

            # Range 2: has blocks.
            await channel.get_sent()
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-b")))
            await channel.feed_response(_encode(BfMsgBatchDone()))

            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(
            ranges=ranges, on_block=on_block, on_no_blocks=on_no_blocks,
        )

        await server_task

        assert received_blocks == [b"block-a", b"block-b"]
        assert empty_ranges == [101]

    @pytest.mark.asyncio
    async def test_empty_ranges_list(self) -> None:
        """Empty ranges list returns immediately without errors."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=10)

        await client.run_pipelined_fetch(
            ranges=[], on_block=AsyncMock(),
        )


class TestPipelinedBlockFetchSequentialEquivalence:
    """max_in_flight=1 produces same results as sequential."""

    @pytest.mark.asyncio
    async def test_max_in_flight_one_is_sequential(self) -> None:
        """With max_in_flight=1, behavior matches sequential fetch."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=1)

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        ranges = [
            (_point(0), _point(10)),
            (_point(11), _point(20)),
        ]

        async def server() -> None:
            for range_idx in range(2):
                await channel.get_sent()
                await channel.feed_response(_encode(BfMsgStartBatch()))
                for j in range(2):
                    data = f"r{range_idx}-b{j}".encode()
                    await channel.feed_response(_encode(BfMsgBlock(data)))
                await channel.feed_response(_encode(BfMsgBatchDone()))
            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(ranges=ranges, on_block=on_block)

        await server_task

        expected = [b"r0-b0", b"r0-b1", b"r1-b0", b"r1-b1"]
        assert received_blocks == expected


class TestRunPipelinedBlockFetch:
    """Test the top-level run_pipelined_block_fetch function."""

    @pytest.mark.asyncio
    async def test_full_fetch_session(self) -> None:
        """run_pipelined_block_fetch runs the full fetch session."""
        channel = FakeBlockFetchChannel()

        received_blocks: list[bytes] = []

        async def on_block(block_cbor: bytes) -> None:
            received_blocks.append(block_cbor)

        ranges = [(_point(0), _point(100))]

        async def server() -> None:
            await channel.get_sent()  # RequestRange.
            await channel.feed_response(_encode(BfMsgStartBatch()))
            await channel.feed_response(_encode(BfMsgBlock(b"block-0")))
            await channel.feed_response(_encode(BfMsgBlock(b"block-1")))
            await channel.feed_response(_encode(BfMsgBatchDone()))
            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await run_pipelined_block_fetch(
            channel=channel,
            ranges=ranges,
            on_block=on_block,
            max_in_flight=5,
        )

        await server_task

        assert received_blocks == [b"block-0", b"block-1"]


class TestPipelinedBlockFetchProperties:
    """Property-based tests."""

    @pytest.mark.asyncio
    @given(
        n_ranges=st.integers(min_value=1, max_value=10),
        blocks_per_range=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=15, deadline=5000)
    async def test_all_blocks_received_in_order(
        self, n_ranges: int, blocks_per_range: int
    ) -> None:
        """For any number of ranges and blocks, all blocks arrive in order."""
        channel = FakeBlockFetchChannel()
        client = PipelinedBlockFetchClient(channel, max_in_flight=n_ranges)

        received: list[str] = []

        async def on_block(block_cbor: bytes) -> None:
            received.append(block_cbor.decode())

        ranges = [
            (_point(i * 100), _point(i * 100 + 99))
            for i in range(n_ranges)
        ]

        async def server() -> None:
            for r_idx in range(n_ranges):
                await channel.get_sent()
                await channel.feed_response(_encode(BfMsgStartBatch()))
                for b_idx in range(blocks_per_range):
                    data = f"r{r_idx}-b{b_idx}".encode()
                    await channel.feed_response(_encode(BfMsgBlock(data)))
                await channel.feed_response(_encode(BfMsgBatchDone()))
            await channel.get_sent()  # ClientDone.

        server_task = asyncio.create_task(server())

        await client.run_pipelined_fetch(ranges=ranges, on_block=on_block)

        await server_task

        expected = [
            f"r{r}-b{b}"
            for r in range(n_ranges)
            for b in range(blocks_per_range)
        ]
        assert received == expected
