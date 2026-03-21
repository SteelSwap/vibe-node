"""Connection manager state-transition tests -- peer lifecycle state machine.

Defines a PeerState enum and PeerManagerSM that models the Haskell node's
connection manager state machine. Tests valid and invalid transitions,
pruning, and exponential backoff.

Haskell ref:
    Ouroboros.Network.ConnectionManager.Types -- ConnectionState
    (OutboundIdleState, OutboundUniState, InboundIdleState, etc.)

    The Haskell node uses a formal state machine for connection lifecycle:
    - Reserving -> UnnegotiatedState -> OutboundUniState / DuplexState
    - With explicit transition guards (e.g., can't go from idle to established
      without a handshake).

    Our simplified model captures the essential invariants:
    - Must go through CONNECTING to reach CONNECTED
    - Must disconnect before re-connecting
    - Cooling-off period before reconnect after errors

Spec ref:
    Ouroboros network spec, Chapter 2 -- connection management
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field

import pytest


# ---------------------------------------------------------------------------
# State machine model (test-only, not production code)
# ---------------------------------------------------------------------------


class PeerState(enum.Enum):
    """Simplified connection states for a peer.

    Maps to Haskell's ConnectionState:
        DISCONNECTED ~ ReservedOutboundState / TerminatedState
        CONNECTING   ~ UnnegotiatedState (handshake in progress)
        CONNECTED    ~ OutboundUniState / DuplexState (established)
        COOLING_OFF  ~ post-disconnect backoff (not in Haskell's SM
                       directly, but modelled by the governor's backoff logic)
    """
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    COOLING_OFF = "cooling_off"


# Valid transitions: from_state -> {allowed_to_states}
VALID_TRANSITIONS: dict[PeerState, set[PeerState]] = {
    PeerState.DISCONNECTED: {PeerState.CONNECTING},
    PeerState.CONNECTING: {PeerState.CONNECTED, PeerState.DISCONNECTED},
    PeerState.CONNECTED: {PeerState.DISCONNECTED, PeerState.COOLING_OFF},
    PeerState.COOLING_OFF: {PeerState.CONNECTING},
}


class InvalidTransitionError(Exception):
    """Raised when a state transition violates the state machine."""


@dataclass
class PeerInfo:
    """Tracks a single peer's connection state and backoff metadata."""

    peer_id: str
    state: PeerState = PeerState.DISCONNECTED
    last_connected: float = 0.0
    failure_count: int = 0
    backoff_until: float = 0.0

    def transition_to(self, new_state: PeerState) -> None:
        """Transition to a new state, validating against VALID_TRANSITIONS.

        Raises:
            InvalidTransitionError: If the transition is not allowed.
        """
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Cannot transition from {self.state.value} to {new_state.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
        self.state = new_state


class PeerManagerSM:
    """Simplified connection manager state machine for testing.

    Models the essential peer lifecycle operations:
    connect, connected, disconnect, prune, backoff.
    """

    BACKOFF_BASE: float = 1.0
    BACKOFF_CAP: float = 60.0

    def __init__(self) -> None:
        self._peers: dict[str, PeerInfo] = {}

    def add_peer(self, peer_id: str) -> PeerInfo:
        info = PeerInfo(peer_id=peer_id)
        self._peers[peer_id] = info
        return info

    def get_peer(self, peer_id: str) -> PeerInfo:
        return self._peers[peer_id]

    def connect(self, peer_id: str) -> None:
        """Initiate connection: DISCONNECTED -> CONNECTING."""
        peer = self._peers[peer_id]
        peer.transition_to(PeerState.CONNECTING)

    def connected(self, peer_id: str) -> None:
        """Handshake succeeded: CONNECTING -> CONNECTED."""
        peer = self._peers[peer_id]
        peer.transition_to(PeerState.CONNECTED)
        peer.last_connected = time.monotonic()
        peer.failure_count = 0  # Reset backoff on success

    def disconnect(self, peer_id: str) -> None:
        """Clean disconnect: CONNECTED/CONNECTING -> DISCONNECTED."""
        peer = self._peers[peer_id]
        peer.transition_to(PeerState.DISCONNECTED)

    def prune(self, *, max_idle: float, now: float | None = None) -> list[str]:
        """Remove peers that have been connected longer than max_idle.

        Returns list of pruned peer_ids.
        """
        if now is None:
            now = time.monotonic()
        pruned: list[str] = []
        for peer_id, peer in list(self._peers.items()):
            if peer.state == PeerState.CONNECTED:
                idle_time = now - peer.last_connected
                if idle_time > max_idle:
                    peer.transition_to(PeerState.DISCONNECTED)
                    pruned.append(peer_id)
        return pruned

    def backoff(self, peer_id: str) -> float:
        """Move CONNECTED -> COOLING_OFF and compute backoff duration.

        Returns the backoff duration in seconds.
        """
        peer = self._peers[peer_id]
        peer.transition_to(PeerState.COOLING_OFF)
        peer.failure_count += 1
        duration = min(
            self.BACKOFF_BASE * (2 ** (peer.failure_count - 1)),
            self.BACKOFF_CAP,
        )
        peer.backoff_until = time.monotonic() + duration
        return duration

    def reconnect_after_cooloff(self, peer_id: str) -> None:
        """COOLING_OFF -> CONNECTING (after backoff timer expires)."""
        peer = self._peers[peer_id]
        peer.transition_to(PeerState.CONNECTING)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidConnectFlow:
    """Test the happy-path lifecycle: DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED."""

    def test_full_lifecycle(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")

        mgr.connect("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.CONNECTING

        mgr.connected("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.CONNECTED

        mgr.disconnect("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.DISCONNECTED


class TestConnectFailure:
    """CONNECTING -> DISCONNECTED on connection failure."""

    def test_connecting_to_disconnected(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")

        mgr.connect("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.CONNECTING

        # Simulate connection failure -- back to disconnected
        mgr.disconnect("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.DISCONNECTED


class TestCoolingOff:
    """CONNECTED -> COOLING_OFF -> CONNECTING (backoff then reconnect)."""

    def test_cooling_off_cycle(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")

        mgr.connect("peer-1")
        mgr.connected("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.CONNECTED

        # Error triggers cooling off
        duration = mgr.backoff("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.COOLING_OFF
        assert duration > 0

        # After cooling off, reconnect
        mgr.reconnect_after_cooloff("peer-1")
        assert mgr.get_peer("peer-1").state == PeerState.CONNECTING


class TestInvalidDisconnectedToConnected:
    """DISCONNECTED -> CONNECTED is invalid (must go through CONNECTING)."""

    def test_skip_connecting_raises(self) -> None:
        mgr = PeerManagerSM()
        peer = mgr.add_peer("peer-1")

        assert peer.state == PeerState.DISCONNECTED
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            peer.transition_to(PeerState.CONNECTED)


class TestInvalidConnectedToConnecting:
    """CONNECTED -> CONNECTING is invalid (must disconnect first)."""

    def test_connected_to_connecting_raises(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")
        mgr.connect("peer-1")
        mgr.connected("peer-1")

        peer = mgr.get_peer("peer-1")
        assert peer.state == PeerState.CONNECTED
        with pytest.raises(InvalidTransitionError, match="Cannot transition"):
            peer.transition_to(PeerState.CONNECTING)


class TestAllValidTransitions:
    """Every transition in VALID_TRANSITIONS succeeds."""

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (src, dst)
            for src, dsts in VALID_TRANSITIONS.items()
            for dst in dsts
        ],
    )
    def test_valid_transition_succeeds(
        self, from_state: PeerState, to_state: PeerState
    ) -> None:
        peer = PeerInfo(peer_id="test", state=from_state)
        peer.transition_to(to_state)
        assert peer.state == to_state


class TestAllInvalidTransitions:
    """Every transition NOT in VALID_TRANSITIONS raises InvalidTransitionError."""

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (src, dst)
            for src in PeerState
            for dst in PeerState
            if dst not in VALID_TRANSITIONS.get(src, set()) and src != dst
        ],
    )
    def test_invalid_transition_raises(
        self, from_state: PeerState, to_state: PeerState
    ) -> None:
        peer = PeerInfo(peer_id="test", state=from_state)
        with pytest.raises(InvalidTransitionError):
            peer.transition_to(to_state)


class TestPruneInactivePeers:
    """Prune peers that have been idle beyond a timeout."""

    def test_prune_after_timeout(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("active")
        mgr.add_peer("stale")

        # Both connect
        for pid in ("active", "stale"):
            mgr.connect(pid)
            mgr.connected(pid)

        # Backdate the stale peer's last_connected
        now = time.monotonic()
        mgr.get_peer("stale").last_connected = now - 120  # 2 min ago
        mgr.get_peer("active").last_connected = now - 5   # 5s ago

        pruned = mgr.prune(max_idle=60, now=now)

        assert "stale" in pruned
        assert "active" not in pruned
        assert mgr.get_peer("stale").state == PeerState.DISCONNECTED
        assert mgr.get_peer("active").state == PeerState.CONNECTED


class TestExponentialBackoff:
    """Backoff durations follow 1s, 2s, 4s, 8s, ..., capped at 60s, reset on success.

    Haskell ref:
        Ouroboros.Network.PeerSelection.Governor.ActivePeers -- the governor
        uses exponential backoff with a cap for peer reconnection delays.
    """

    def test_backoff_sequence_and_cap(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")

        expected_durations = [1, 2, 4, 8, 16, 32, 60, 60]

        for expected in expected_durations:
            # Bring peer to CONNECTED so we can trigger backoff
            peer = mgr.get_peer("peer-1")
            if peer.state == PeerState.COOLING_OFF:
                mgr.reconnect_after_cooloff("peer-1")
            if peer.state == PeerState.DISCONNECTED:
                mgr.connect("peer-1")
            if peer.state == PeerState.CONNECTING:
                # Simulate connected briefly then error
                mgr.connected("peer-1")
                # Preserve failure_count across the connected call
                # connected() resets failure_count, so we need to
                # track it separately
            # Actually: connected() resets failure_count, which is
            # the correct behavior for "success resets". For the
            # backoff escalation test we need consecutive failures
            # without a successful connection in between.
            pass

        # Reset and test properly: consecutive failures without success
        mgr2 = PeerManagerSM()
        mgr2.add_peer("peer-1")
        peer = mgr2.get_peer("peer-1")

        expected_durations = [1, 2, 4, 8, 16, 32, 60, 60]
        for expected in expected_durations:
            # Manually set state to CONNECTED to simulate the backoff trigger
            peer.state = PeerState.CONNECTED
            duration = mgr2.backoff("peer-1")
            assert duration == expected, (
                f"Expected {expected}s backoff, got {duration}s "
                f"(failure_count={peer.failure_count})"
            )

    def test_backoff_resets_on_success(self) -> None:
        mgr = PeerManagerSM()
        mgr.add_peer("peer-1")
        peer = mgr.get_peer("peer-1")

        # Rack up failures
        for _ in range(5):
            peer.state = PeerState.CONNECTED
            mgr.backoff("peer-1")

        assert peer.failure_count == 5

        # Successful connection resets
        peer.state = PeerState.CONNECTING  # simulate reconnect from cooling_off
        mgr.connected("peer-1")
        assert peer.failure_count == 0

        # Next backoff should start from 1s again
        mgr.backoff("peer-1")
        assert peer.failure_count == 1
