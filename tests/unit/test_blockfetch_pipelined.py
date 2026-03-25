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
