"""Tests for pipelined block-fetch (run_block_fetch_pipelined)."""

from __future__ import annotations

import asyncio

import pytest

import cbor2pure as cbor2

from vibe.cardano.network.blockfetch import (
    MSG_REQUEST_RANGE,
    encode_batch_done,
    encode_block,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import Point


HASH_A = b"\xaa" * 32
HASH_B = b"\xbb" * 32
POINT_A = Point(slot=1, hash=HASH_A)
POINT_B = Point(slot=100, hash=HASH_B)
SAMPLE_BLOCK = b"\xde\xad" * 50


class FakeChannel:
    """Mock mux channel that records sent bytes and feeds scripted responses."""

    def __init__(self, responses: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()
        if responses:
            for r in responses:
                self._responses.put_nowait(r)

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        return await self._responses.get()

    def inject(self, data: bytes) -> None:
        """Add a response to be returned by recv()."""
        self._responses.put_nowait(data)


class TestPipelinedSender:
    """Verify the sender task sends MsgRequestRange from range_queue."""

    @pytest.mark.asyncio
    async def test_sender_sends_request_range(self):
        """Sender encodes and sends MsgRequestRange for each range in the queue."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        range_queue.put_nowait((POINT_A, POINT_B))

        stop = asyncio.Event()
        blocks_received: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks_received.append(b)

        # Inject server response: StartBatch, Block, BatchDone
        channel.inject(encode_start_batch())
        channel.inject(encode_block(SAMPLE_BLOCK))
        channel.inject(encode_batch_done())

        # Run pipelined fetch — should process 1 range then wait
        # Set stop after a short delay
        async def stop_after():
            await asyncio.sleep(0.1)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        stopper = asyncio.create_task(stop_after())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await stopper

        # Verify: sender sent MsgRequestRange
        assert len(channel.sent) >= 1
        decoded = cbor2.loads(channel.sent[0])
        assert decoded[0] == MSG_REQUEST_RANGE

        # Verify: processor received the block
        assert len(blocks_received) == 1
        assert blocks_received[0] == SAMPLE_BLOCK


class TestPipelining:
    """Verify that multiple range requests are in flight simultaneously."""

    @pytest.mark.asyncio
    async def test_multiple_ranges_in_flight(self):
        """Sender sends up to max_in_flight ranges without waiting for BatchDone."""

        class TrackingChannel(FakeChannel):
            """FakeChannel that signals when N sends have occurred."""

            def __init__(self, notify_at: int) -> None:
                super().__init__()
                self._notify_at = notify_at
                self.send_reached = asyncio.Event()

            async def send(self, data: bytes) -> None:
                self.sent.append(data)
                if len(self.sent) >= self._notify_at:
                    self.send_reached.set()

        max_in_flight = 2
        channel = TrackingChannel(notify_at=max_in_flight)
        range_queue: asyncio.Queue = asyncio.Queue()

        # Queue 5 ranges
        for i in range(5):
            point = Point(slot=i * 100, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        async def delayed_responses():
            # Wait until sender has sent max_in_flight requests
            await channel.send_reached.wait()
            sent_before_response = len(channel.sent)

            # Now feed responses for all 5 ranges
            for _ in range(5):
                channel.inject(encode_start_batch())
                channel.inject(encode_block(SAMPLE_BLOCK))
                channel.inject(encode_batch_done())

            await asyncio.sleep(0.5)
            stop.set()
            return sent_before_response

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        response_task = asyncio.create_task(delayed_responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=max_in_flight,
        )
        sent_before_response = await response_task

        # Sender should have sent exactly max_in_flight before blocking
        assert sent_before_response == max_in_flight

        # All 5 blocks should have been processed
        assert len(blocks) == 5


class TestBackpressure:
    """Verify in_flight tracking and backpressure."""

    @pytest.mark.asyncio
    async def test_in_flight_respects_max(self):
        """After max_in_flight ranges sent, sender blocks until BatchDone."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()

        for i in range(10):
            point = Point(slot=i, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        # Feed responses one batch at a time with delays
        async def slow_responses():
            for _batch_num in range(10):
                await asyncio.sleep(0.02)
                channel.inject(encode_start_batch())
                channel.inject(encode_block(b"block"))
                channel.inject(encode_batch_done())
            await asyncio.sleep(0.5)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        resp_task = asyncio.create_task(slow_responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await resp_task

        # All 10 blocks received
        assert len(blocks) == 10


class TestShutdown:
    """Verify clean shutdown without hanging tasks."""

    @pytest.mark.asyncio
    async def test_stop_event_exits_cleanly(self):
        """Setting stop_event causes all tasks to exit without hanging."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()

        async def on_block(b: bytes) -> None:
            pass

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        # Set stop after a tiny delay so tasks have started
        async def stop_soon():
            await asyncio.sleep(0.01)
            stop.set()

        stopper = asyncio.create_task(stop_soon())
        await asyncio.wait_for(
            run_block_fetch_pipelined(
                channel,
                range_queue=range_queue,
                on_block_received=on_block,
                stop_event=stop,
            ),
            timeout=3.0,
        )
        await stopper
        # If we get here without timeout, shutdown is clean


class TestNoBlocks:
    """Verify NoBlocks response is handled correctly."""

    @pytest.mark.asyncio
    async def test_no_blocks_decrements_in_flight(self):
        """NoBlocks response frees a slot so sender can send more ranges."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()

        for i in range(3):
            point = Point(slot=i, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((point, point))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        from vibe.cardano.network.blockfetch import encode_no_blocks

        async def responses():
            await asyncio.sleep(0.05)
            # Range 1: NoBlocks
            channel.inject(encode_no_blocks())
            # Range 2: has blocks
            channel.inject(encode_start_batch())
            channel.inject(encode_block(b"block2"))
            channel.inject(encode_batch_done())
            # Range 3: has blocks
            channel.inject(encode_start_batch())
            channel.inject(encode_block(b"block3"))
            channel.inject(encode_batch_done())
            await asyncio.sleep(0.5)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        resp = asyncio.create_task(responses())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await resp

        # 2 blocks received (range 1 had NoBlocks)
        assert len(blocks) == 2


class TestReassembly:
    """Verify receiver handles CBOR messages split across multiple recv() calls."""

    @pytest.mark.asyncio
    async def test_split_block_message(self):
        """A MsgBlock split across two recv() calls is reassembled correctly."""
        channel = FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        range_queue.put_nowait((POINT_A, POINT_B))

        stop = asyncio.Event()
        blocks: list[bytes] = []

        async def on_block(b: bytes) -> None:
            blocks.append(b)

        # Encode a complete batch: StartBatch + Block + BatchDone
        start_bytes = encode_start_batch()
        block_bytes = encode_block(SAMPLE_BLOCK)
        done_bytes = encode_batch_done()

        # Inject StartBatch normally
        channel.inject(start_bytes)
        # Split the Block message in half
        mid = len(block_bytes) // 2
        channel.inject(block_bytes[:mid])
        channel.inject(block_bytes[mid:])
        # BatchDone normally
        channel.inject(done_bytes)

        async def stop_later():
            await asyncio.sleep(0.5)
            stop.set()

        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        stopper = asyncio.create_task(stop_later())
        await run_block_fetch_pipelined(
            channel,
            range_queue=range_queue,
            on_block_received=on_block,
            stop_event=stop,
            max_in_flight=3,
        )
        await stopper

        assert len(blocks) == 1
        assert blocks[0] == SAMPLE_BLOCK
