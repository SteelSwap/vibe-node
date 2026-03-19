"""Pytest fixtures for Ogmios-based conformance testing.

Provides WebSocket connectivity to Ogmios (JSON-RPC over WS) for querying
the Haskell cardano-node. All conformance tests skip automatically when
Docker Compose services aren't running.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import pytest
import websockets


# ---------------------------------------------------------------------------
# URL configuration
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ogmios_url() -> str:
    """WebSocket URL for the Ogmios server.

    Configurable via the OGMIOS_URL environment variable.
    Defaults to ws://localhost:1337.
    """
    return os.environ.get("OGMIOS_URL", "ws://localhost:1337")


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ogmios_available(ogmios_url: str) -> bool:
    """Check whether Ogmios is reachable.

    Hits the HTTP health endpoint (same host/port as the WS endpoint).
    Returns True if Ogmios responds, False otherwise.
    """
    # Derive HTTP URL from WS URL: ws://host:port -> http://host:port/health
    health_url = ogmios_url.replace("ws://", "http://").replace("wss://", "https://")
    health_url = health_url.rstrip("/") + "/health"

    try:
        resp = httpx.get(health_url, timeout=5.0)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        return False


@pytest.fixture(autouse=True)
def skip_without_ogmios(request: pytest.FixtureRequest, ogmios_available: bool) -> None:
    """Auto-skip conformance tests when Ogmios is not running.

    Only applies to tests marked with @pytest.mark.conformance.
    """
    marker = request.node.get_closest_marker("conformance")
    if marker is not None and not ogmios_available:
        pytest.skip("Ogmios not available — skipping conformance test")


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _ogmios_ws(url: str) -> AsyncGenerator[websockets.ClientConnection, None]:
    """Open a WebSocket connection to Ogmios."""
    async with websockets.connect(url) as ws:
        yield ws


@pytest.fixture
async def ogmios_client(ogmios_url: str) -> AsyncGenerator[websockets.ClientConnection, None]:
    """Async fixture providing a WebSocket connection to Ogmios.

    Usage::

        async def test_something(ogmios_client):
            await ogmios_client.send(json.dumps({...}))
            response = json.loads(await ogmios_client.recv())
    """
    async with _ogmios_ws(ogmios_url) as ws:
        yield ws


# ---------------------------------------------------------------------------
# Helper: fetch block CBOR
# ---------------------------------------------------------------------------

async def fetch_block_cbor(
    ogmios_url: str,
    slot: int,
    block_hash: str,
) -> bytes:
    """Fetch a block's raw CBOR bytes from Ogmios.

    Uses the queryNetwork/blockBySlot JSON-RPC method. Ogmios returns the
    block as a hex-encoded CBOR string.

    Args:
        ogmios_url: WebSocket URL for Ogmios (e.g. "ws://localhost:1337").
        slot: Slot number of the block.
        block_hash: Block header hash (hex string).

    Returns:
        Raw CBOR bytes of the block.

    Raises:
        RuntimeError: If Ogmios returns an error or unexpected response.
    """
    request = {
        "jsonrpc": "2.0",
        "method": "queryLedgerState/constitutionalCommittee",
        "id": None,
    }
    # Ogmios v6 uses a different approach for fetching blocks.
    # The primary way to get block CBOR is through the chain-sync
    # mini-protocol via nextBlock. For specific block fetches,
    # we use queryNetwork with a point reference.
    request = {
        "jsonrpc": "2.0",
        "method": "findIntersection",
        "params": {
            "points": [{"slot": slot, "id": block_hash}],
        },
        "id": "fetch-block-cbor",
    }

    async with _ogmios_ws(ogmios_url) as ws:
        # Step 1: Find the intersection at the target block
        await ws.send(json.dumps(request))
        resp = json.loads(await ws.recv())

        if "error" in resp:
            raise RuntimeError(
                f"Ogmios findIntersection error: {resp['error']}"
            )

        # Step 2: Request the next block (which should be the one after our point)
        next_block_req = {
            "jsonrpc": "2.0",
            "method": "nextBlock",
            "id": "fetch-block-next",
        }
        await ws.send(json.dumps(next_block_req))
        block_resp = json.loads(await ws.recv())

        if "error" in block_resp:
            raise RuntimeError(
                f"Ogmios nextBlock error: {block_resp['error']}"
            )

        result = block_resp.get("result", {})

        # Ogmios v6 returns block data in result.block with a cbor field
        # when the block contains CBOR data
        block = result.get("block")
        if block is None:
            raise RuntimeError(
                f"No block in Ogmios response: {json.dumps(result)[:500]}"
            )

        # Extract CBOR — Ogmios v6 includes a 'cbor' field when available
        if isinstance(block, dict):
            cbor_hex = block.get("cbor")
            if cbor_hex is not None:
                return bytes.fromhex(cbor_hex)

        raise RuntimeError(
            f"No CBOR data in block response. Keys: {list(block.keys()) if isinstance(block, dict) else type(block)}"
        )
