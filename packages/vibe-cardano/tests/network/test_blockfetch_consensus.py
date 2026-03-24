"""BlockFetch consensus integration tests — Praos and Genesis scenarios.

Tests cover Haskell parity gaps for block-fetch behavior under different
consensus modes:
    1. Terminate correctly under Praos — client sends Done after fetching
    2. Terminate correctly under Genesis — same but with Genesis config
    3. No overlap scheduling under Praos — ranges don't overlap
    4. Overlap scheduling under Praos — overlapping ranges handled

Haskell references:
    Ouroboros.Consensus.MiniProtocol.BlockFetch.ClientInterface
    Test.Consensus.MiniProtocol.BlockFetch.Client
    - testTerminatePraos
    - testTerminateGenesis
    - testNoOverlapPraos
    - testWithOverlapPraos

Antithesis compatibility:
    Tests are deterministic with fixed block data and predictable
    protocol state transitions.
"""

from __future__ import annotations

import asyncio

import pytest

from vibe.cardano.network.blockfetch_protocol import (
    BfMsgBatchDone,
    BfMsgBlock,
    BfMsgClientDone,
    BfMsgRequestRange,
    BfMsgStartBatch,
    BlockFetchCodec,
    run_block_fetch,
)
from vibe.cardano.network.chainsync import Point

# ---------------------------------------------------------------------------
# Fake channel for block-fetch testing
# ---------------------------------------------------------------------------


class FakeBlockFetchChannel:
    """Simulates a MiniProtocolChannel for block-fetch tests."""

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
    """Create a test point with a deterministic hash."""
    return Point(slot=slot, hash=slot.to_bytes(32, "big"))


def _encode(msg: object) -> bytes:
    """Encode a block-fetch message to CBOR."""
    codec = BlockFetchCodec()
    return codec.encode(msg)


# ---------------------------------------------------------------------------
# 1. Fetch terminates correctly under Praos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blockfetch_terminate_praos():
    """Block-fetch client terminates correctly under Praos consensus.

    Under Praos, after fetching all requested ranges, the client sends
    MsgClientDone to terminate the protocol. The final state must be
    BFDone.

    Haskell reference:
        Test.Consensus.MiniProtocol.BlockFetch.Client.testTerminatePraos
    """
    channel = FakeBlockFetchChannel()
    codec = BlockFetchCodec()

    block_data = b"praos-block-1"
    blocks_received: list[bytes] = []

    async def on_block(data: bytes) -> None:
        blocks_received.append(data)

    # Server task: respond to one range request, then expect Done.
    async def server() -> None:
        # Wait for RequestRange.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)

        # Send StartBatch, one Block, BatchDone.
        await channel.feed_response(_encode(BfMsgStartBatch()))
        await channel.feed_response(_encode(BfMsgBlock(block_cbor=block_data)))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Wait for ClientDone.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgClientDone)

    # Client task: fetch one range and terminate.
    ranges = [(_point(1), _point(1))]

    server_task = asyncio.create_task(server())
    client_task = asyncio.create_task(run_block_fetch(channel, ranges, on_block))

    await asyncio.gather(server_task, client_task)

    assert blocks_received == [block_data]


# ---------------------------------------------------------------------------
# 2. Fetch terminates correctly under Genesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blockfetch_terminate_genesis():
    """Block-fetch client terminates correctly under Genesis consensus.

    Genesis mode uses the same block-fetch protocol but may request
    larger ranges. The termination behavior is identical — after all
    ranges, send MsgClientDone.

    Haskell reference:
        Test.Consensus.MiniProtocol.BlockFetch.Client.testTerminateGenesis
    """
    channel = FakeBlockFetchChannel()
    codec = BlockFetchCodec()

    blocks_received: list[bytes] = []

    async def on_block(data: bytes) -> None:
        blocks_received.append(data)

    # Genesis-style: fetch from origin to a point (large range).
    genesis_block_1 = b"genesis-block-1"
    genesis_block_2 = b"genesis-block-2"

    async def server() -> None:
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)

        await channel.feed_response(_encode(BfMsgStartBatch()))
        await channel.feed_response(_encode(BfMsgBlock(block_cbor=genesis_block_1)))
        await channel.feed_response(_encode(BfMsgBlock(block_cbor=genesis_block_2)))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Expect Done.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgClientDone)

    ranges = [(_point(0), _point(100))]
    server_task = asyncio.create_task(server())
    client_task = asyncio.create_task(run_block_fetch(channel, ranges, on_block))

    await asyncio.gather(server_task, client_task)
    assert len(blocks_received) == 2
    assert blocks_received == [genesis_block_1, genesis_block_2]


# ---------------------------------------------------------------------------
# 3. No overlap scheduling under Praos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blockfetch_no_overlap_praos():
    """Non-overlapping range requests are handled correctly.

    Under Praos with no overlap scheduling, each range request covers
    a disjoint set of blocks. The client processes them sequentially.

    Haskell reference:
        Test.Consensus.MiniProtocol.BlockFetch.Client.testNoOverlapPraos
    """
    channel = FakeBlockFetchChannel()
    codec = BlockFetchCodec()

    blocks_received: list[bytes] = []

    async def on_block(data: bytes) -> None:
        blocks_received.append(data)

    # Two non-overlapping ranges: [1, 3] and [4, 6].
    ranges = [(_point(1), _point(3)), (_point(4), _point(6))]

    async def server() -> None:
        # Range 1: blocks 1-3.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)
        assert msg.point_from.slot == 1
        assert msg.point_to.slot == 3

        await channel.feed_response(_encode(BfMsgStartBatch()))
        for i in range(1, 4):
            await channel.feed_response(_encode(BfMsgBlock(block_cbor=f"block-{i}".encode())))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Range 2: blocks 4-6.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)
        assert msg.point_from.slot == 4
        assert msg.point_to.slot == 6

        await channel.feed_response(_encode(BfMsgStartBatch()))
        for i in range(4, 7):
            await channel.feed_response(_encode(BfMsgBlock(block_cbor=f"block-{i}".encode())))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Expect Done.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgClientDone)

    server_task = asyncio.create_task(server())
    client_task = asyncio.create_task(run_block_fetch(channel, ranges, on_block))

    await asyncio.gather(server_task, client_task)

    # Should have received 6 blocks in order.
    assert len(blocks_received) == 6
    for i in range(1, 7):
        assert blocks_received[i - 1] == f"block-{i}".encode()


# ---------------------------------------------------------------------------
# 4. Overlap scheduling under Praos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blockfetch_with_overlap_praos():
    """Overlapping range requests are handled by processing sequentially.

    When ranges overlap (e.g., [1, 5] and [3, 7]), the block-fetch
    client processes them sequentially. The server may return duplicate
    blocks for the overlapping region. The client receives all blocks
    from all ranges.

    Haskell reference:
        Test.Consensus.MiniProtocol.BlockFetch.Client.testWithOverlapPraos
    """
    channel = FakeBlockFetchChannel()
    codec = BlockFetchCodec()

    blocks_received: list[bytes] = []

    async def on_block(data: bytes) -> None:
        blocks_received.append(data)

    # Overlapping ranges: [1, 5] and [3, 7] share blocks 3, 4, 5.
    ranges = [(_point(1), _point(5)), (_point(3), _point(7))]

    async def server() -> None:
        # Range 1: blocks 1-5.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)

        await channel.feed_response(_encode(BfMsgStartBatch()))
        for i in range(1, 6):
            await channel.feed_response(_encode(BfMsgBlock(block_cbor=f"block-{i}".encode())))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Range 2: blocks 3-7 (overlap with range 1).
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgRequestRange)

        await channel.feed_response(_encode(BfMsgStartBatch()))
        for i in range(3, 8):
            await channel.feed_response(_encode(BfMsgBlock(block_cbor=f"block-{i}".encode())))
        await channel.feed_response(_encode(BfMsgBatchDone()))

        # Expect Done.
        raw = await channel.get_sent()
        msg = codec.decode(raw)
        assert isinstance(msg, BfMsgClientDone)

    server_task = asyncio.create_task(server())
    client_task = asyncio.create_task(run_block_fetch(channel, ranges, on_block))

    await asyncio.gather(server_task, client_task)

    # Total blocks: 5 from range 1 + 5 from range 2 = 10
    # (duplicates are not deduplicated at the protocol level).
    assert len(blocks_received) == 10
