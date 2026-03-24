"""Conformance tests: verify block metadata against Ogmios.

Ogmios v6 returns JSON (not raw CBOR) via chain-sync. These tests
verify that block metadata (era, slot, height, id, tx count) from
Ogmios matches what we'd expect. Raw CBOR conformance testing requires
the N2N protocol (Phase 2 Track B deliverable).

Requires Docker Compose services running (cardano-node + Ogmios).
Tests skip automatically when Ogmios is unavailable.
"""

from __future__ import annotations

import json

import pytest
import websockets

pytestmark = pytest.mark.conformance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ogmios_rpc(ws, method: str, params: dict | None = None, rpc_id: str = "req") -> dict:
    """Send a JSON-RPC request and return the result."""
    msg = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    resp = json.loads(await ws.recv())
    if "error" in resp:
        raise RuntimeError(f"Ogmios {method} error: {resp['error']}")
    return resp.get("result", {})


async def _fetch_blocks_from_origin(ws, count: int = 10) -> list[dict]:
    """Fetch N blocks starting from origin via chain-sync."""
    # Find intersection at origin
    await _ogmios_rpc(ws, "findIntersection", {"points": ["origin"]}, "find")

    blocks = []
    # First nextBlock is always RollBackward to origin
    await _ogmios_rpc(ws, "nextBlock", rpc_id="skip")

    for i in range(count + 5):  # fetch extra in case of EBBs
        result = await _ogmios_rpc(ws, "nextBlock", rpc_id=f"b{i}")
        if result.get("direction") == "forward":
            block = result.get("block", {})
            blocks.append(block)
            if len(blocks) >= count:
                break

    return blocks


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
async def test_fetch_blocks_from_origin(ogmios_client):
    """Fetch first 5 blocks from origin and verify basic structure."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=5)
    assert len(blocks) >= 5

    for block in blocks:
        assert "era" in block
        assert "id" in block
        assert isinstance(block["id"], str)
        assert len(block["id"]) == 64  # hex-encoded 32-byte hash


@pytest.mark.timeout(30)
async def test_block_ids_are_unique(ogmios_client):
    """All block IDs in a sequence should be unique."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=20)
    ids = [b["id"] for b in blocks]
    assert len(ids) == len(set(ids)), "Duplicate block IDs found"


@pytest.mark.timeout(30)
async def test_block_heights_are_monotonic(ogmios_client):
    """Block heights should increase monotonically."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=20)
    heights = [b["height"] for b in blocks]
    for i in range(1, len(heights)):
        assert heights[i] >= heights[i - 1], f"Height decreased: {heights[i - 1]} -> {heights[i]}"


@pytest.mark.timeout(30)
async def test_ancestor_chain(ogmios_client):
    """Each block's ancestor should be the previous block's ID."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=10)
    for i in range(1, len(blocks)):
        ancestor = blocks[i].get("ancestor")
        prev_id = blocks[i - 1]["id"]
        assert (
            ancestor == prev_id
        ), f"Block {i} ancestor {ancestor[:16]}... != prev ID {prev_id[:16]}..."


@pytest.mark.timeout(30)
async def test_first_blocks_are_byron(ogmios_client):
    """Preprod starts with Byron era blocks."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=5)
    for block in blocks:
        assert block["era"] == "byron", f"Expected byron, got {block['era']}"


@pytest.mark.timeout(30)
async def test_recent_blocks_are_conway(ogmios_url):
    """Recent blocks on preprod should be Conway era."""
    async with websockets.connect(ogmios_url) as ws:
        tip = await _ogmios_rpc(ws, "queryNetwork/tip", rpc_id="tip")
        # Intersect at tip, get the rollback, tip is conway
        assert tip["slot"] > 0
        # The health endpoint confirms current era
        import httpx

        health_url = ogmios_url.replace("ws://", "http://") + "/health"
        resp = httpx.get(health_url, timeout=5)
        health = resp.json()
        assert health["currentEra"] == "conway"


@pytest.mark.timeout(30)
async def test_byron_block_has_expected_fields(ogmios_client):
    """Byron BFT blocks should have expected fields."""
    blocks = await _fetch_blocks_from_origin(ogmios_client, count=5)
    # Find a non-EBB Byron block
    bft_blocks = [b for b in blocks if b.get("type") == "bft"]
    assert len(bft_blocks) > 0, "No Byron BFT blocks found"

    b = bft_blocks[0]
    assert "slot" in b
    assert "issuer" in b
    assert "delegate" in b
    assert "size" in b
    assert "transactions" in b
    assert isinstance(b["transactions"], list)
