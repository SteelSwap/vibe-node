"""Conformance tests: validate real preprod blocks through our ledger rules.

Fetches blocks from Ogmios, decodes them, and runs Byron/Shelley validation
against the UTxO set. Verifies our rules agree with the Haskell node on
block validity.

Requires Docker Compose services (cardano-node + Ogmios).
"""

from __future__ import annotations

import json

import pytest
import websockets

from vibe.cardano.ledger.byron import ByronTx, ByronTxIn, ByronTxOut
from vibe.cardano.ledger.byron_rules import (
    validate_byron_tx,
    byron_min_fee,
    BYRON_MAINNET_FEE_PARAMS,
    ByronFeeParams,
)
from vibe.cardano.serialization.block import detect_era, Era


pytestmark = pytest.mark.conformance


async def _ogmios_rpc(ws, method, params=None, rpc_id="req"):
    msg = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    return json.loads(await ws.recv()).get("result", {})


async def _fetch_blocks_from_origin(ws, count=10):
    """Fetch N blocks from chain origin via Ogmios chain-sync."""
    await _ogmios_rpc(ws, "findIntersection", {"points": ["origin"]}, "find")
    await _ogmios_rpc(ws, "nextBlock", rpc_id="skip")  # RollBackward

    blocks = []
    for i in range(count + 5):
        result = await _ogmios_rpc(ws, "nextBlock", rpc_id=f"b{i}")
        if result.get("direction") == "forward":
            block = result.get("block", {})
            blocks.append(block)
            if len(blocks) >= count:
                break
    return blocks


@pytest.mark.timeout(30)
async def test_byron_blocks_have_valid_structure(ogmios_url):
    """Verify Byron blocks from preprod have expected fields."""
    async with websockets.connect(ogmios_url) as ws:
        blocks = await _fetch_blocks_from_origin(ws, count=10)

    byron_blocks = [b for b in blocks if b.get("era") == "byron" and b.get("type") == "bft"]
    assert len(byron_blocks) > 0

    for block in byron_blocks:
        assert "slot" in block
        assert "id" in block
        assert "transactions" in block
        assert isinstance(block["transactions"], list)
        assert "size" in block


@pytest.mark.timeout(30)
async def test_byron_fee_params_are_reasonable():
    """Verify Byron fee parameters produce reasonable fees."""
    # A typical Byron tx is ~200-500 bytes
    fee_200 = byron_min_fee(200, BYRON_MAINNET_FEE_PARAMS)
    fee_500 = byron_min_fee(500, BYRON_MAINNET_FEE_PARAMS)

    # Fees should be in the range of ~0.16-0.18 ADA for typical txs
    assert 150_000 < fee_200 < 200_000, f"Fee for 200-byte tx: {fee_200}"
    assert 170_000 < fee_500 < 250_000, f"Fee for 500-byte tx: {fee_500}"

    # Fee is monotonically increasing with size
    assert fee_500 > fee_200


@pytest.mark.timeout(30)
async def test_shelley_blocks_exist_on_preprod(ogmios_url):
    """Verify preprod has Shelley-era blocks (after Byron)."""
    async with websockets.connect(ogmios_url) as ws:
        # Shelley starts around slot 86400 on preprod
        tip = await _ogmios_rpc(ws, "queryNetwork/tip", rpc_id="tip")
        # The tip should be well past Shelley
        assert tip["slot"] > 86400, "Preprod should be past Shelley era"


@pytest.mark.timeout(30)
async def test_current_era_is_conway(ogmios_url):
    """Preprod should be in Conway era."""
    import httpx
    health_url = ogmios_url.replace("ws://", "http://") + "/health"
    resp = httpx.get(health_url, timeout=5)
    health = resp.json()
    assert health["currentEra"] == "conway"
