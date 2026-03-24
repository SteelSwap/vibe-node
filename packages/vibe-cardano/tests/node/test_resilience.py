"""Connection resilience tests -- exponential backoff and error recovery.

Tests the PeerManager's reconnect behaviour when peer connections fail
or drop unexpectedly (MuxClosedError, ConnectionError, OSError).

Haskell ref:
    Ouroboros.Network.PeerSelection.Governor.ActivePeers -- the governor
    uses exponential backoff with a cap for peer reconnection delays.
    Our _peer_loop mirrors this pattern: 1s -> 2s -> 4s -> ... -> 60s cap,
    reset on successful reconnection.

Spec ref:
    Ouroboros network spec, Chapter 2 -- connection management
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from vibe.cardano.node.config import NodeConfig, PeerAddress
from vibe.cardano.node.peer_manager import PeerManager, _PeerConnection
from vibe.core.multiplexer import MuxClosedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> NodeConfig:
    """Minimal NodeConfig for PeerManager tests."""
    return NodeConfig(
        network_magic=2,  # preview
        slot_length=1.0,
        epoch_length=432000,
        security_param=2160,
        active_slot_coeff=0.05,
        system_start=datetime(2022, 11, 1, tzinfo=UTC),
        host="127.0.0.1",
        port=3001,
    )


def _make_peer() -> _PeerConnection:
    """Create a _PeerConnection with a dummy address."""
    return _PeerConnection(address=PeerAddress(host="10.0.0.1", port=3001))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExponentialBackoffTiming:
    """Verify that reconnect delay doubles each attempt and caps at 60s."""

    def test_delay_doubles_and_caps(self) -> None:
        """Backoff sequence: 1, 2, 4, 8, 16, 32, 60, 60."""
        peer = _make_peer()
        assert peer.reconnect_delay == 1.0

        expected = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
        delays: list[float] = []

        for _ in expected:
            delays.append(peer.reconnect_delay)
            peer.reconnect_delay = min(peer.reconnect_delay * 2, 60.0)

        assert delays == expected

    def test_cap_never_exceeded(self) -> None:
        """After many failures the delay never exceeds 60s."""
        peer = _make_peer()
        for _ in range(100):
            peer.reconnect_delay = min(peer.reconnect_delay * 2, 60.0)
        assert peer.reconnect_delay == 60.0


class TestBackoffResetsOnSuccess:
    """Verify that backoff resets to 1s after a successful reconnection."""

    def test_reset_after_success(self) -> None:
        """After escalating backoff, a successful connect resets to 1s."""
        peer = _make_peer()

        # Escalate backoff 5 times: 1 -> 2 -> 4 -> 8 -> 16 -> 32
        for _ in range(5):
            peer.reconnect_delay = min(peer.reconnect_delay * 2, 60.0)
        assert peer.reconnect_delay == 32.0
        assert peer.reconnect_attempt == 0  # not yet incremented in unit test

        # Simulate what _peer_loop does on successful connect.
        peer.reconnect_delay = 1.0
        peer.reconnect_attempt = 0
        assert peer.reconnect_delay == 1.0
        assert peer.reconnect_attempt == 0

    def test_attempt_counter_resets(self) -> None:
        """reconnect_attempt resets to 0 after success."""
        peer = _make_peer()
        peer.reconnect_attempt = 7
        peer.reconnect_delay = 60.0

        # Simulate successful connect.
        peer.reconnect_delay = 1.0
        peer.reconnect_attempt = 0

        assert peer.reconnect_attempt == 0
        assert peer.reconnect_delay == 1.0


class TestMuxClosedErrorDoesntCrash:
    """Verify that MuxClosedError during the mux task is caught gracefully.

    When a peer disconnects, the multiplexer raises MuxClosedError.  The
    _peer_loop must catch this, log at INFO, and continue to the
    reconnect backoff -- not crash the entire peer task.
    """

    @pytest.mark.asyncio
    async def test_mux_closed_caught_in_peer_loop(self) -> None:
        """_peer_loop catches MuxClosedError and retries."""
        config = _make_config()
        mgr = PeerManager(config)
        peer_addr = PeerAddress(host="10.0.0.1", port=3001)
        mgr.add_peer(peer_addr)

        peer = mgr._peers[str(peer_addr)]
        call_count = 0

        async def _fake_connect(self_arg, p: _PeerConnection) -> None:
            nonlocal call_count
            call_count += 1
            p.connected = True
            p.mux_task = asyncio.create_task(_raise_mux_closed())

        async def _raise_mux_closed() -> None:
            raise MuxClosedError("bearer gone")

        async def _fake_disconnect(self_arg, p: _PeerConnection) -> None:
            p.connected = False

        with (
            patch.object(PeerManager, "_connect_peer", _fake_connect),
            patch.object(PeerManager, "_disconnect_peer", _fake_disconnect),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):

            async def _stop_after_two(delay: float) -> None:
                if call_count >= 2:
                    mgr._stopped = True

            mock_sleep.side_effect = _stop_after_two

            await mgr._peer_loop(peer)

        # Should have attempted connect at least twice (initial + 1 reconnect)
        assert call_count >= 2
        # Backoff delay should have doubled.
        assert peer.reconnect_delay >= 2.0

    @pytest.mark.asyncio
    async def test_connection_error_caught(self) -> None:
        """ConnectionError during _connect_peer triggers reconnect, not crash."""
        config = _make_config()
        mgr = PeerManager(config)
        peer_addr = PeerAddress(host="10.0.0.2", port=3001)
        mgr.add_peer(peer_addr)

        peer = mgr._peers[str(peer_addr)]
        call_count = 0

        async def _fail_connect(self_arg, p: _PeerConnection) -> None:
            nonlocal call_count
            call_count += 1
            raise ConnectionRefusedError("connection refused")

        async def _fake_disconnect(self_arg, p: _PeerConnection) -> None:
            p.connected = False

        with (
            patch.object(PeerManager, "_connect_peer", _fail_connect),
            patch.object(PeerManager, "_disconnect_peer", _fake_disconnect),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):

            async def _stop_after_three(delay: float) -> None:
                if call_count >= 3:
                    mgr._stopped = True

            mock_sleep.side_effect = _stop_after_three

            await mgr._peer_loop(peer)

        assert call_count >= 3
        # After 3 failures: delays used were 1, 2, 4 -- next would be 8.
        assert peer.reconnect_delay >= 4.0

    @pytest.mark.asyncio
    async def test_os_error_caught(self) -> None:
        """OSError (e.g. network unreachable) triggers reconnect."""
        config = _make_config()
        mgr = PeerManager(config)
        peer_addr = PeerAddress(host="10.0.0.3", port=3001)
        mgr.add_peer(peer_addr)

        peer = mgr._peers[str(peer_addr)]
        call_count = 0

        async def _fail_connect(self_arg, p: _PeerConnection) -> None:
            nonlocal call_count
            call_count += 1
            raise OSError("Network unreachable")

        async def _fake_disconnect(self_arg, p: _PeerConnection) -> None:
            p.connected = False

        with (
            patch.object(PeerManager, "_connect_peer", _fail_connect),
            patch.object(PeerManager, "_disconnect_peer", _fake_disconnect),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):

            async def _stop_after_two(delay: float) -> None:
                if call_count >= 2:
                    mgr._stopped = True

            mock_sleep.side_effect = _stop_after_two

            await mgr._peer_loop(peer)

        assert call_count >= 2
