"""Pytest fixtures for Ogmios-based conformance testing.

Provides WebSocket connectivity to Ogmios (JSON-RPC over WS) for querying
the Haskell cardano-node. All conformance tests skip automatically when
Docker Compose services aren't running.

Fixture files in tests/conformance/fixtures/ provide fallback data when
Ogmios is unavailable, allowing structural validation tests to run in CI
without Docker.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import websockets

# Make helpers importable — add this directory to sys.path
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from helpers import (  # noqa: E402
    ERA_FIXTURE_FILES,
    load_fixture,
    ogmios_rpc,
)

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
    except httpx.ConnectError, httpx.TimeoutException, OSError:
        return False


@pytest.fixture(autouse=True)
def skip_without_ogmios(request: pytest.FixtureRequest, ogmios_available: bool) -> None:
    """Auto-skip conformance tests when Ogmios is not running.

    Only applies to tests marked with @pytest.mark.conformance.
    Tests marked with @pytest.mark.fixture_only are never skipped — they
    use cached fixture files and don't need Ogmios.
    """
    # Never skip fixture_only tests
    if request.node.get_closest_marker("fixture_only") is not None:
        return

    marker = request.node.get_closest_marker("conformance")
    if marker is not None and not ogmios_available:
        pytest.skip("Ogmios not available — skipping conformance test")


# ---------------------------------------------------------------------------
# WebSocket client
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _ogmios_ws(url: str) -> AsyncGenerator[websockets.ClientConnection]:
    """Open a WebSocket connection to Ogmios."""
    async with websockets.connect(url) as ws:
        yield ws


@pytest.fixture
async def ogmios_client(ogmios_url: str) -> AsyncGenerator[websockets.ClientConnection]:
    """Async fixture providing a WebSocket connection to Ogmios.

    Usage::

        async def test_something(ogmios_client):
            await ogmios_client.send(json.dumps({...}))
            response = json.loads(await ogmios_client.recv())
    """
    async with _ogmios_ws(ogmios_url) as ws:
        yield ws


# ---------------------------------------------------------------------------
# Fixture-file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def byron_block_fixture() -> dict:
    """Pre-cached Byron block data."""
    return load_fixture("byron")


@pytest.fixture(scope="session")
def shelley_block_fixture() -> dict:
    """Pre-cached Shelley block data."""
    return load_fixture("shelley")


@pytest.fixture(scope="session")
def alonzo_block_fixture() -> dict:
    """Pre-cached Alonzo block data (with Plutus scripts)."""
    return load_fixture("alonzo")


@pytest.fixture(scope="session")
def babbage_block_fixture() -> dict:
    """Pre-cached Babbage block data (with inline datums + reference inputs)."""
    return load_fixture("babbage")


@pytest.fixture(scope="session")
def conway_block_fixture() -> dict:
    """Pre-cached Conway block data (with governance actions)."""
    return load_fixture("conway")


@pytest.fixture(scope="session")
def all_era_fixtures() -> dict[str, dict]:
    """All pre-cached era block fixtures keyed by era name."""
    return {era: load_fixture(era) for era in ERA_FIXTURE_FILES}


# ---------------------------------------------------------------------------
# Helper: fetch block CBOR
# ---------------------------------------------------------------------------


async def fetch_block_cbor(
    ogmios_url: str,
    slot: int,
    block_hash: str,
) -> bytes:
    """Fetch a block's raw CBOR bytes from Ogmios.

    Uses chain-sync findIntersection + nextBlock to retrieve the block
    following the given point. Ogmios v6 returns CBOR when available.

    Args:
        ogmios_url: WebSocket URL for Ogmios (e.g. "ws://localhost:1337").
        slot: Slot number of the block.
        block_hash: Block header hash (hex string).

    Returns:
        Raw CBOR bytes of the block.

    Raises:
        RuntimeError: If Ogmios returns an error or unexpected response.
    """
    async with _ogmios_ws(ogmios_url) as ws:
        # Step 1: Find the intersection at the target block
        await ogmios_rpc(
            ws,
            "findIntersection",
            {"points": [{"slot": slot, "id": block_hash}]},
            "fetch-block-cbor",
        )

        # Step 2: Request the next block (which should be the one after our point)
        result = await ogmios_rpc(ws, "nextBlock", rpc_id="fetch-block-next")

        block = result.get("block")
        if block is None:
            raise RuntimeError(f"No block in Ogmios response: {json.dumps(result)[:500]}")

        # Extract CBOR — Ogmios v6 includes a 'cbor' field when available
        if isinstance(block, dict):
            cbor_hex = block.get("cbor")
            if cbor_hex is not None:
                return bytes.fromhex(cbor_hex)

        raise RuntimeError(
            f"No CBOR data in block response. Keys: "
            f"{list(block.keys()) if isinstance(block, dict) else type(block)}"
        )
