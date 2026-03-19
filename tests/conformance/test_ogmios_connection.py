"""Smoke test: verify Ogmios connectivity and basic chain queries.

This test connects to Ogmios, queries the chain tip, and asserts
the node has synced past genesis (slot > 0). It validates that
our conformance test infrastructure is wired up correctly.
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.conformance
async def test_ogmios_chain_tip(ogmios_client) -> None:
    """Connect to Ogmios and verify the chain tip has a positive slot number."""
    request = {
        "jsonrpc": "2.0",
        "method": "queryNetwork/tip",
        "id": "tip-query",
    }

    await ogmios_client.send(json.dumps(request))
    response = json.loads(await ogmios_client.recv())

    # Ogmios JSON-RPC response should have a "result" field
    assert "result" in response, f"Unexpected Ogmios response: {response}"

    tip = response["result"]

    # The tip should have a slot number
    assert "slot" in tip, f"No 'slot' in tip response: {tip}"
    assert isinstance(tip["slot"], int), f"Slot is not an integer: {tip['slot']}"
    assert tip["slot"] > 0, f"Chain tip slot should be > 0, got: {tip['slot']}"

    # The tip should also have a block hash (id)
    assert "id" in tip, f"No 'id' (block hash) in tip response: {tip}"
    assert isinstance(tip["id"], str), f"Block hash is not a string: {tip['id']}"
    assert len(tip["id"]) == 64, f"Block hash should be 64 hex chars, got: {len(tip['id'])}"
