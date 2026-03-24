"""Integration test: handshake with a real cardano-node.

VNODE-168 — Connect to Docker Compose cardano-node, execute the
handshake miniprotocol, verify AcceptVersion with correct network magic.
"""

from __future__ import annotations

import pytest

from vibe.cardano.network.handshake import (
    MAINNET_NETWORK_MAGIC,
    PREPROD_NETWORK_MAGIC,
    MsgAcceptVersion,
    MsgRefuse,
    build_version_table,
    decode_handshake_response,
    encode_propose_versions,
)
from vibe.core.multiplexer.segment import MuxSegment

pytestmark = pytest.mark.integration


@pytest.mark.timeout(10)
async def test_handshake_accepted(bearer):
    """Handshake with preprod node succeeds and returns AcceptVersion."""
    versions = build_version_table(PREPROD_NETWORK_MAGIC)
    propose = encode_propose_versions(versions)
    seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=propose)
    await bearer.write_segment(seg)

    resp = await bearer.read_segment()
    msg = decode_handshake_response(resp.payload)

    assert isinstance(msg, MsgAcceptVersion)
    assert msg.version_data.network_magic == PREPROD_NETWORK_MAGIC


@pytest.mark.timeout(10)
async def test_handshake_selects_highest_version(bearer):
    """Node selects the highest mutually supported version."""
    versions = build_version_table(PREPROD_NETWORK_MAGIC)
    propose = encode_propose_versions(versions)
    seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=propose)
    await bearer.write_segment(seg)

    resp = await bearer.read_segment()
    msg = decode_handshake_response(resp.payload)

    assert isinstance(msg, MsgAcceptVersion)
    # Should pick the highest version we offered
    assert msg.version_number == max(versions.keys())


@pytest.mark.timeout(10)
async def test_handshake_wrong_magic_refused(bearer):
    """Handshake with wrong network magic is refused."""
    # Use mainnet magic against preprod node
    versions = build_version_table(MAINNET_NETWORK_MAGIC)
    propose = encode_propose_versions(versions)
    seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=propose)
    await bearer.write_segment(seg)

    resp = await bearer.read_segment()
    msg = decode_handshake_response(resp.payload)

    assert isinstance(msg, MsgRefuse)
