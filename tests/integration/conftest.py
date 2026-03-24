"""Pytest fixtures for integration tests against Docker Compose cardano-node."""

from __future__ import annotations

import os

import pytest

from vibe.cardano.network.handshake import (
    PREPROD_NETWORK_MAGIC,
    build_version_table,
    decode_handshake_response,
    encode_propose_versions,
)
from vibe.core.multiplexer.bearer import Bearer, connect
from vibe.core.multiplexer.segment import MuxSegment

CARDANO_NODE_HOST = os.environ.get("CARDANO_NODE_HOST", "localhost")
CARDANO_NODE_PORT = int(os.environ.get("CARDANO_NODE_PORT", "3001"))


@pytest.fixture(scope="session")
def cardano_node_available() -> bool:
    """Check if cardano-node is reachable on the N2N port."""
    import socket

    try:
        sock = socket.create_connection((CARDANO_NODE_HOST, CARDANO_NODE_PORT), timeout=3)
        sock.close()
        return True
    except ConnectionRefusedError, TimeoutError, OSError:
        return False


@pytest.fixture(autouse=True)
def skip_without_cardano_node(
    request: pytest.FixtureRequest, cardano_node_available: bool
) -> None:
    """Skip integration tests when cardano-node isn't running."""
    marker = request.node.get_closest_marker("integration")
    if marker is not None and not cardano_node_available:
        pytest.skip("cardano-node not available — skipping integration test")


@pytest.fixture
async def bearer() -> Bearer:
    """Connect to cardano-node and return a Bearer."""
    b = await connect(CARDANO_NODE_HOST, CARDANO_NODE_PORT)
    yield b
    await b.close()


@pytest.fixture
async def handshaken_bearer() -> Bearer:
    """Connect and complete handshake, return bearer ready for miniprotocols."""
    b = await connect(CARDANO_NODE_HOST, CARDANO_NODE_PORT)

    versions = build_version_table(PREPROD_NETWORK_MAGIC)
    propose = encode_propose_versions(versions)
    seg = MuxSegment(timestamp=0, protocol_id=0, is_initiator=True, payload=propose)
    await b.write_segment(seg)
    resp = await b.read_segment()
    decode_handshake_response(resp.payload)  # verify it parses

    yield b
    await b.close()
