"""Integration test: chain-sync with a real cardano-node.

VNODE-171 + VNODE-156 — Connect to Docker Compose cardano-node,
handshake, run chain-sync, sync block headers, verify hashes.
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.core.multiplexer.segment import MuxSegment
from vibe.cardano.network.chainsync import (
    MsgRollForward,
    MsgRollBackward,
    MsgIntersectFound,
    MsgIntersectNotFound,
    MsgAwaitReply,
    encode_find_intersect,
    encode_request_next,
    decode_server_message,
)


pytestmark = pytest.mark.integration

CHAINSYNC_PROTOCOL_ID = 2


async def _send_chainsync(bearer, payload: bytes):
    seg = MuxSegment(
        timestamp=0, protocol_id=CHAINSYNC_PROTOCOL_ID,
        is_initiator=True, payload=payload,
    )
    await bearer.write_segment(seg)


async def _recv_chainsync(bearer):
    resp = await bearer.read_segment()
    return decode_server_message(resp.payload)


@pytest.mark.timeout(30)
async def test_find_intersect_at_origin(handshaken_bearer):
    """FindIntersect with empty points returns IntersectNotFound (origin)."""
    bearer = handshaken_bearer
    await _send_chainsync(bearer, encode_find_intersect([]))
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, MsgIntersectNotFound)


@pytest.mark.timeout(30)
async def test_sync_first_blocks(handshaken_bearer):
    """Sync first 10 blocks after origin."""
    bearer = handshaken_bearer

    # Find intersect at origin
    await _send_chainsync(bearer, encode_find_intersect([]))
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, MsgIntersectNotFound)

    # First RequestNext gives RollBackward to origin
    await _send_chainsync(bearer, encode_request_next())
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, MsgRollBackward)

    # Next blocks should be RollForward
    forward_count = 0
    for _ in range(10):
        await _send_chainsync(bearer, encode_request_next())
        msg = await _recv_chainsync(bearer)
        if isinstance(msg, MsgRollForward):
            forward_count += 1
            assert msg.tip is not None

    assert forward_count == 10


@pytest.mark.timeout(30)
async def test_roll_forward_has_header_bytes(handshaken_bearer):
    """RollForward messages contain non-empty header bytes."""
    bearer = handshaken_bearer

    await _send_chainsync(bearer, encode_find_intersect([]))
    await _recv_chainsync(bearer)  # IntersectNotFound
    await _send_chainsync(bearer, encode_request_next())
    await _recv_chainsync(bearer)  # RollBackward

    await _send_chainsync(bearer, encode_request_next())
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, MsgRollForward)
    assert msg.header is not None
    assert len(msg.header) > 0


@pytest.mark.timeout(60)
async def test_sync_100_headers(handshaken_bearer):
    """Sync 100 block headers and verify they arrive in order."""
    bearer = handshaken_bearer

    await _send_chainsync(bearer, encode_find_intersect([]))
    await _recv_chainsync(bearer)  # IntersectNotFound
    await _send_chainsync(bearer, encode_request_next())
    await _recv_chainsync(bearer)  # RollBackward

    headers = []
    for _ in range(100):
        await _send_chainsync(bearer, encode_request_next())
        msg = await _recv_chainsync(bearer)
        if isinstance(msg, MsgRollForward):
            headers.append(msg)

    assert len(headers) == 100
    # Tips should be monotonically advancing or stable
    tip_slots = [h.tip.point.slot for h in headers if hasattr(h.tip.point, 'slot')]
    for i in range(1, len(tip_slots)):
        assert tip_slots[i] >= tip_slots[i - 1]


@pytest.mark.timeout(300)
async def test_sync_1000_headers_gate(handshaken_bearer):
    """PHASE 2 GATE TEST: Sync 1,000 block headers from a real Cardano node.

    This is the Phase 2 definition of done (VNODE-156). Proves that
    vibe-node can connect to a Haskell cardano-node, complete the
    handshake, and sync block headers via the chain-sync miniprotocol.
    """
    bearer = handshaken_bearer

    # Find intersect at origin
    await _send_chainsync(bearer, encode_find_intersect([]))
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, (MsgIntersectFound, MsgIntersectNotFound))

    # Skip initial rollback
    await _send_chainsync(bearer, encode_request_next())
    msg = await _recv_chainsync(bearer)
    assert isinstance(msg, MsgRollBackward)

    # Sync 1,000 headers
    forward_count = 0
    for i in range(1000):
        await _send_chainsync(bearer, encode_request_next())
        msg = await _recv_chainsync(bearer)

        if isinstance(msg, MsgRollForward):
            forward_count += 1
        elif isinstance(msg, MsgAwaitReply):
            # At tip, wait for new block — shouldn't happen at origin
            pytest.fail(f"Got AwaitReply after only {forward_count} blocks")

    assert forward_count == 1000, (
        f"Expected 1000 RollForward messages, got {forward_count}"
    )
