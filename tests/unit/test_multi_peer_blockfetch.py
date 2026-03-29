"""Tests for multi-peer parallel block-fetch."""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.blockfetch import (
    encode_batch_done,
    encode_block,
    encode_start_batch,
)
from vibe.cardano.network.chainsync import Point


SAMPLE_BLOCK = b"\xde\xad" * 50


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._responses: asyncio.Queue[bytes] = asyncio.Queue()

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        return await asyncio.wait_for(self._responses.get(), timeout=0.5)

    def inject(self, data: bytes) -> None:
        self._responses.put_nowait(data)


class TestMultiPeerRangeDistribution:
    @pytest.mark.asyncio
    async def test_two_peers_fetch_different_ranges(self):
        """Two peers pull from same range_queue — each gets unique ranges."""
        from vibe.cardano.network.blockfetch_protocol import run_block_fetch_pipelined

        ch1, ch2 = FakeChannel(), FakeChannel()
        range_queue: asyncio.Queue = asyncio.Queue()
        block_queue: asyncio.Queue = asyncio.Queue()
        stop = asyncio.Event()

        for i in range(4):
            p = Point(slot=i * 100, hash=b"\x00" * 31 + bytes([i]))
            range_queue.put_nowait((p, p))

        for ch in [ch1, ch2]:
            for _ in range(2):
                ch.inject(encode_start_batch())
                ch.inject(encode_block(SAMPLE_BLOCK))
                ch.inject(encode_batch_done())

        async def stop_after():
            await asyncio.sleep(0.5)
            stop.set()

        stopper = asyncio.create_task(stop_after())
        t1 = asyncio.create_task(run_block_fetch_pipelined(
            ch1, range_queue=range_queue, on_block_received=None,
            stop_event=stop, block_queue=block_queue, max_in_flight=2,
        ))
        t2 = asyncio.create_task(run_block_fetch_pipelined(
            ch2, range_queue=range_queue, on_block_received=None,
            stop_event=stop, block_queue=block_queue, max_in_flight=2,
        ))
        await asyncio.gather(t1, t2, stopper, return_exceptions=True)

        # Both peers should have sent at least ClientDone
        assert len(ch1.sent) >= 1
        assert len(ch2.sent) >= 1
        # Total RequestRange messages (excluding ClientDone) should be 4
        # ClientDone is [1] = b'\x81\x01'
        range_msgs = [m for m in ch1.sent + ch2.sent if m != b'\x81\x01']
        assert len(range_msgs) == 4

        blocks = []
        while not block_queue.empty():
            blocks.append(block_queue.get_nowait())
        assert len(blocks) == 4


class TestRangeRecovery:
    @pytest.mark.asyncio
    async def test_no_blocks_re_enqueues_range(self):
        """NoBlocks response puts the range back on range_queue."""
        from vibe.cardano.node.peer_manager import _RangeTracker

        range_queue: asyncio.Queue = asyncio.Queue()
        tracker = _RangeTracker(range_queue)

        r = (Point(slot=1, hash=b"\x01" * 32), Point(slot=100, hash=b"\x02" * 32))
        tracker.on_no_blocks(r)

        assert not range_queue.empty()
        recovered = range_queue.get_nowait()
        assert recovered == r

    @pytest.mark.asyncio
    async def test_disconnect_re_enqueues_in_flight(self):
        """Peer disconnect puts all in-flight ranges back on range_queue."""
        from vibe.cardano.node.peer_manager import _RangeTracker

        range_queue: asyncio.Queue = asyncio.Queue()
        tracker = _RangeTracker(range_queue)

        r1 = (Point(slot=1, hash=b"\x01" * 32), Point(slot=50, hash=b"\x02" * 32))
        r2 = (Point(slot=51, hash=b"\x03" * 32), Point(slot=100, hash=b"\x04" * 32))
        tracker.on_range_sent("peer1", r1)
        tracker.on_range_sent("peer1", r2)
        tracker.on_peer_disconnect("peer1")

        recovered = []
        while not range_queue.empty():
            recovered.append(range_queue.get_nowait())
        assert len(recovered) == 2
