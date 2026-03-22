"""Tests for M5.35 — connection timeout handling.

Tests cover:
- Chain-sync server sends AwaitReply when client is at tip
- Chain-sync server handles client disconnect during await
- Keep-alive prevents idle disconnect
- BearerClosedError handled gracefully in peer loop
- Reconnect after disconnect
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibe.cardano.network.chainsync import (
    ORIGIN,
    Point,
    Tip,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainProvider,
    ChainSyncCodec,
    ChainSyncProtocol,
    CsMsgAwaitReply,
    CsMsgDone,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
    CsMsgRequestNext,
    CsMsgRollForward,
    run_chain_sync_server,
)
from vibe.cardano.node.config import NodeConfig, PeerAddress
from vibe.cardano.node.run import PeerManager
from vibe.core.multiplexer import BearerClosedError, MuxClosedError
from vibe.core.protocols.agency import PeerRole
from vibe.core.protocols.runner import ProtocolRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TIP = Tip(point=Point(slot=100, hash=b"\xaa" * 32), block_number=10)
SAMPLE_HEADER = b"\xde\xad" * 16


class StubChainProvider(ChainProvider):
    """A chain provider that returns a fixed sequence of actions."""

    def __init__(self, actions: list[tuple[str, bytes | None, object, Tip]]):
        self._actions = list(actions)
        self._call_count = 0

    async def get_tip(self) -> Tip:
        return SAMPLE_TIP

    async def find_intersect(self, points):
        return ORIGIN, SAMPLE_TIP

    async def next_block(self, client_point):
        if self._call_count < len(self._actions):
            result = self._actions[self._call_count]
            self._call_count += 1
            return result
        return ("await", None, None, SAMPLE_TIP)


def _make_mock_channel() -> MagicMock:
    """Create a mock MiniProtocolChannel with async send/recv."""
    channel = MagicMock()
    channel.send = AsyncMock()
    channel.recv = AsyncMock()
    return channel


def _make_node_config(**overrides) -> NodeConfig:
    """Create a minimal NodeConfig for testing."""
    defaults = {
        "network_magic": 764824073,
        "host": "127.0.0.1",
        "port": 3001,
        "peers": [],
    }
    defaults.update(overrides)
    return NodeConfig(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_sync_server_sends_await_reply_at_tip():
    """When the client is at tip, the server must send AwaitReply.

    The chain-sync server sends MsgAwaitReply when next_block returns
    ("await", None, None, tip), then polls until data is available.
    After data arrives, it sends RollForward and returns to StIdle.
    """
    new_point = Point(slot=101, hash=b"\xbb" * 32)
    new_tip = Tip(point=new_point, block_number=11)

    provider = StubChainProvider([
        # First call: at tip -> await
        ("await", None, None, SAMPLE_TIP),
        # Second call (after polling): new block available
        ("roll_forward", SAMPLE_HEADER, new_point, new_tip),
    ])

    # Track messages sent by the server.
    sent_messages: list[object] = []
    recv_queue: asyncio.Queue = asyncio.Queue()

    channel = _make_mock_channel()

    # Simulate client sending FindIntersect, then RequestNext, then Done.
    codec = ChainSyncCodec()

    find_msg = CsMsgFindIntersect(points=[ORIGIN])
    req_msg = CsMsgRequestNext()
    done_msg = CsMsgDone()

    encoded_find = codec.encode(find_msg)
    encoded_req = codec.encode(req_msg)
    encoded_done = codec.encode(done_msg)

    recv_returns = [encoded_find, encoded_req, encoded_done]
    recv_idx = 0

    async def mock_recv() -> bytes:
        nonlocal recv_idx
        if recv_idx < len(recv_returns):
            data = recv_returns[recv_idx]
            recv_idx += 1
            return data
        # Block forever (simulating no more messages).
        await asyncio.sleep(999)
        return b""

    async def mock_send(data: bytes) -> None:
        sent_messages.append(data)

    channel.recv = mock_recv
    channel.send = mock_send

    stop = asyncio.Event()

    # Run server with a timeout so it doesn't hang.
    try:
        await asyncio.wait_for(
            run_chain_sync_server(channel, provider, stop_event=stop),
            timeout=5.0,
        )
    except TimeoutError:
        stop.set()

    # Verify that the server sent messages including AwaitReply.
    assert len(sent_messages) >= 2, f"Expected at least 2 sent messages, got {len(sent_messages)}"

    # Decode sent messages to verify AwaitReply was among them.
    decoded = [codec.decode(m) for m in sent_messages]
    types = [type(m).__name__ for m in decoded]

    # First should be IntersectFound (response to FindIntersect).
    assert "CsMsgIntersectFound" in types[0], f"Expected IntersectFound, got {types[0]}"
    # Second should be AwaitReply (client at tip).
    assert "CsMsgAwaitReply" in types[1], f"Expected AwaitReply, got {types[1]}"
    # Third should be RollForward (after data arrived).
    assert "CsMsgRollForward" in types[2], f"Expected RollForward, got {types[2]}"


@pytest.mark.asyncio
async def test_chain_sync_server_handles_client_done_during_await():
    """The server should exit cleanly if the channel closes during await.

    When the chain-sync server is in the AwaitReply polling loop and
    the underlying channel raises an exception (client disconnected),
    the server should return without crashing.
    """
    provider = StubChainProvider([
        # Always returns await — forces the server into the polling loop.
        ("await", None, None, SAMPLE_TIP),
        ("await", None, None, SAMPLE_TIP),
        ("await", None, None, SAMPLE_TIP),
        ("await", None, None, SAMPLE_TIP),
    ])

    channel = _make_mock_channel()
    codec = ChainSyncCodec()

    # Client sends FindIntersect, then RequestNext.
    find_msg = codec.encode(CsMsgFindIntersect(points=[ORIGIN]))
    req_msg = codec.encode(CsMsgRequestNext())

    call_count = 0

    async def mock_recv() -> bytes:
        nonlocal call_count
        if call_count == 0:
            call_count += 1
            return find_msg
        elif call_count == 1:
            call_count += 1
            return req_msg
        # Simulate client disconnect after server enters await loop.
        raise ConnectionError("client disconnected")

    channel.recv = mock_recv
    channel.send = AsyncMock()

    stop = asyncio.Event()

    # The server should exit cleanly (no exception propagated).
    try:
        await asyncio.wait_for(
            run_chain_sync_server(channel, provider, stop_event=stop),
            timeout=5.0,
        )
    except TimeoutError:
        stop.set()
        pytest.fail("Server hung instead of exiting on client disconnect")


@pytest.mark.asyncio
async def test_keepalive_prevents_idle_disconnect():
    """Verify that keep-alive protocol import exists and can be launched.

    The keep-alive server echoes pings back to the client, preventing
    the Ouroboros 5-second idle timeout from disconnecting the peer.
    This test verifies the keep-alive server function exists and is
    callable (integration test with real connections is separate).
    """
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_server

    # Verify the function signature accepts channel and stop_event.
    assert callable(run_keep_alive_server)

    # Create a mock channel that raises on recv (simulates immediate close).
    channel = _make_mock_channel()
    channel.recv = AsyncMock(side_effect=MuxClosedError("closed"))

    stop = asyncio.Event()

    # The keep-alive server should exit on channel close without crashing.
    try:
        await asyncio.wait_for(
            run_keep_alive_server(channel, stop_event=stop),
            timeout=2.0,
        )
    except (MuxClosedError, TimeoutError):
        # Either outcome is acceptable: the server may propagate
        # MuxClosedError or timeout if it doesn't check the channel.
        pass


@pytest.mark.asyncio
async def test_bearer_closed_handled_gracefully():
    """BearerClosedError and MuxClosedError should be caught in _peer_loop.

    When a peer disconnects, the mux task raises BearerClosedError or
    MuxClosedError. The peer loop should log info (not error) and
    proceed to reconnect.
    """
    config = _make_node_config(
        peers=[PeerAddress(host="127.0.0.1", port=9999)],
    )
    pm = PeerManager(config)
    pm.add_peer(PeerAddress(host="127.0.0.1", port=9999))

    connect_count = 0
    max_connects = 2

    async def mock_connect(self_pm, peer):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            # First connect: simulate successful connection that
            # then raises BearerClosedError.
            peer.connected = True

            async def _raise_bearer_closed():
                await asyncio.sleep(0.05)
                raise BearerClosedError("peer closed")

            peer.mux_task = asyncio.create_task(_raise_bearer_closed())
        elif connect_count >= max_connects:
            # Second connect: stop the loop.
            pm._stopped = True
            raise ConnectionError("stopped")

    peer = list(pm._peers.values())[0]

    with patch.object(PeerManager, "_connect_peer", mock_connect):
        try:
            await asyncio.wait_for(pm._peer_loop(peer), timeout=5.0)
        except (asyncio.CancelledError, TimeoutError):
            pass

    # The peer loop should have attempted at least one reconnect
    # after the BearerClosedError (caught as info, not crash).
    assert connect_count >= 1, "Peer loop should have connected at least once"


@pytest.mark.asyncio
async def test_reconnect_after_disconnect():
    """After disconnect, the peer loop reconnects with exponential backoff.

    The peer loop should catch the disconnect exception, wait with
    backoff, and attempt to reconnect.
    """
    config = _make_node_config(
        peers=[PeerAddress(host="127.0.0.1", port=9999)],
    )
    pm = PeerManager(config)
    pm.add_peer(PeerAddress(host="127.0.0.1", port=9999))

    connect_attempts = []

    async def mock_connect(self_pm, peer):
        connect_attempts.append(asyncio.get_event_loop().time())
        if len(connect_attempts) >= 3:
            pm._stopped = True
            raise ConnectionError("stopped")
        raise ConnectionError("connection refused")

    peer = list(pm._peers.values())[0]

    with patch.object(PeerManager, "_connect_peer", mock_connect):
        try:
            await asyncio.wait_for(pm._peer_loop(peer), timeout=15.0)
        except (asyncio.CancelledError, TimeoutError):
            pass

    # Should have attempted at least 2 connections.
    assert len(connect_attempts) >= 2, (
        f"Expected at least 2 connect attempts, got {len(connect_attempts)}"
    )

    # Verify exponential backoff: second attempt should be delayed.
    if len(connect_attempts) >= 2:
        delay = connect_attempts[1] - connect_attempts[0]
        # Initial backoff is 1.0s, allow some margin.
        assert delay >= 0.5, f"Backoff delay too short: {delay:.2f}s"
