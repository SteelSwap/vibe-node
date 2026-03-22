"""Tests for the chain-sync typed protocol -- Haskell parity gaps.

Covers:
- Chain-sync duration: sync completes within expected time

Haskell references:
    Test.Ouroboros.Network.Protocol.ChainSync
    (testChainSyncPipelinedDuration)
"""

from __future__ import annotations

import asyncio
import time

import pytest

from vibe.cardano.network.chainsync import Point, Tip, ORIGIN
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncCodec,
    ChainSyncProtocol,
    ChainSyncState,
    CsMsgRequestNext,
    CsMsgRollForward,
    CsMsgRollBackward,
    CsMsgDone,
)


# ---------------------------------------------------------------------------
# Fake channel for chain-sync testing
# ---------------------------------------------------------------------------


class FakeChainSyncChannel:
    """Simulates a MiniProtocolChannel for chain-sync."""

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
    return Point(slot=slot, hash=slot.to_bytes(32, "big"))


def _tip(slot: int) -> Tip:
    return Tip(point=_point(slot), block_number=slot)


def _encode(msg: object) -> bytes:
    codec = ChainSyncCodec()
    return codec.encode(msg)


# ---------------------------------------------------------------------------
# test_chainsync_duration -- sync completes within expected time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chainsync_duration():
    """Chain-sync protocol exchange completes within a reasonable time bound.

    This test verifies that a simple chain-sync exchange (request next,
    receive roll-forward, send done) completes without hanging or
    excessive delay. The time bound is generous (5 seconds) -- the point
    is to catch hangs and deadlocks, not micro-optimize.

    Haskell reference:
        Test.Ouroboros.Network.Protocol.ChainSync.testChainSyncPipelinedDuration
        Verifies that pipelined chain-sync completes within a time bound.
    """
    channel = FakeChainSyncChannel()
    codec = ChainSyncCodec()

    # Simulate a 10-block chain sync exchange.
    num_blocks = 10

    async def client() -> float:
        """Client sends RequestNext, receives RollForward, then Done."""
        start = time.monotonic()
        for _ in range(num_blocks):
            msg = CsMsgRequestNext()
            await channel.send(_encode(msg))
            raw = await channel.recv()
            decoded = codec.decode(raw)
            assert isinstance(decoded, CsMsgRollForward)
        elapsed = time.monotonic() - start
        # Send Done to terminate.
        await channel.send(_encode(CsMsgDone()))
        return elapsed

    async def server() -> None:
        """Server responds to each RequestNext with RollForward."""
        for i in range(1, num_blocks + 1):
            raw = await channel.get_sent()
            decoded = codec.decode(raw)
            assert isinstance(decoded, CsMsgRequestNext)

            response = CsMsgRollForward(
                header=f"block-header-{i}".encode(),
                tip=_tip(i),
            )
            await channel.feed_response(_encode(response))

        # Wait for Done.
        raw = await channel.get_sent()
        decoded = codec.decode(raw)
        assert isinstance(decoded, CsMsgDone)

    # Run with a timeout.
    try:
        server_task = asyncio.create_task(server())
        elapsed = await asyncio.wait_for(client(), timeout=5.0)
        await server_task

        # Sync of 10 blocks should complete well under 5 seconds.
        assert elapsed < 5.0, f"Chain-sync took {elapsed:.2f}s, expected < 5.0s"
    except TimeoutError:
        pytest.fail("Chain-sync timed out after 5 seconds -- possible deadlock")
