"""Tests for the peer registry used by the peer sharing protocol.

Verifies add/remove lifecycle, duplicate handling, deterministic salt-based
selection, policy caps, exclusion, and salt rotation behavior.

Haskell reference:
    computePeerSharingPeers in Ouroboros.Network.PeerSharing
"""

from __future__ import annotations

import pytest

from vibe.cardano.node.peer_registry import PeerAddress, PeerRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_peer(i: int) -> PeerAddress:
    """Create a unique peer address for testing."""
    return PeerAddress(ip=f"192.168.1.{i}", port=3000 + i)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAddRemovePeers:
    """Add/remove lifecycle."""

    def test_add_remove_peers(self) -> None:
        """Add 3 peers, verify count, remove 1, verify count."""
        reg = PeerRegistry()
        peers = [_make_peer(i) for i in range(3)]
        for p in peers:
            reg.add_peer(p)
        assert reg.peer_count == 3

        reg.remove_peer(peers[1])
        assert reg.peer_count == 2

    def test_add_duplicate_peer(self) -> None:
        """Adding the same peer twice does not increase count."""
        reg = PeerRegistry()
        p = _make_peer(0)
        reg.add_peer(p)
        reg.add_peer(p)
        assert reg.peer_count == 1

    def test_remove_nonexistent_peer(self) -> None:
        """Removing a peer that was never added is a no-op."""
        reg = PeerRegistry()
        reg.remove_peer(_make_peer(99))
        assert reg.peer_count == 0


class TestGetPeers:
    """Selection logic: amount, caps, determinism, exclusion."""

    def test_get_peers_respects_amount(self) -> None:
        """Add 20 peers, request 5, get exactly 5."""
        reg = PeerRegistry()
        for i in range(20):
            reg.add_peer(_make_peer(i))
        result = reg.get_peers(5)
        assert len(result) == 5

    def test_get_peers_capped_at_policy_max(self) -> None:
        """Add 20 peers, request 255, get at most POLICY_MAX_PEERS (10)."""
        reg = PeerRegistry()
        for i in range(20):
            reg.add_peer(_make_peer(i))
        result = reg.get_peers(255)
        assert len(result) == PeerRegistry.POLICY_MAX_PEERS

    def test_get_peers_returns_fewer_if_not_enough(self) -> None:
        """Add 3 peers, request 10, get 3."""
        reg = PeerRegistry()
        for i in range(3):
            reg.add_peer(_make_peer(i))
        result = reg.get_peers(10)
        assert len(result) == 3

    def test_get_peers_empty_registry(self) -> None:
        """Empty registry returns empty list."""
        reg = PeerRegistry()
        result = reg.get_peers(10)
        assert result == []

    def test_get_peers_excludes_requesting_peer(self) -> None:
        """Add peer A and B, exclude A, only get B."""
        reg = PeerRegistry()
        a = PeerAddress(ip="10.0.0.1", port=3001)
        b = PeerAddress(ip="10.0.0.2", port=3002)
        reg.add_peer(a)
        reg.add_peer(b)
        result = reg.get_peers(10, exclude=a)
        assert result == [b]


class TestDeterminism:
    """Salt-based deterministic selection and rotation."""

    def test_get_peers_deterministic_with_same_salt(self) -> None:
        """Two consecutive calls return the same peers (salt hasn't rotated)."""
        reg = PeerRegistry()
        for i in range(20):
            reg.add_peer(_make_peer(i))
        first = reg.get_peers(5)
        second = reg.get_peers(5)
        assert first == second

    def test_get_peers_changes_after_salt_rotation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After salt rotation, a different selection is returned.

        We add enough peers (50) to make it very likely that a different
        salt produces a different ordering of the first 5.
        """
        import time as time_mod

        reg = PeerRegistry()
        for i in range(50):
            reg.add_peer(_make_peer(i))

        # Capture the initial selection.
        first = reg.get_peers(5)

        # Advance monotonic time past the sticky window to force rotation.
        original_monotonic = time_mod.monotonic
        offset = PeerRegistry.POLICY_STICKY_TIME + 1.0

        monkeypatch.setattr(
            time_mod,
            "monotonic",
            lambda: original_monotonic() + offset,
        )

        second = reg.get_peers(5)

        # With 50 peers and a new random salt, the probability of getting
        # the exact same 5 peers in the same order is astronomically low.
        assert first != second


class TestPeerCount:
    """The peer_count property."""

    def test_peer_count_property(self) -> None:
        """peer_count reflects the actual number of registered peers."""
        reg = PeerRegistry()
        assert reg.peer_count == 0

        peers = [_make_peer(i) for i in range(5)]
        for i, p in enumerate(peers, 1):
            reg.add_peer(p)
            assert reg.peer_count == i

        for i, p in enumerate(peers):
            reg.remove_peer(p)
            assert reg.peer_count == 5 - i - 1
