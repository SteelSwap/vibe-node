"""Shared helpers for conformance tests.

These functions are used by both conftest.py (for fixtures) and test modules
(for direct calls). Extracted here to avoid import issues since conftest.py
is not directly importable as a module in pytest's test collection.
"""

from __future__ import annotations

import json
from pathlib import Path

import websockets

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Canonical era names -> fixture file names
ERA_FIXTURE_FILES: dict[str, str] = {
    "byron": "byron_block.json",
    "shelley": "shelley_block.json",
    "alonzo": "alonzo_block.json",
    "babbage": "babbage_block.json",
    "conway": "conway_block.json",
}


# ---------------------------------------------------------------------------
# Ogmios JSON-RPC helpers
# ---------------------------------------------------------------------------


async def ogmios_rpc(
    ws: websockets.ClientConnection,
    method: str,
    params: dict | None = None,
    rpc_id: str = "req",
) -> dict:
    """Send a JSON-RPC request to Ogmios and return the result.

    Raises RuntimeError if the response contains an error field.
    """
    msg: dict = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    resp = json.loads(await ws.recv())
    if "error" in resp:
        raise RuntimeError(f"Ogmios {method} error: {resp['error']}")
    return resp.get("result", {})


async def fetch_blocks_from_point(
    ws: websockets.ClientConnection,
    point: dict | str,
    count: int = 10,
) -> list[dict]:
    """Fetch N blocks starting from a chain-sync intersection point.

    Args:
        ws: Open WebSocket connection to Ogmios.
        point: Ogmios point — either "origin" or {"slot": N, "id": "hash"}.
        count: Number of forward blocks to collect.

    Returns:
        List of Ogmios block JSON dicts.
    """
    points = [point] if isinstance(point, str) else [point]
    await ogmios_rpc(ws, "findIntersection", {"points": points}, "find")
    # First nextBlock after intersection is always RollBackward
    await ogmios_rpc(ws, "nextBlock", rpc_id="skip")

    blocks: list[dict] = []
    for i in range(count + 10):  # fetch extra in case of EBBs
        result = await ogmios_rpc(ws, "nextBlock", rpc_id=f"b{i}")
        if result.get("direction") == "forward":
            block = result.get("block", {})
            blocks.append(block)
            if len(blocks) >= count:
                break

    return blocks


async def fetch_blocks_from_origin(
    ws: websockets.ClientConnection,
    count: int = 10,
) -> list[dict]:
    """Fetch N blocks from chain origin via Ogmios chain-sync."""
    return await fetch_blocks_from_point(ws, "origin", count)


# ---------------------------------------------------------------------------
# Fixture-file loaders
# ---------------------------------------------------------------------------


def load_fixture(era: str) -> dict:
    """Load a pre-cached block fixture from the fixtures directory.

    Args:
        era: Era name (byron, shelley, alonzo, babbage, conway).

    Returns:
        Parsed JSON dict matching the Ogmios v6 block output structure.

    Raises:
        FileNotFoundError: If no fixture file exists for the era.
    """
    filename = ERA_FIXTURE_FILES.get(era)
    if filename is None:
        raise FileNotFoundError(f"No fixture file registered for era: {era}")

    filepath = FIXTURES_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Fixture file not found: {filepath}")

    with open(filepath) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def extract_block_metadata(block: dict) -> dict:
    """Extract key metadata fields from an Ogmios block JSON for comparison.

    Returns a normalized dict with:
        era, id, height, slot, tx_count, total_fee_lovelace,
        script_count, datum_count, redeemer_count
    """
    txs = block.get("transactions", [])

    total_fee = 0
    script_count = 0
    datum_count = 0
    redeemer_count = 0

    for tx in txs:
        # Fee extraction — Ogmios nests fee under ada.lovelace
        fee = tx.get("fee", {})
        if isinstance(fee, dict):
            total_fee += fee.get("ada", {}).get("lovelace", 0)
        elif isinstance(fee, int):
            total_fee += fee

        # Script count
        scripts = tx.get("scripts", {})
        script_count += len(scripts)

        # Datum count
        datums = tx.get("datums", {})
        datum_count += len(datums)

        # Redeemer count
        redeemers = tx.get("redeemers", [])
        redeemer_count += len(redeemers)

    return {
        "era": block.get("era"),
        "id": block.get("id"),
        "height": block.get("height"),
        "slot": block.get("slot"),
        "tx_count": len(txs),
        "total_fee_lovelace": total_fee,
        "script_count": script_count,
        "datum_count": datum_count,
        "redeemer_count": redeemer_count,
    }
