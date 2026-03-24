"""Tests for the tx-submission decision engine logic.

These 13 tests correspond to the Haskell property-based tests from
ouroboros-network-protocols that exercise SharedTxState, peer selection,
tx acknowledgment, and the decision engine that drives which transactions
to request from which peers.

Since our implementation doesn't have a separate SharedTxState class
(the state is managed inline in run_tx_submission_server), we build a
minimal SharedTxState model here and test the decision logic through it.
This mirrors the Haskell test structure while testing the same invariants.

Haskell references:
    Test.Ouroboros.Network.TxSubmission (prop_*)
    Ouroboros.Network.TxSubmission.Inbound (SharedTxState, makeDecisions)
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from vibe.core.protocols.agency import PeerRole
from vibe.core.protocols.runner import ProtocolRunner

from vibe.cardano.network.txsubmission_protocol import (
    TxSubmissionState,
    TxSubmissionProtocol,
    TxSubmissionCodec,
    TsMsgInit,
    TsMsgRequestTxIds,
    TsMsgReplyTxIds,
    TsMsgRequestTxs,
    TsMsgReplyTxs,
    TsMsgDone,
    TxSubmissionClient,
    run_tx_submission_server,
)


# ---------------------------------------------------------------------------
# SharedTxState -- decision engine model
#
# The Haskell tx-submission decision engine maintains a SharedTxState that
# tracks per-peer outstanding tx IDs, in-flight requests, acknowledged IDs,
# and mempool state. Our implementation handles this inline, so we build
# an equivalent model for testing the decision logic.
# ---------------------------------------------------------------------------

# Policy constants (matching Haskell defaults)
MAX_UNACKED_TX_IDS = 10  # maxUnackedTxIds
MAX_TX_IDS_TO_REQUEST = 3  # maxTxIdsToRequest
MAX_TXS_IN_FLIGHT = 10  # maxTxsInFlight


@dataclass
class PeerTxState:
    """Per-peer tx-submission state.

    Haskell ref: PeerTxState in Ouroboros.Network.TxSubmission.Inbound
    """

    #: Tx IDs we've been told about by this peer (announced but not yet requested)
    available_tx_ids: dict[bytes, int] = field(default_factory=dict)

    #: Tx IDs we've requested from this peer but haven't received yet
    requested_tx_ids: set[bytes] = field(default_factory=set)

    #: Tx IDs we've acknowledged (told the peer we processed)
    acknowledged_tx_ids: list[bytes] = field(default_factory=list)

    #: Total number of unacknowledged tx IDs (outstanding window)
    unacked_count: int = 0


@dataclass
class SharedTxState:
    """Shared state for the tx-submission decision engine.

    Models the Haskell SharedTxState from
    Ouroboros.Network.TxSubmission.Inbound.

    Tracks per-peer state, known tx IDs, in-flight requests, and the
    mempool integration point.
    """

    #: Per-peer state
    peers: dict[str, PeerTxState] = field(default_factory=dict)

    #: Tx IDs that are already in the mempool (no need to request)
    mempool_tx_ids: set[bytes] = field(default_factory=set)

    #: Tx IDs currently in-flight (requested from any peer)
    in_flight_tx_ids: set[bytes] = field(default_factory=set)

    #: All known tx IDs (from all peers)
    known_tx_ids: set[bytes] = field(default_factory=set)

    #: Buffered transactions received but not yet written to mempool
    buffered_txs: dict[bytes, bytes] = field(default_factory=dict)

    def add_peer(self, peer_id: str) -> None:
        """Register a new peer."""
        self.peers[peer_id] = PeerTxState()

    def remove_peer(self, peer_id: str) -> None:
        """Remove a peer and clean up its state."""
        if peer_id in self.peers:
            peer = self.peers[peer_id]
            # Remove in-flight txs that were only from this peer
            self.in_flight_tx_ids -= peer.requested_tx_ids
            del self.peers[peer_id]

    def receive_tx_ids(
        self, peer_id: str, tx_ids: list[tuple[bytes, int]]
    ) -> None:
        """Record tx IDs announced by a peer.

        Haskell ref: receivedTxIdsImpl
        """
        if peer_id not in self.peers:
            return
        peer = self.peers[peer_id]
        for txid, size in tx_ids:
            # Skip if already acknowledged (prevents invariant 4 violation)
            if txid in peer.acknowledged_tx_ids:
                continue
            peer.available_tx_ids[txid] = size
            peer.unacked_count += 1
            self.known_tx_ids.add(txid)

    def acknowledge_tx_ids(self, peer_id: str, count: int) -> list[bytes]:
        """Acknowledge (consume) tx IDs from a peer's outstanding set.

        Returns the acknowledged tx IDs. These are removed from the peer's
        outstanding count and tracked for the next MsgRequestTxIds ack_count.

        Haskell ref: acknowledgeTxIds
        """
        if peer_id not in self.peers:
            return []
        peer = self.peers[peer_id]
        # Acknowledge the oldest `count` tx IDs
        acked = list(peer.available_tx_ids.keys())[:count]
        for txid in acked:
            del peer.available_tx_ids[txid]
            peer.unacked_count -= 1
        peer.acknowledged_tx_ids.extend(acked)
        return acked

    def split_acknowledged_tx_ids(
        self, peer_id: str
    ) -> tuple[list[bytes], list[bytes]]:
        """Split acknowledged tx IDs into those in mempool and those not.

        Returns (in_mempool, not_in_mempool).

        Haskell ref: splitAcknowledgedTxIds
        """
        if peer_id not in self.peers:
            return [], []
        peer = self.peers[peer_id]
        in_mempool = [
            txid
            for txid in peer.acknowledged_tx_ids
            if txid in self.mempool_tx_ids
        ]
        not_in_mempool = [
            txid
            for txid in peer.acknowledged_tx_ids
            if txid not in self.mempool_tx_ids
        ]
        return in_mempool, not_in_mempool

    def collect_txs(self, peer_id: str) -> list[bytes]:
        """Decide which txs to request from a peer.

        Returns tx IDs to request, following the policy:
        - Don't request txs already in mempool
        - Don't request txs already in-flight from any peer
        - Don't request txs already requested by this peer
        - Respect max_txs_in_flight limit

        Haskell ref: collectTxsImpl
        """
        if peer_id not in self.peers:
            return []
        peer = self.peers[peer_id]

        to_request: list[bytes] = []
        for txid in peer.available_tx_ids:
            if txid in self.mempool_tx_ids:
                continue
            if txid in self.in_flight_tx_ids:
                continue
            if txid in peer.requested_tx_ids:
                continue
            if txid in self.buffered_txs:
                continue
            if len(self.in_flight_tx_ids) + len(to_request) >= MAX_TXS_IN_FLIGHT:
                break
            to_request.append(txid)

        # Mark as in-flight
        for txid in to_request:
            self.in_flight_tx_ids.add(txid)
            peer.requested_tx_ids.add(txid)

        return to_request

    def receive_txs(
        self, peer_id: str, txs: dict[bytes, bytes]
    ) -> None:
        """Record received transactions from a peer.

        Haskell ref: part of the decision loop
        """
        if peer_id not in self.peers:
            return
        peer = self.peers[peer_id]
        for txid, tx_body in txs.items():
            self.buffered_txs[txid] = tx_body
            self.in_flight_tx_ids.discard(txid)
            peer.requested_tx_ids.discard(txid)

    def write_mempool(self) -> list[bytes]:
        """Write buffered transactions to the mempool.

        Returns list of tx IDs written. Also cleans up in-flight and
        per-peer requested sets to maintain invariants.

        Haskell ref: mempoolWriter
        """
        written = list(self.buffered_txs.keys())
        for txid in written:
            self.mempool_tx_ids.add(txid)
            # Clean up in-flight tracking (invariant: no overlap mempool/in-flight)
            self.in_flight_tx_ids.discard(txid)
            for peer in self.peers.values():
                peer.requested_tx_ids.discard(txid)
        self.buffered_txs.clear()
        return written

    def make_decisions(self) -> list[tuple[str, str, Any]]:
        """Make decisions about what to request from each peer.

        Returns a list of (peer_id, action, data) tuples where action is:
        - "request_tx_ids": request more tx IDs (data = (blocking, ack_count, req_count))
        - "request_txs": request specific txs (data = list of txids)

        Haskell ref: makeDecisions
        """
        decisions: list[tuple[str, str, Any]] = []

        for peer_id, peer in self.peers.items():
            # Decision 1: Request tx IDs if the peer's window is low
            if peer.unacked_count < MAX_UNACKED_TX_IDS:
                space = MAX_UNACKED_TX_IDS - peer.unacked_count
                req_count = min(space, MAX_TX_IDS_TO_REQUEST)
                if req_count > 0:
                    blocking = len(peer.available_tx_ids) == 0
                    ack_count = len(peer.acknowledged_tx_ids)
                    decisions.append(
                        (
                            peer_id,
                            "request_tx_ids",
                            (blocking, ack_count, req_count),
                        )
                    )

            # Decision 2: Request txs for available tx IDs not yet requested
            to_request = []
            for txid in peer.available_tx_ids:
                if txid in self.mempool_tx_ids:
                    continue
                if txid in self.in_flight_tx_ids:
                    continue
                if txid in peer.requested_tx_ids:
                    continue
                if (
                    len(self.in_flight_tx_ids) + len(to_request)
                    >= MAX_TXS_IN_FLIGHT
                ):
                    break
                to_request.append(txid)

            if to_request:
                decisions.append((peer_id, "request_txs", to_request))
                # Mark as in-flight
                for txid in to_request:
                    self.in_flight_tx_ids.add(txid)
                    peer.requested_tx_ids.add(txid)

        return decisions

    def active_peers(self) -> set[str]:
        """Return the set of peers that have available or in-flight txs.

        Haskell ref: filterActivePeers
        """
        return {
            peer_id
            for peer_id, peer in self.peers.items()
            if peer.available_tx_ids or peer.requested_tx_ids
        }

    def check_invariant(self) -> bool:
        """Verify the SharedTxState invariant holds.

        Haskell ref: sharedTxStateInvariant

        Invariants:
        1. All in-flight txs must be tracked by exactly one peer
        2. No tx ID appears in both mempool and in-flight
        3. Per-peer unacked count matches available_tx_ids length
        4. No acknowledged tx ID appears in available_tx_ids
        """
        # Invariant 1: in-flight txs tracked by at least one peer
        all_peer_requested = set()
        for peer in self.peers.values():
            all_peer_requested |= peer.requested_tx_ids
        if not self.in_flight_tx_ids.issubset(all_peer_requested):
            return False

        # Invariant 2: no overlap between mempool and in-flight
        if self.mempool_tx_ids & self.in_flight_tx_ids:
            return False

        # Invariant 3: unacked count consistency
        for peer in self.peers.values():
            if peer.unacked_count != len(peer.available_tx_ids):
                return False

        # Invariant 4: no acknowledged tx in available set
        for peer in self.peers.values():
            acked_set = set(peer.acknowledged_tx_ids)
            if acked_set & set(peer.available_tx_ids.keys()):
                return False

        return True


# ---------------------------------------------------------------------------
# Mock channel for async direct tests
# ---------------------------------------------------------------------------


@dataclass
class MockChannel:
    """In-memory bidirectional channel for direct client-server tests."""

    _a_to_b: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _b_to_a: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)

    @property
    def client_side(self) -> "_MockChannelEnd":
        return _MockChannelEnd(send_q=self._a_to_b, recv_q=self._b_to_a)

    @property
    def server_side(self) -> "_MockChannelEnd":
        return _MockChannelEnd(send_q=self._b_to_a, recv_q=self._a_to_b)


@dataclass
class _MockChannelEnd:
    send_q: asyncio.Queue[bytes]
    recv_q: asyncio.Queue[bytes]

    async def send(self, payload: bytes) -> None:
        await self.send_q.put(payload)

    async def recv(self) -> bytes:
        return await self.recv_q.get()


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

txid_strategy = st.binary(min_size=32, max_size=32)
size_strategy = st.integers(min_value=1, max_value=65535)
txid_size_pair = st.tuples(txid_strategy, size_strategy)
peer_id_strategy = st.text(
    alphabet="abcdefghijklmnop", min_size=1, max_size=8
)


@st.composite
def shared_tx_state_strategy(draw: st.DrawFn) -> SharedTxState:
    """Generate a valid SharedTxState for property testing.

    Haskell ref: prop_SharedTxState_generator
    """
    state = SharedTxState()
    num_peers = draw(st.integers(min_value=1, max_value=5))
    peer_ids = [f"peer_{i}" for i in range(num_peers)]

    for pid in peer_ids:
        state.add_peer(pid)

    # Generate some tx IDs known across the system
    num_txs = draw(st.integers(min_value=0, max_value=20))
    all_tx_ids = [draw(txid_strategy) for _ in range(num_txs)]

    # Deduplicate
    unique_txids = list(set(all_tx_ids))

    # Some go to mempool
    mempool_count = draw(
        st.integers(min_value=0, max_value=max(0, len(unique_txids) // 3))
    )
    mempool_txids = unique_txids[:mempool_count]
    state.mempool_tx_ids = set(mempool_txids)

    # Remaining get distributed to peers as available
    remaining = unique_txids[mempool_count:]
    for txid in remaining:
        # Assign to a random peer
        pid = draw(st.sampled_from(peer_ids))
        sz = draw(size_strategy)
        state.peers[pid].available_tx_ids[txid] = sz
        state.peers[pid].unacked_count = len(
            state.peers[pid].available_tx_ids
        )
        state.known_tx_ids.add(txid)

    return state


# Increase max_examples in CI, keep fast locally
_MAX_EXAMPLES = int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "50"))


# ---------------------------------------------------------------------------
# Test 1: prop_acknowledgeTxIds
# ---------------------------------------------------------------------------


class TestAcknowledgeTxIds:
    """Acknowledging tx IDs removes them from the outstanding set.

    Haskell ref: prop_acknowledgeTxIds
    """

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_acknowledge_removes_from_outstanding(
        self, data: st.DataObject
    ) -> None:
        state = SharedTxState()
        state.add_peer("peer_0")

        # Announce some tx IDs
        num_txs = data.draw(st.integers(min_value=1, max_value=10))
        tx_ids = [
            (data.draw(txid_strategy), data.draw(size_strategy))
            for _ in range(num_txs)
        ]
        # Ensure unique tx IDs
        seen = set()
        unique_tx_ids = []
        for txid, sz in tx_ids:
            if txid not in seen:
                seen.add(txid)
                unique_tx_ids.append((txid, sz))
        tx_ids = unique_tx_ids

        state.receive_tx_ids("peer_0", tx_ids)
        initial_count = state.peers["peer_0"].unacked_count
        assert initial_count == len(tx_ids)

        # Acknowledge some
        ack_count = data.draw(
            st.integers(min_value=0, max_value=len(tx_ids))
        )
        acked = state.acknowledge_tx_ids("peer_0", ack_count)

        # Verify acknowledgment
        assert len(acked) == ack_count
        assert state.peers["peer_0"].unacked_count == initial_count - ack_count

        # Acknowledged tx IDs should not be in available set
        for txid in acked:
            assert txid not in state.peers["peer_0"].available_tx_ids

    def test_acknowledge_nonexistent_peer(self) -> None:
        """Acknowledging tx IDs for a non-existent peer returns empty list."""
        state = SharedTxState()
        result = state.acknowledge_tx_ids("ghost_peer", 5)
        assert result == []

    def test_acknowledge_zero(self) -> None:
        """Acknowledging zero tx IDs is a no-op."""
        state = SharedTxState()
        state.add_peer("peer_0")
        state.receive_tx_ids("peer_0", [(b"\x01" * 32, 100)])
        acked = state.acknowledge_tx_ids("peer_0", 0)
        assert acked == []
        assert state.peers["peer_0"].unacked_count == 1


# ---------------------------------------------------------------------------
# Test 2: prop_collectTxsImpl
# ---------------------------------------------------------------------------


class TestCollectTxsImpl:
    """Collecting txs from peers follows policy constraints.

    Haskell ref: prop_collectTxsImpl
    """

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_collect_respects_mempool(self, data: st.DataObject) -> None:
        """Txs already in mempool are not collected."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid_in_mempool = data.draw(txid_strategy)
        txid_not_in_mempool = data.draw(txid_strategy)
        assume(txid_in_mempool != txid_not_in_mempool)

        state.mempool_tx_ids.add(txid_in_mempool)
        state.receive_tx_ids(
            "peer_0",
            [(txid_in_mempool, 100), (txid_not_in_mempool, 200)],
        )

        collected = state.collect_txs("peer_0")
        assert txid_in_mempool not in collected
        assert txid_not_in_mempool in collected

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_collect_respects_in_flight(self, data: st.DataObject) -> None:
        """Txs already in-flight from another peer are not collected."""
        state = SharedTxState()
        state.add_peer("peer_0")
        state.add_peer("peer_1")

        txid_shared = data.draw(txid_strategy)
        txid_unique = data.draw(txid_strategy)
        assume(txid_shared != txid_unique)

        # peer_0 announces both, peer_1 also has shared one
        state.receive_tx_ids(
            "peer_0", [(txid_shared, 100), (txid_unique, 200)]
        )
        state.receive_tx_ids("peer_1", [(txid_shared, 100)])

        # Collect from peer_1 first (puts txid_shared in-flight)
        collected_1 = state.collect_txs("peer_1")
        assert txid_shared in collected_1

        # Now collect from peer_0 -- txid_shared should be skipped
        collected_0 = state.collect_txs("peer_0")
        assert txid_shared not in collected_0
        assert txid_unique in collected_0

    def test_collect_respects_max_in_flight(self) -> None:
        """Collection stops when max_txs_in_flight is reached."""
        state = SharedTxState()
        state.add_peer("peer_0")

        # Announce more txs than MAX_TXS_IN_FLIGHT
        tx_ids = [(bytes([i]) * 32, 100) for i in range(MAX_TXS_IN_FLIGHT + 5)]
        state.receive_tx_ids("peer_0", tx_ids)

        collected = state.collect_txs("peer_0")
        assert len(collected) <= MAX_TXS_IN_FLIGHT

    def test_collect_from_nonexistent_peer(self) -> None:
        """Collecting from non-existent peer returns empty list."""
        state = SharedTxState()
        assert state.collect_txs("ghost") == []


# ---------------------------------------------------------------------------
# Test 3: prop_makeDecisions_acknowledged
# ---------------------------------------------------------------------------


class TestMakeDecisionsAcknowledged:
    """Decisions respect acknowledged state.

    Haskell ref: prop_makeDecisions_acknowledged
    """

    def test_decisions_include_ack_count(self) -> None:
        """When tx IDs have been acknowledged, the ack_count in decisions
        reflects the number of acknowledged IDs."""
        state = SharedTxState()
        state.add_peer("peer_0")

        # Announce and acknowledge some tx IDs
        tx_ids = [(bytes([i]) * 32, 100) for i in range(5)]
        state.receive_tx_ids("peer_0", tx_ids)
        state.acknowledge_tx_ids("peer_0", 3)

        decisions = state.make_decisions()

        # Find the request_tx_ids decision for peer_0
        req_decisions = [
            (pid, action, data)
            for pid, action, data in decisions
            if pid == "peer_0" and action == "request_tx_ids"
        ]
        assert len(req_decisions) >= 1
        _, _, (blocking, ack_count, req_count) = req_decisions[0]
        assert ack_count == 3  # We acknowledged 3 tx IDs

    def test_acknowledged_not_re_requested(self) -> None:
        """Acknowledged tx IDs are not included in tx request decisions."""
        state = SharedTxState()
        state.add_peer("peer_0")

        tx_ids = [(bytes([i]) * 32, 100) for i in range(5)]
        state.receive_tx_ids("peer_0", tx_ids)

        # Acknowledge all
        state.acknowledge_tx_ids("peer_0", 5)

        decisions = state.make_decisions()

        # No request_txs decisions since all are acknowledged (removed from available)
        request_txs = [
            d for d in decisions if d[1] == "request_txs" and d[0] == "peer_0"
        ]
        assert len(request_txs) == 0


# ---------------------------------------------------------------------------
# Test 4: prop_makeDecisions_exhaustive
# ---------------------------------------------------------------------------


class TestMakeDecisionsExhaustive:
    """All peers get serviced by the decision engine.

    Haskell ref: prop_makeDecisions_exhaustive
    """

    def test_all_peers_get_decisions(self) -> None:
        """Every peer with available tx IDs gets at least one decision."""
        state = SharedTxState()

        for i in range(5):
            pid = f"peer_{i}"
            state.add_peer(pid)
            state.receive_tx_ids(pid, [(bytes([i]) * 32, 100)])

        decisions = state.make_decisions()

        # Every peer should have at least one decision
        peers_with_decisions = {pid for pid, _, _ in decisions}
        for i in range(5):
            assert f"peer_{i}" in peers_with_decisions

    def test_idle_peers_get_blocking_request(self) -> None:
        """Peers with no available tx IDs get a blocking request for more."""
        state = SharedTxState()
        state.add_peer("peer_0")
        # Peer has no available tx IDs

        decisions = state.make_decisions()

        req_ids = [
            d
            for d in decisions
            if d[0] == "peer_0" and d[1] == "request_tx_ids"
        ]
        assert len(req_ids) == 1
        _, _, (blocking, _, _) = req_ids[0]
        assert blocking is True  # Blocking because no available txs


# ---------------------------------------------------------------------------
# Test 5: prop_makeDecisions_inflight
# ---------------------------------------------------------------------------


class TestMakeDecisionsInFlight:
    """In-flight tracking is correct across decisions.

    Haskell ref: prop_makeDecisions_inflight
    """

    def test_decisions_mark_in_flight(self) -> None:
        """After make_decisions, requested txs are marked in-flight."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])

        decisions = state.make_decisions()

        # The tx should now be in-flight
        request_txs = [d for d in decisions if d[1] == "request_txs"]
        if request_txs:
            assert txid in state.in_flight_tx_ids

    def test_in_flight_prevents_duplicate_requests(self) -> None:
        """Txs already in-flight are not re-requested from another peer."""
        state = SharedTxState()
        state.add_peer("peer_0")
        state.add_peer("peer_1")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])
        state.receive_tx_ids("peer_1", [(txid, 100)])

        # First round of decisions
        decisions1 = state.make_decisions()

        # txid is in-flight after first decisions
        assert txid in state.in_flight_tx_ids

        # Only one peer should have a request_txs for this txid
        request_txs = [
            (pid, data)
            for pid, action, data in decisions1
            if action == "request_txs"
        ]
        all_requested = []
        for _, tx_list in request_txs:
            all_requested.extend(tx_list)

        assert all_requested.count(txid) == 1

    def test_received_tx_clears_in_flight(self) -> None:
        """Receiving a tx clears it from in-flight."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])
        state.collect_txs("peer_0")

        assert txid in state.in_flight_tx_ids

        # Receive the tx
        state.receive_txs("peer_0", {txid: b"\xaa\xbb"})
        assert txid not in state.in_flight_tx_ids


# ---------------------------------------------------------------------------
# Test 6: prop_makeDecisions_policy
# ---------------------------------------------------------------------------


class TestMakeDecisionsPolicy:
    """Policy constraints are respected in decisions.

    Haskell ref: prop_makeDecisions_policy
    """

    def test_max_unacked_respected(self) -> None:
        """Decisions don't request more tx IDs than MAX_UNACKED_TX_IDS allows."""
        state = SharedTxState()
        state.add_peer("peer_0")

        # Fill up to max
        tx_ids = [
            (bytes([i]) * 32, 100) for i in range(MAX_UNACKED_TX_IDS)
        ]
        state.receive_tx_ids("peer_0", tx_ids)

        decisions = state.make_decisions()

        # No request_tx_ids decision since we're at max
        req_ids = [
            d
            for d in decisions
            if d[0] == "peer_0" and d[1] == "request_tx_ids"
        ]
        assert len(req_ids) == 0

    def test_request_count_bounded(self) -> None:
        """Request count in decisions is bounded by MAX_TX_IDS_TO_REQUEST."""
        state = SharedTxState()
        state.add_peer("peer_0")
        # Peer has no txs, so we request some
        decisions = state.make_decisions()

        req_ids = [
            d
            for d in decisions
            if d[0] == "peer_0" and d[1] == "request_tx_ids"
        ]
        if req_ids:
            _, _, (_, _, req_count) = req_ids[0]
            assert req_count <= MAX_TX_IDS_TO_REQUEST

    def test_max_in_flight_respected(self) -> None:
        """Decisions don't put more than MAX_TXS_IN_FLIGHT txs in flight."""
        state = SharedTxState()
        state.add_peer("peer_0")

        # Announce many txs
        tx_ids = [
            (bytes([i]) * 32, 100)
            for i in range(MAX_TXS_IN_FLIGHT + 10)
        ]
        state.receive_tx_ids("peer_0", tx_ids)

        state.make_decisions()

        assert len(state.in_flight_tx_ids) <= MAX_TXS_IN_FLIGHT


# ---------------------------------------------------------------------------
# Test 7: prop_makeDecisions_sharedstate
# ---------------------------------------------------------------------------


class TestMakeDecisionsSharedState:
    """Shared state invariants hold after making decisions.

    Haskell ref: prop_makeDecisions_sharedstate
    """

    @given(state=shared_tx_state_strategy())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_invariant_holds_after_decisions(
        self, state: SharedTxState
    ) -> None:
        """SharedTxState invariant holds before and after make_decisions."""
        assert state.check_invariant()
        state.make_decisions()
        assert state.check_invariant()


# ---------------------------------------------------------------------------
# Test 8: prop_mempool_writer
# ---------------------------------------------------------------------------


class TestMempoolWriter:
    """Mempool writer integration works correctly.

    Haskell ref: prop_mempool_writer
    """

    def test_write_moves_buffered_to_mempool(self) -> None:
        """Buffered txs are moved to mempool on write."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])
        state.collect_txs("peer_0")
        state.receive_txs("peer_0", {txid: b"\xaa\xbb"})

        assert txid in state.buffered_txs
        assert txid not in state.mempool_tx_ids

        written = state.write_mempool()

        assert txid in written
        assert txid in state.mempool_tx_ids
        assert txid not in state.buffered_txs

    def test_write_empty_buffer(self) -> None:
        """Writing with empty buffer returns empty list."""
        state = SharedTxState()
        written = state.write_mempool()
        assert written == []

    def test_mempool_txs_not_re_requested(self) -> None:
        """After writing to mempool, those txs are not requested again."""
        state = SharedTxState()
        state.add_peer("peer_0")
        state.add_peer("peer_1")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])
        state.collect_txs("peer_0")
        state.receive_txs("peer_0", {txid: b"\xaa\xbb"})
        state.write_mempool()

        # peer_1 also announces the same txid
        state.receive_tx_ids("peer_1", [(txid, 100)])
        collected = state.collect_txs("peer_1")

        assert txid not in collected

    @pytest.mark.asyncio
    async def test_mempool_writer_via_server(self) -> None:
        """End-to-end: server receives txs and writes to mempool callback."""
        mock = MockChannel()
        protocol = TxSubmissionProtocol()
        codec = TxSubmissionCodec()

        received_tx_ids: list[tuple[bytes, int]] = []
        received_txs: list[bytes] = []

        tx1_id = b"\x01" * 32
        tx1_body = b"\xaa\xbb\xcc"

        async def run_client() -> None:
            runner = ProtocolRunner(
                role=PeerRole.Initiator,
                protocol=protocol,
                codec=codec,
                channel=mock.client_side,
            )
            client = TxSubmissionClient(runner)
            await client.send_init()

            req = await client.recv_server_request()
            assert isinstance(req, TsMsgRequestTxIds)
            await client.reply_tx_ids([(tx1_id, len(tx1_body))])

            req2 = await client.recv_server_request()
            assert isinstance(req2, TsMsgRequestTxs)
            await client.reply_txs([tx1_body])

            req3 = await client.recv_server_request()
            assert isinstance(req3, TsMsgRequestTxIds)
            await client.done()

        async def on_tx_ids(ids: list[tuple[bytes, int]]) -> None:
            received_tx_ids.extend(ids)

        async def on_txs(txs: list[bytes]) -> None:
            received_txs.extend(txs)

        await asyncio.gather(
            run_client(),
            run_tx_submission_server(
                mock.server_side,
                on_tx_ids_received=on_tx_ids,
                on_txs_received=on_txs,
                max_tx_ids_to_request=10,
            ),
        )

        assert received_tx_ids == [(tx1_id, len(tx1_body))]
        assert received_txs == [tx1_body]


# ---------------------------------------------------------------------------
# Test 9: prop_receivedTxIdsImpl
# ---------------------------------------------------------------------------


class TestReceivedTxIdsImpl:
    """Received tx ID tracking is correct.

    Haskell ref: prop_receivedTxIdsImpl
    """

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_received_ids_tracked(self, data: st.DataObject) -> None:
        """All received tx IDs appear in the peer's available set."""
        state = SharedTxState()
        state.add_peer("peer_0")

        num_txs = data.draw(st.integers(min_value=1, max_value=10))
        tx_ids = []
        seen = set()
        for _ in range(num_txs):
            txid = data.draw(txid_strategy)
            if txid not in seen:
                seen.add(txid)
                tx_ids.append((txid, data.draw(size_strategy)))

        state.receive_tx_ids("peer_0", tx_ids)

        peer = state.peers["peer_0"]
        for txid, sz in tx_ids:
            assert txid in peer.available_tx_ids
            assert peer.available_tx_ids[txid] == sz

        assert peer.unacked_count == len(tx_ids)

    def test_received_ids_added_to_known(self) -> None:
        """Received tx IDs are added to the global known set."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid = b"\x01" * 32
        state.receive_tx_ids("peer_0", [(txid, 100)])
        assert txid in state.known_tx_ids

    def test_received_ids_from_nonexistent_peer(self) -> None:
        """Receiving tx IDs from non-existent peer is a no-op."""
        state = SharedTxState()
        state.receive_tx_ids("ghost", [(b"\x01" * 32, 100)])
        assert len(state.known_tx_ids) == 0


# ---------------------------------------------------------------------------
# Test 10: prop_SharedTxState_generator
# ---------------------------------------------------------------------------


class TestSharedTxStateGenerator:
    """Generator produces valid SharedTxState instances.

    Haskell ref: prop_SharedTxState_generator
    """

    @given(state=shared_tx_state_strategy())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_generated_state_valid(self, state: SharedTxState) -> None:
        """Every generated SharedTxState passes the invariant check."""
        assert state.check_invariant()

    @given(state=shared_tx_state_strategy())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_generated_state_has_peers(self, state: SharedTxState) -> None:
        """Every generated state has at least one peer."""
        assert len(state.peers) >= 1

    @given(state=shared_tx_state_strategy())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_generated_state_no_mempool_in_available(
        self, state: SharedTxState
    ) -> None:
        """Mempool tx IDs don't appear in any peer's available set."""
        for peer in state.peers.values():
            for txid in peer.available_tx_ids:
                assert txid not in state.mempool_tx_ids


# ---------------------------------------------------------------------------
# Test 11: prop_sharedTxStateInvariant
# ---------------------------------------------------------------------------


class TestSharedTxStateInvariant:
    """Invariant holds across all operations.

    Haskell ref: prop_sharedTxStateInvariant
    """

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_invariant_across_operations(self, data: st.DataObject) -> None:
        """Run a random sequence of operations; invariant holds after each."""
        state = SharedTxState()
        state.add_peer("peer_0")
        state.add_peer("peer_1")
        assert state.check_invariant()

        num_ops = data.draw(st.integers(min_value=1, max_value=20))
        for _ in range(num_ops):
            op = data.draw(st.integers(min_value=0, max_value=4))
            pid = data.draw(st.sampled_from(["peer_0", "peer_1"]))

            if op == 0:
                # Receive tx IDs
                txid = data.draw(txid_strategy)
                sz = data.draw(size_strategy)
                if txid not in state.mempool_tx_ids:
                    peer = state.peers[pid]
                    if txid not in peer.available_tx_ids:
                        state.receive_tx_ids(pid, [(txid, sz)])

            elif op == 1:
                # Acknowledge tx IDs
                peer = state.peers[pid]
                if peer.unacked_count > 0:
                    count = data.draw(
                        st.integers(
                            min_value=1,
                            max_value=peer.unacked_count,
                        )
                    )
                    state.acknowledge_tx_ids(pid, count)

            elif op == 2:
                # Collect txs
                state.collect_txs(pid)

            elif op == 3:
                # Receive txs (for in-flight ones)
                peer = state.peers[pid]
                if peer.requested_tx_ids:
                    txid = next(iter(peer.requested_tx_ids))
                    state.receive_txs(pid, {txid: b"\xaa"})

            elif op == 4:
                # Write mempool
                state.write_mempool()

            assert state.check_invariant(), (
                f"Invariant violated after op={op} for {pid}"
            )


# ---------------------------------------------------------------------------
# Test 12: prop_splitAcknowledgedTxIds
# ---------------------------------------------------------------------------


class TestSplitAcknowledgedTxIds:
    """Split logic correctly partitions acknowledged tx IDs.

    Haskell ref: prop_splitAcknowledgedTxIds
    """

    def test_split_partitions_correctly(self) -> None:
        """Split produces disjoint sets covering all acknowledged IDs."""
        state = SharedTxState()
        state.add_peer("peer_0")

        txid_1 = b"\x01" * 32
        txid_2 = b"\x02" * 32
        txid_3 = b"\x03" * 32

        state.receive_tx_ids(
            "peer_0",
            [(txid_1, 100), (txid_2, 200), (txid_3, 300)],
        )
        state.acknowledge_tx_ids("peer_0", 3)

        # Put txid_1 in mempool
        state.mempool_tx_ids.add(txid_1)

        in_mp, not_in_mp = state.split_acknowledged_tx_ids("peer_0")

        assert txid_1 in in_mp
        assert txid_2 in not_in_mp
        assert txid_3 in not_in_mp

        # Disjoint
        assert not set(in_mp) & set(not_in_mp)

        # Complete
        assert set(in_mp) | set(not_in_mp) == {txid_1, txid_2, txid_3}

    @given(data=st.data())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_split_property(self, data: st.DataObject) -> None:
        """For any acknowledged set, split covers everything exactly once."""
        state = SharedTxState()
        state.add_peer("peer_0")

        num_txs = data.draw(st.integers(min_value=1, max_value=10))
        tx_ids = []
        seen = set()
        for _ in range(num_txs):
            txid = data.draw(txid_strategy)
            if txid not in seen:
                seen.add(txid)
                tx_ids.append((txid, data.draw(size_strategy)))

        state.receive_tx_ids("peer_0", tx_ids)
        state.acknowledge_tx_ids("peer_0", len(tx_ids))

        # Put some in mempool
        mempool_count = data.draw(
            st.integers(min_value=0, max_value=len(tx_ids))
        )
        for txid, _ in tx_ids[:mempool_count]:
            state.mempool_tx_ids.add(txid)

        in_mp, not_in_mp = state.split_acknowledged_tx_ids("peer_0")

        # Every acknowledged ID is in exactly one partition
        all_acked = set(state.peers["peer_0"].acknowledged_tx_ids)
        assert set(in_mp) | set(not_in_mp) == all_acked
        assert not set(in_mp) & set(not_in_mp)

        # in_mp are actually in mempool
        for txid in in_mp:
            assert txid in state.mempool_tx_ids
        for txid in not_in_mp:
            assert txid not in state.mempool_tx_ids


# ---------------------------------------------------------------------------
# Test 13: prop_filterActivePeers_not_limitting_decisions
# ---------------------------------------------------------------------------


class TestFilterActivePeersNotLimitingDecisions:
    """Active peer filter doesn't limit decision making.

    The active peer filter identifies peers with work to do, but the
    decision engine should still consider ALL peers (including idle ones
    that need new tx ID requests).

    Haskell ref: prop_filterActivePeers_not_limitting_decisions
    """

    def test_idle_peers_still_get_decisions(self) -> None:
        """Peers not in the active set still receive decisions."""
        state = SharedTxState()

        # peer_0 has txs (active), peer_1 has nothing (idle)
        state.add_peer("peer_0")
        state.add_peer("peer_1")
        state.receive_tx_ids("peer_0", [(b"\x01" * 32, 100)])

        active = state.active_peers()
        assert "peer_0" in active
        assert "peer_1" not in active  # peer_1 is idle

        # But decisions should still include peer_1
        decisions = state.make_decisions()
        peers_in_decisions = {pid for pid, _, _ in decisions}
        assert "peer_1" in peers_in_decisions

    def test_active_filter_is_subset(self) -> None:
        """Active peers are a subset of all peers, never a superset."""
        state = SharedTxState()
        for i in range(5):
            state.add_peer(f"peer_{i}")

        # Only give txs to some
        state.receive_tx_ids("peer_0", [(b"\x01" * 32, 100)])
        state.receive_tx_ids("peer_2", [(b"\x02" * 32, 200)])

        active = state.active_peers()
        assert active.issubset(state.peers.keys())
        assert active == {"peer_0", "peer_2"}

    @given(state=shared_tx_state_strategy())
    @settings(
        max_examples=_MAX_EXAMPLES,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_decisions_not_limited_by_active_filter(
        self, state: SharedTxState
    ) -> None:
        """Peers with room in their window get at least a request_tx_ids."""
        decisions = state.make_decisions()
        peers_in_decisions = {pid for pid, _, _ in decisions}

        # Peers whose unacked window has room should get at least a
        # request_tx_ids to keep the pipeline running.  Peers at their
        # unacked limit AND with no requestable txs correctly get no
        # decision — the protocol only acts when there is work to do.
        for pid, peer in state.peers.items():
            has_window = peer.unacked_count < MAX_UNACKED_TX_IDS
            has_requestable = any(
                txid not in state.mempool_tx_ids
                and txid not in state.in_flight_tx_ids
                and txid not in peer.requested_tx_ids
                for txid in peer.available_tx_ids
            )
            if has_window or has_requestable:
                assert pid in peers_in_decisions, (
                    f"Peer {pid} has room (unacked={peer.unacked_count}) "
                    f"or requestable txs but got no decision"
                )
