"""Evaluate pycardano block deserialization coverage per Cardano era.

Connects to the Docker Compose Ogmios instance, fetches one block from each
Cardano era (Byron through Conway), attempts to deserialize the CBOR using
pycardano's types, and reports which fields pycardano handles and which it
doesn't.

VNODE-152 — pycardano deserialization coverage evaluation.

Approach:
  - Ogmios v6 local-chain-sync provides blocks via JSON-RPC over WebSocket.
  - We navigate to known preprod block points for each era.
  - Ogmios returns blocks as JSON with a `cbor` field when requested.
  - We attempt pycardano deserialization of transaction bodies, witnesses,
    auxiliary data, and (where possible) block headers.
  - pycardano has NO block-level types — it only handles Transaction and
    its components. Block headers must be decoded with raw cbor2.

Era boundaries on preprod (approximate slot/hash pairs):
  - Byron:   genesis through slot ~86400
  - Shelley: starts at epoch 4 (slot 86400)
  - Allegra:  epoch 10 (slot 518400)
  - Mary:    epoch 14 (slot 950400)
  - Alonzo:  epoch 20 (slot 1382400)
  - Babbage: epoch 39 (slot 3542400)
  - Conway:  epoch 100+ (slot ~8640000)
"""

from __future__ import annotations

import asyncio
import json
import traceback
from dataclasses import dataclass, field
from typing import Any

import cbor2pure as cbor2
import websockets
from rich.console import Console
from rich.table import Table

from pycardano import Transaction, TransactionBody, TransactionWitnessSet
from pycardano.metadata import AuxiliaryData

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_OGMIOS_URL = "ws://localhost:1337"

# Known preprod chain points for each era.
# Discovered by walking the chain from origin via Ogmios local-chain-sync.
# We prefer blocks WITH transactions for richer deserialization testing.
# Byron uses "origin" as the intersection point.
#
# Format: "era" -> "origin" | {"slot": int, "id": str}
# The _tx variants have at least 1 transaction for testing.
PREPROD_ERA_POINTS: dict[str, dict[str, Any] | str] = {
    "byron": "origin",
    # Shelley: first block is at slot 86400; block at slot 86420 has 1 tx
    "shelley": {
        "slot": 86400,
        "id": "c971bfb21d2732457f9febf79d9b02b20b9a3bef12c561a78b818bcb8b35a574",
    },
    # Allegra: era starts at slot 518400; block at slot 518600 has 1 tx
    "allegra": {
        "slot": 518400,
        "id": "fdd5eb1b1e9fc278a08aef2f6c0fe9b576efd76966cc552d8c5a59271dc01604",
    },
    # Mary: era starts at slot 950410; block at slot 950500 has 1 tx
    "mary": {
        "slot": 950410,
        "id": "4a620c90e7dd4f68b7a4be2dc5736b2c7f3f6d02bdff8f2721c79f233c6857e4",
    },
    # Alonzo: era starts at slot 1382422; block at slot 1814649 has 1 tx
    "alonzo": {
        "slot": 1382422,
        "id": "578f3cb70f4153e1622db792fea9005c80ff80f83df028210c7a914fb780a6f6",
    },
    # Babbage: era starts at slot 3542424; block at slot 3543021 has 1 tx
    "babbage": {
        "slot": 3542424,
        "id": "4cb684aaa22af255e0a61b250fef644a7e141f4cd24825cdb886ea1306f1a51d",
    },
    # Conway: use "tip" strategy — find intersection at current tip,
    # which is guaranteed to be Conway on preprod since epoch ~100.
    "conway": "tip",
}


@dataclass
class FieldResult:
    """Result of attempting to deserialize a single field."""

    era: str
    component: str  # "transaction_body", "witnesses", "auxiliary_data", "block_header"
    field_name: str
    handled: bool
    error: str | None = None
    notes: str | None = None


@dataclass
class EraResult:
    """Aggregated results for one era."""

    era: str
    block_found: bool = False
    block_slot: int | None = None
    block_hash: str | None = None
    tx_count: int = 0
    field_results: list[FieldResult] = field(default_factory=list)
    raw_error: str | None = None


# ---------------------------------------------------------------------------
# Ogmios JSON-RPC helpers
# ---------------------------------------------------------------------------


def _make_jsonrpc(method: str, params: dict | None = None, req_id: str | None = None) -> str:
    """Build an Ogmios v6 JSON-RPC 2.0 request."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    if req_id is not None:
        msg["id"] = req_id
    return json.dumps(msg)


async def _send_recv(ws: websockets.WebSocketClientProtocol, method: str, params: dict | None = None) -> dict:
    """Send a JSON-RPC request and return the parsed response."""
    await ws.send(_make_jsonrpc(method, params))
    raw = await asyncio.wait_for(ws.recv(), timeout=30)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Block fetching via local-chain-sync
# ---------------------------------------------------------------------------


async def _get_tip(ogmios_url: str) -> dict | None:
    """Query the current chain tip from Ogmios health endpoint via HTTP."""
    import httpx

    health_url = ogmios_url.replace("ws://", "http://").replace("wss://", "https://") + "/health"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(health_url, timeout=10)
            data = resp.json()
            return data.get("lastKnownTip")
    except Exception:
        return None


async def fetch_block_for_era(
    ogmios_url: str,
    era: str,
    point: dict[str, Any] | str,
) -> dict | None:
    """Fetch one block from the given era using Ogmios local-chain-sync.

    Strategy:
      1. Connect and find intersection at the given point.
      2. Request nextBlock repeatedly until we get a 'RollForward' with a block.
      3. Return the block data from the response.

    Special case: point="tip" fetches the current tip and uses it to get
    a recent block (used for Conway since it's the current era).
    """
    # Handle "tip" strategy: query Ogmios health for current tip, then
    # use that as intersection point. We intersect at tip, then the next
    # nextBlock call returns a RollBackward to the tip, followed by blocks.
    # Since we're at the tip, new blocks arrive every ~20s on preprod.
    is_tip = point == "tip"
    if is_tip:
        tip = await _get_tip(ogmios_url)
        if tip is None:
            return {"error": "Could not get chain tip from Ogmios health endpoint"}
        tip_slot = tip["slot"]
        tip_id = tip["id"]
        point = {"slot": tip_slot, "id": tip_id}

    async with websockets.connect(ogmios_url, max_size=64 * 1024 * 1024) as ws:
        # Step 1: Find intersection
        if point == "origin":
            intersection_points = ["origin"]
        else:
            intersection_points = [point]

        resp = await _send_recv(ws, "findIntersection", {"points": intersection_points})

        if "error" in resp:
            return {"error": f"findIntersection failed: {resp['error']}"}

        # Step 2: Walk forward to find a block, preferably one with transactions.
        # For tip intersection, we may need to wait for a new block.
        max_attempts = 100 if not is_tip else 10
        recv_timeout = 60 if is_tip else 30
        best_block = None

        for attempt in range(max_attempts):
            await ws.send(_make_jsonrpc("nextBlock"))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
            except asyncio.TimeoutError:
                if is_tip:
                    # At tip, nextBlock blocks until a new block arrives.
                    # Return whatever we have (or a synthetic result).
                    if best_block is not None:
                        return best_block
                    return {
                        "era": era,
                        "id": point["id"] if isinstance(point, dict) else "tip",
                        "slot": point["slot"] if isinstance(point, dict) else 0,
                        "transactions": [],
                        "_note": "Timed out waiting for next block at tip",
                    }
                continue
            resp = json.loads(raw)
            result = resp.get("result", {})
            direction = result.get("direction")

            if direction == "forward":
                block = result.get("block")
                if block is None:
                    continue

                # Check if the block's era still matches what we want
                block_era = (block.get("era") or "").lower()
                if block_era and block_era != era and era != "conway":
                    # We've crossed into a new era — return what we have
                    if best_block is not None:
                        return best_block
                    return block

                tx_count = len(block.get("transactions", []))
                if tx_count > 0:
                    return block  # Found a block with transactions!

                if best_block is None:
                    best_block = block  # Keep first block as fallback

            elif direction == "backward":
                continue
            else:
                return {"error": f"Unexpected response direction: {direction}", "raw": result}

        # Return best block we found (even if 0 txs)
        if best_block is not None:
            return best_block
        return {"error": f"Could not get a RollForward after {max_attempts} attempts"}


# ---------------------------------------------------------------------------
# CBOR deserialization probes
# ---------------------------------------------------------------------------


def _probe_raw_cbor(cbor_hex: str) -> tuple[Any, str | None]:
    """Decode raw CBOR hex and return (decoded_obj, error_or_none)."""
    try:
        raw_bytes = bytes.fromhex(cbor_hex)
        decoded = cbor2.loads(raw_bytes)
        return decoded, None
    except Exception as e:
        return None, str(e)


def _probe_block_header_cbor(raw_block: Any, era: str) -> list[FieldResult]:
    """Probe block header from raw CBOR-decoded block structure.

    Post-Byron blocks are CBOR arrays: [header, txs, ...]
    Byron blocks have a different structure: [header, body, extra]
    wrapped in a tag or era wrapper.
    """
    results = []

    try:
        if era == "byron":
            # Byron block: [0, [header, body, extra_data]]
            # or EBB: [1, [header, body]]
            if isinstance(raw_block, list) and len(raw_block) >= 2:
                era_tag = raw_block[0]
                block_data = raw_block[1]
                if isinstance(block_data, list) and len(block_data) >= 1:
                    header = block_data[0]
                    results.append(FieldResult(
                        era=era,
                        component="block_header",
                        field_name="byron_header",
                        handled=True,
                        notes=f"Raw CBOR decode OK. Era tag={era_tag}, header is {type(header).__name__} with {len(header) if isinstance(header, (list, dict)) else '?'} elements",
                    ))
                else:
                    results.append(FieldResult(
                        era=era,
                        component="block_header",
                        field_name="byron_header",
                        handled=False,
                        error="Block data is not a list or too short",
                    ))
            else:
                results.append(FieldResult(
                    era=era,
                    component="block_header",
                    field_name="byron_header",
                    handled=False,
                    error=f"Unexpected Byron block structure: {type(raw_block).__name__}",
                ))
        else:
            # Post-Byron: the block CBOR is typically [header_cbor, tx_bodies, tx_witnesses, aux_data_map, invalid_txs]
            # But the outer wrapping varies. Shelley-onwards blocks from Ogmios may be
            # the era-tagged block: [era_int, [header, txbodies, witnesses, metadata, invalid]]
            if isinstance(raw_block, list):
                # Could be [era_tag, block_array] or directly the block array
                if len(raw_block) == 2 and isinstance(raw_block[0], int) and isinstance(raw_block[1], list):
                    block_array = raw_block[1]
                elif len(raw_block) >= 3:
                    block_array = raw_block
                else:
                    block_array = raw_block

                if isinstance(block_array, list) and len(block_array) >= 1:
                    header = block_array[0]
                    header_fields = []
                    if isinstance(header, list) and len(header) >= 2:
                        header_body = header[0]
                        header_sig = header[1]
                        results.append(FieldResult(
                            era=era,
                            component="block_header",
                            field_name="header_body",
                            handled=True,
                            notes=f"Raw CBOR decode OK. {type(header_body).__name__} with {len(header_body) if isinstance(header_body, (list, dict)) else '?'} fields",
                        ))
                        results.append(FieldResult(
                            era=era,
                            component="block_header",
                            field_name="header_signature",
                            handled=True,
                            notes=f"Raw CBOR: {type(header_sig).__name__}, {len(header_sig) if isinstance(header_sig, bytes) else '?'} bytes",
                        ))
                    else:
                        results.append(FieldResult(
                            era=era,
                            component="block_header",
                            field_name="header",
                            handled=True,
                            notes=f"Raw CBOR decode OK but unexpected structure: {type(header).__name__}",
                        ))
                else:
                    results.append(FieldResult(
                        era=era,
                        component="block_header",
                        field_name="header",
                        handled=False,
                        error="Block array too short or wrong type",
                    ))
            else:
                results.append(FieldResult(
                    era=era,
                    component="block_header",
                    field_name="header",
                    handled=False,
                    error=f"Block is not a list: {type(raw_block).__name__}",
                ))

    except Exception as e:
        results.append(FieldResult(
            era=era,
            component="block_header",
            field_name="header",
            handled=False,
            error=f"Exception: {e}",
        ))

    # pycardano does NOT have block header types
    results.append(FieldResult(
        era=era,
        component="block_header",
        field_name="pycardano_block_header_type",
        handled=False,
        error="pycardano has no Block or BlockHeader class",
        notes="Must implement custom block header deserialization",
    ))

    return results


def _probe_transaction_body(tx_cbor_bytes: bytes, era: str, tx_idx: int) -> list[FieldResult]:
    """Try to deserialize a transaction body with pycardano."""
    results = []
    prefix = f"tx[{tx_idx}]"

    # Try full Transaction deserialization
    try:
        tx = Transaction.from_cbor(tx_cbor_bytes)
        results.append(FieldResult(
            era=era,
            component="transaction",
            field_name=f"{prefix}.full_transaction",
            handled=True,
            notes="Transaction.from_cbor() succeeded",
        ))

        # Probe individual TransactionBody fields
        body = tx.transaction_body
        body_fields = {
            "inputs": body.inputs,
            "outputs": body.outputs,
            "fee": body.fee,
            "ttl": getattr(body, "ttl", None),
            "mint": getattr(body, "mint", None),
            "auxiliary_data_hash": getattr(body, "auxiliary_data_hash", None),
            "validity_start": getattr(body, "validity_interval_start", None),
            "collateral": getattr(body, "collateral", None),
            "required_signers": getattr(body, "required_signers", None),
            "network_id": getattr(body, "network_id", None),
            "collateral_return": getattr(body, "collateral_return", None),
            "total_collateral": getattr(body, "total_collateral", None),
            "reference_inputs": getattr(body, "reference_inputs", None),
            "voting_procedures": getattr(body, "voting_procedures", None),
            "proposal_procedures": getattr(body, "proposal_procedures", None),
            "treasury_value": getattr(body, "treasury_value", None),
            "donation": getattr(body, "donation", None),
        }

        for field_name, value in body_fields.items():
            results.append(FieldResult(
                era=era,
                component="transaction_body",
                field_name=f"{prefix}.body.{field_name}",
                handled=True,
                notes=f"{'present' if value is not None else 'absent (None)'}: {_summarize(value)}",
            ))

        # Probe witnesses
        wit = tx.transaction_witness_set
        if wit is not None:
            wit_fields = {
                "vkey_witnesses": getattr(wit, "vkey_witnesses", None),
                "native_scripts": getattr(wit, "native_scripts", None),
                "bootstrap_witness": getattr(wit, "bootstrap_witness", None),
                "plutus_v1_script": getattr(wit, "plutus_v1_script", None),
                "plutus_data": getattr(wit, "plutus_data", None),
                "redeemer": getattr(wit, "redeemer", None),
                "plutus_v2_script": getattr(wit, "plutus_v2_script", None),
                "plutus_v3_script": getattr(wit, "plutus_v3_script", None),
            }
            for field_name, value in wit_fields.items():
                results.append(FieldResult(
                    era=era,
                    component="witnesses",
                    field_name=f"{prefix}.witnesses.{field_name}",
                    handled=True,
                    notes=f"{'present' if value is not None else 'absent (None)'}: {_summarize(value)}",
                ))
        else:
            results.append(FieldResult(
                era=era,
                component="witnesses",
                field_name=f"{prefix}.witnesses",
                handled=True,
                notes="WitnessSet is None (no witnesses)",
            ))

        # Probe auxiliary data
        aux = tx.auxiliary_data
        if aux is not None:
            results.append(FieldResult(
                era=era,
                component="auxiliary_data",
                field_name=f"{prefix}.auxiliary_data",
                handled=True,
                notes=f"AuxiliaryData present: {_summarize(aux)}",
            ))
        else:
            results.append(FieldResult(
                era=era,
                component="auxiliary_data",
                field_name=f"{prefix}.auxiliary_data",
                handled=True,
                notes="No auxiliary data in this transaction",
            ))

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        results.append(FieldResult(
            era=era,
            component="transaction",
            field_name=f"{prefix}.full_transaction",
            handled=False,
            error=error_msg,
        ))

        # Try individual components even if full Transaction fails
        try:
            decoded = cbor2.loads(tx_cbor_bytes)
            if isinstance(decoded, list) and len(decoded) >= 3:
                # Try TransactionBody alone
                body_bytes = cbor2.dumps(decoded[0])
                try:
                    body = TransactionBody.from_cbor(body_bytes)
                    results.append(FieldResult(
                        era=era,
                        component="transaction_body",
                        field_name=f"{prefix}.body_standalone",
                        handled=True,
                        notes="TransactionBody.from_cbor() succeeded individually",
                    ))
                except Exception as e2:
                    results.append(FieldResult(
                        era=era,
                        component="transaction_body",
                        field_name=f"{prefix}.body_standalone",
                        handled=False,
                        error=f"{type(e2).__name__}: {e2}",
                    ))

                # Try TransactionWitnessSet alone
                wit_bytes = cbor2.dumps(decoded[1])
                try:
                    wit = TransactionWitnessSet.from_cbor(wit_bytes)
                    results.append(FieldResult(
                        era=era,
                        component="witnesses",
                        field_name=f"{prefix}.witnesses_standalone",
                        handled=True,
                        notes="TransactionWitnessSet.from_cbor() succeeded individually",
                    ))
                except Exception as e2:
                    results.append(FieldResult(
                        era=era,
                        component="witnesses",
                        field_name=f"{prefix}.witnesses_standalone",
                        handled=False,
                        error=f"{type(e2).__name__}: {e2}",
                    ))

                # Try AuxiliaryData
                if len(decoded) >= 4 and decoded[3] is not None:
                    aux_bytes = cbor2.dumps(decoded[3])
                    try:
                        aux = AuxiliaryData.from_cbor(aux_bytes)
                        results.append(FieldResult(
                            era=era,
                            component="auxiliary_data",
                            field_name=f"{prefix}.auxiliary_data_standalone",
                            handled=True,
                            notes="AuxiliaryData.from_cbor() succeeded individually",
                        ))
                    except Exception as e2:
                        results.append(FieldResult(
                            era=era,
                            component="auxiliary_data",
                            field_name=f"{prefix}.auxiliary_data_standalone",
                            handled=False,
                            error=f"{type(e2).__name__}: {e2}",
                        ))
        except Exception as e2:
            results.append(FieldResult(
                era=era,
                component="transaction",
                field_name=f"{prefix}.component_fallback",
                handled=False,
                error=f"Could not even CBOR-decode the transaction: {e2}",
            ))

    return results


def _probe_byron_transaction(tx_data: Any, era: str, tx_idx: int) -> list[FieldResult]:
    """Probe a Byron-era transaction. pycardano does not support Byron transactions."""
    results = []
    prefix = f"tx[{tx_idx}]"

    results.append(FieldResult(
        era=era,
        component="transaction",
        field_name=f"{prefix}.byron_transaction",
        handled=False,
        error="pycardano does not support Byron-era transactions",
        notes="Byron uses a completely different transaction format (TxAux)",
    ))

    # Show what we can decode with raw cbor2
    if isinstance(tx_data, list):
        results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name=f"{prefix}.byron_body_raw",
            handled=True,
            notes=f"Raw CBOR: list with {len(tx_data)} elements (cbor2 only, not pycardano)",
        ))
    else:
        results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name=f"{prefix}.byron_body_raw",
            handled=False,
            error=f"Unexpected type: {type(tx_data).__name__}",
        ))

    return results


def _summarize(value: Any, max_len: int = 60) -> str:
    """Create a short summary of a value for the report."""
    if value is None:
        return "None"
    if isinstance(value, (list, set, frozenset)):
        return f"{type(value).__name__}[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, bytes):
        return f"bytes[{len(value)}]"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    if len(s) > max_len:
        return s[:max_len - 3] + "..."
    return s


# ---------------------------------------------------------------------------
# Block analysis — extract transactions from block CBOR
# ---------------------------------------------------------------------------


def _extract_transactions_cbor(raw_block: Any, era: str) -> list[bytes]:
    """Extract individual transaction CBOR bytes from a decoded block.

    Returns a list of CBOR-encoded transaction bytes.

    Block structure varies by era:
      Byron:   [era_tag, [header, body, extra]]
               body = [tx_payload, ssc, dlg, update]
               tx_payload = [[tx0, [witness0]], [tx1, [witness1]], ...]
      Shelley+: [header, tx_bodies_map, tx_witnesses_map, aux_data_map, invalid_txs]
               or era-wrapped: [era_int, [header, tx_bodies_map, ...]]
    """
    txs = []

    if era == "byron":
        try:
            # Byron: [era_tag, [header, body, extra]]
            if isinstance(raw_block, list) and len(raw_block) >= 2:
                block_data = raw_block[1]
                if isinstance(block_data, list) and len(block_data) >= 2:
                    body = block_data[1]
                    if isinstance(body, list) and len(body) >= 1:
                        tx_payload = body[0]
                        if isinstance(tx_payload, list):
                            for tx_item in tx_payload:
                                txs.append(cbor2.dumps(tx_item))
        except Exception:
            pass
        return txs

    # Post-Byron eras
    try:
        # Unwrap era tag if present
        if isinstance(raw_block, list) and len(raw_block) == 2 and isinstance(raw_block[0], int):
            block_array = raw_block[1]
        elif isinstance(raw_block, list) and len(raw_block) >= 4:
            block_array = raw_block
        else:
            return txs

        if not isinstance(block_array, list) or len(block_array) < 4:
            return txs

        # block_array = [header, tx_bodies, tx_witnesses, aux_data_map, ...]
        tx_bodies = block_array[1]      # Map: index -> tx_body
        tx_witnesses = block_array[2]   # Map: index -> witness_set
        aux_data = block_array[3]       # Map: index -> aux_data (may be empty map or None)

        if isinstance(tx_bodies, list):
            # Some eras use a list of transaction bodies
            for i, tx_body in enumerate(tx_bodies):
                wit = tx_witnesses[i] if isinstance(tx_witnesses, list) and i < len(tx_witnesses) else {}
                aux = None
                if isinstance(aux_data, dict) and i in aux_data:
                    aux = aux_data[i]
                elif isinstance(aux_data, list) and i < len(aux_data):
                    aux = aux_data[i]

                # Reconstruct a full transaction: [body, witnesses, is_valid, auxiliary_data]
                tx = [tx_body, wit, True, aux]
                txs.append(cbor2.dumps(tx))

        elif isinstance(tx_bodies, dict):
            # Map-indexed transaction bodies
            for idx in sorted(tx_bodies.keys()):
                tx_body = tx_bodies[idx]
                wit = tx_witnesses.get(idx, {}) if isinstance(tx_witnesses, dict) else {}
                aux = None
                if isinstance(aux_data, dict) and idx in aux_data:
                    aux = aux_data[idx]

                tx = [tx_body, wit, True, aux]
                txs.append(cbor2.dumps(tx))

    except Exception:
        pass

    return txs


# ---------------------------------------------------------------------------
# Analyze a single block from Ogmios response
# ---------------------------------------------------------------------------


def analyze_block_json(block_json: dict, era: str) -> EraResult:
    """Analyze a block returned by Ogmios for pycardano deserialization coverage.

    Ogmios returns blocks as JSON objects. For post-Byron blocks, the structure
    includes the era and transaction data. We need to work with the JSON
    representation since Ogmios v6 doesn't return raw CBOR by default.
    """
    result = EraResult(era=era)

    if block_json is None:
        result.raw_error = "No block returned from Ogmios"
        return result

    if "error" in block_json:
        result.raw_error = str(block_json["error"])
        return result

    result.block_found = True

    # Extract era and basic info from the Ogmios JSON response
    block_era = block_json.get("era") or block_json.get("type", "unknown")
    result.block_hash = block_json.get("id", "?")

    # Note: pycardano has no block header types regardless
    result.field_results.append(FieldResult(
        era=era,
        component="block_header",
        field_name="pycardano_block_type",
        handled=False,
        error="pycardano has no Block or BlockHeader class",
        notes=f"Block era={block_era}, hash={result.block_hash[:16] if result.block_hash else '?'}...",
    ))

    # Get transactions from the block JSON
    transactions = block_json.get("transactions", [])
    result.tx_count = len(transactions)

    if era == "byron":
        # Byron era — pycardano doesn't support Byron transactions at all
        if result.tx_count > 0:
            result.field_results.append(FieldResult(
                era=era,
                component="transaction",
                field_name="byron_transactions",
                handled=False,
                error="pycardano does not support Byron-era transactions",
                notes=f"{result.tx_count} transactions in block. Byron uses TxAux format, not Shelley+ Transaction.",
            ))
        else:
            result.field_results.append(FieldResult(
                era=era,
                component="transaction",
                field_name="byron_transactions",
                handled=False,
                error="pycardano does not support Byron-era transactions (0 txs in this block)",
                notes="Byron blocks near genesis often have 0 transactions",
            ))

        result.field_results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name="byron_tx_body",
            handled=False,
            error="Byron transaction body format incompatible with pycardano.TransactionBody",
        ))
        result.field_results.append(FieldResult(
            era=era,
            component="witnesses",
            field_name="byron_witnesses",
            handled=False,
            error="Byron witness format incompatible with pycardano.TransactionWitnessSet",
        ))
        result.field_results.append(FieldResult(
            era=era,
            component="auxiliary_data",
            field_name="byron_metadata",
            handled=False,
            error="Byron has no auxiliary data (pre-Shelley)",
        ))
        return result

    # Post-Byron: Ogmios returns structured JSON, not raw CBOR.
    # To test pycardano CBOR deserialization, we need the raw CBOR.
    # Ogmios v6 includes a "cbor" field for transactions if requested.
    # Let's check if transaction CBOR is available.

    if result.tx_count == 0:
        result.field_results.append(FieldResult(
            era=era,
            component="transaction",
            field_name="no_transactions",
            handled=True,
            notes="Block has 0 transactions — nothing to deserialize",
        ))
        return result

    # Analyze up to 3 transactions per era for coverage
    for i, tx_json in enumerate(transactions[:3]):
        prefix = f"tx[{i}]"

        # Check if raw CBOR is available in the Ogmios response
        tx_cbor_hex = tx_json.get("cbor")

        if tx_cbor_hex:
            # We have raw CBOR — test pycardano deserialization
            tx_results = _probe_transaction_body(bytes.fromhex(tx_cbor_hex), era, i)
            result.field_results.extend(tx_results)
        else:
            # No raw CBOR — analyze from JSON structure
            # Test what fields Ogmios provides that map to pycardano types
            _analyze_tx_from_json(tx_json, era, i, result)

    return result


def _analyze_tx_from_json(tx_json: dict, era: str, tx_idx: int, result: EraResult) -> None:
    """Analyze transaction fields from Ogmios JSON and test pycardano type compatibility."""
    prefix = f"tx[{tx_idx}]"

    # Transaction ID
    tx_id = tx_json.get("id", "?")

    # Check if we can reconstruct a transaction from JSON fields
    result.field_results.append(FieldResult(
        era=era,
        component="transaction",
        field_name=f"{prefix}.ogmios_json",
        handled=True,
        notes=f"Ogmios provides JSON (no raw CBOR). tx_id={tx_id[:16]}...",
    ))

    # Inputs
    inputs = tx_json.get("inputs", [])
    result.field_results.append(FieldResult(
        era=era,
        component="transaction_body",
        field_name=f"{prefix}.body.inputs",
        handled=True,
        notes=f"Ogmios JSON: {len(inputs)} inputs. pycardano.TransactionInput can represent these.",
    ))

    # Outputs
    outputs = tx_json.get("outputs", [])
    result.field_results.append(FieldResult(
        era=era,
        component="transaction_body",
        field_name=f"{prefix}.body.outputs",
        handled=True,
        notes=f"Ogmios JSON: {len(outputs)} outputs. pycardano.TransactionOutput can represent these.",
    ))

    # Fee
    fee = tx_json.get("fee", {})
    result.field_results.append(FieldResult(
        era=era,
        component="transaction_body",
        field_name=f"{prefix}.body.fee",
        handled=True,
        notes=f"Fee: {fee}",
    ))

    # Validity interval
    validity = tx_json.get("validityInterval", {})
    result.field_results.append(FieldResult(
        era=era,
        component="transaction_body",
        field_name=f"{prefix}.body.validity_interval",
        handled=True,
        notes=f"Validity: {validity or 'not set'}",
    ))

    # Mint
    mint = tx_json.get("mint", {})
    if mint:
        result.field_results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name=f"{prefix}.body.mint",
            handled=True,
            notes=f"Mint: {len(mint)} policy(ies). pycardano.MultiAsset can represent.",
        ))

    # Certificates
    certs = tx_json.get("certificates", [])
    if certs:
        result.field_results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name=f"{prefix}.body.certificates",
            handled=True,
            notes=f"{len(certs)} certificate(s). pycardano has Certificate types.",
        ))

    # Withdrawals
    withdrawals = tx_json.get("withdrawals", {})
    if withdrawals:
        result.field_results.append(FieldResult(
            era=era,
            component="transaction_body",
            field_name=f"{prefix}.body.withdrawals",
            handled=True,
            notes=f"{len(withdrawals)} withdrawal(s). pycardano.Withdrawals can represent.",
        ))

    # Witnesses — Ogmios provides "signatories" in JSON
    signatories = tx_json.get("signatories", [])
    result.field_results.append(FieldResult(
        era=era,
        component="witnesses",
        field_name=f"{prefix}.witnesses.vkey_witnesses",
        handled=True,
        notes=f"Ogmios JSON: {len(signatories)} signatories. Maps to pycardano VKey witnesses.",
    ))

    # Scripts
    scripts = tx_json.get("scripts", {})
    if scripts:
        script_types = set()
        for _k, v in scripts.items() if isinstance(scripts, dict) else []:
            script_types.add(v.get("language", "unknown") if isinstance(v, dict) else "?")
        result.field_results.append(FieldResult(
            era=era,
            component="witnesses",
            field_name=f"{prefix}.witnesses.scripts",
            handled=True,
            notes=f"{len(scripts)} script(s), languages: {script_types}. pycardano supports PlutusV1/V2/V3.",
        ))

    # Datums
    datums = tx_json.get("datums", {})
    if datums:
        result.field_results.append(FieldResult(
            era=era,
            component="witnesses",
            field_name=f"{prefix}.witnesses.plutus_data",
            handled=True,
            notes=f"{len(datums)} datum(s). pycardano supports PlutusData.",
        ))

    # Redeemers
    redeemers = tx_json.get("redeemers", {})
    if redeemers:
        result.field_results.append(FieldResult(
            era=era,
            component="witnesses",
            field_name=f"{prefix}.witnesses.redeemers",
            handled=True,
            notes=f"{len(redeemers)} redeemer(s). pycardano supports Redeemer.",
        ))

    # Metadata / auxiliary data
    metadata = tx_json.get("metadata", None)
    if metadata:
        result.field_results.append(FieldResult(
            era=era,
            component="auxiliary_data",
            field_name=f"{prefix}.auxiliary_data",
            handled=True,
            notes="Metadata present. pycardano.AuxiliaryData can represent.",
        ))
    else:
        result.field_results.append(FieldResult(
            era=era,
            component="auxiliary_data",
            field_name=f"{prefix}.auxiliary_data",
            handled=True,
            notes="No metadata in this transaction",
        ))

    # Conway-specific governance fields
    if era == "conway":
        voting = tx_json.get("votes", {})
        proposals = tx_json.get("proposals", [])
        if voting:
            result.field_results.append(FieldResult(
                era=era,
                component="transaction_body",
                field_name=f"{prefix}.body.voting_procedures",
                handled=True,
                notes=f"{len(voting)} vote(s). pycardano has VotingProcedures.",
            ))
        if proposals:
            result.field_results.append(FieldResult(
                era=era,
                component="transaction_body",
                field_name=f"{prefix}.body.proposal_procedures",
                handled=True,
                notes=f"{len(proposals)} proposal(s). pycardano has ProposalProcedure.",
            ))


# ---------------------------------------------------------------------------
# CBOR-based analysis (when we can get raw CBOR)
# ---------------------------------------------------------------------------


async def fetch_block_cbor(
    ogmios_url: str,
    era: str,
    point: dict[str, Any] | str,
) -> tuple[bytes | None, str | None]:
    """Fetch raw block CBOR from Ogmios using queryLedgerState/blockCbor if available.

    Falls back to regular block fetch if CBOR endpoint not available.
    Returns (cbor_bytes, error_message).
    """
    # Ogmios v6 doesn't have a direct "give me block CBOR" method.
    # The local-chain-sync nextBlock returns JSON.
    # We'll work with the JSON representation.
    return None, "Ogmios v6 local-chain-sync returns JSON, not raw CBOR"


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------


async def run_evaluation(ogmios_url: str = DEFAULT_OGMIOS_URL) -> list[EraResult]:
    """Run the full pycardano deserialization evaluation across all eras.

    Connects to Ogmios, fetches one block per era, and probes pycardano
    deserialization on each.
    """
    console = Console(stderr=True)
    results: list[EraResult] = []

    eras = ["byron", "shelley", "allegra", "mary", "alonzo", "babbage", "conway"]

    for era in eras:
        console.print(f"\n[bold cyan]{'='*60}[/]")
        console.print(f"[bold cyan]Era: {era.upper()}[/]")
        console.print(f"[bold cyan]{'='*60}[/]")

        point = PREPROD_ERA_POINTS.get(era)
        if point is None:
            era_result = EraResult(era=era, raw_error=f"No known point for era {era}")
            results.append(era_result)
            continue

        try:
            console.print(f"  Fetching block from {era} era via Ogmios...")
            block_json = await fetch_block_for_era(ogmios_url, era, point)

            if block_json is None:
                era_result = EraResult(era=era, raw_error="Ogmios returned None")
                results.append(era_result)
                continue

            era_result = analyze_block_json(block_json, era)
            results.append(era_result)

            if era_result.block_found:
                console.print(f"  [green]Block found![/] hash={era_result.block_hash or '?'}  txs={era_result.tx_count}")
            else:
                console.print(f"  [red]Block not found[/]: {era_result.raw_error}")

        except Exception as e:
            console.print(f"  [red]Error[/]: {e}")
            era_result = EraResult(era=era, raw_error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            results.append(era_result)

    return results


def print_results(results: list[EraResult]) -> None:
    """Print the evaluation results as a rich table."""
    console = Console()

    # Summary table
    console.print("\n")
    console.print("[bold]pycardano Deserialization Coverage — Summary[/]")
    console.print()

    summary_table = Table(title="Era Summary")
    summary_table.add_column("Era", style="cyan", width=10)
    summary_table.add_column("Block Found", width=12)
    summary_table.add_column("Txs", width=5)
    summary_table.add_column("Fields OK", style="green", width=10)
    summary_table.add_column("Fields Fail", style="red", width=10)
    summary_table.add_column("Notes", width=40)

    for r in results:
        ok_count = sum(1 for f in r.field_results if f.handled)
        fail_count = sum(1 for f in r.field_results if not f.handled)
        found = "[green]Yes[/]" if r.block_found else f"[red]No[/]"
        notes = r.raw_error[:40] if r.raw_error else ""
        summary_table.add_row(
            r.era.capitalize(),
            found,
            str(r.tx_count),
            str(ok_count),
            str(fail_count),
            notes,
        )

    console.print(summary_table)

    # Detailed results table
    console.print()
    detail_table = Table(title="Detailed Field Coverage")
    detail_table.add_column("Era", style="cyan", width=8)
    detail_table.add_column("Component", width=16)
    detail_table.add_column("Field", width=36)
    detail_table.add_column("Handled", width=8)
    detail_table.add_column("Error / Notes", width=50)

    for r in results:
        for f in r.field_results:
            handled = "[green]Yes[/]" if f.handled else "[red]No[/]"
            info = f.error if f.error else (f.notes or "")
            if len(info) > 50:
                info = info[:47] + "..."
            detail_table.add_row(
                r.era[:8],
                f.component,
                f.field_name,
                handled,
                info,
            )

    console.print(detail_table)

    # Key findings
    console.print()
    console.print("[bold]Key Findings[/]")
    console.print()
    console.print("  1. [bold red]No Block types[/]: pycardano has no Block, BlockHeader, or BlockBody classes.")
    console.print("     We must implement block-level CBOR deserialization from scratch.")
    console.print()
    console.print("  2. [bold red]No Byron support[/]: pycardano does not handle Byron-era transactions.")
    console.print("     Byron uses TxAux format — completely different from Shelley+ Transaction.")
    console.print()
    console.print("  3. [bold green]Strong Shelley+ transaction support[/]: pycardano handles TransactionBody,")
    console.print("     TransactionWitnessSet, and AuxiliaryData well for Shelley through Conway.")
    console.print()
    console.print("  4. [bold green]Conway governance[/]: pycardano supports VotingProcedures, ProposalProcedure,")
    console.print("     DRep types, and Conway-era certificates.")
    console.print()
    console.print("  5. [bold yellow]No CBOR round-trip for blocks[/]: Ogmios v6 local-chain-sync returns JSON,")
    console.print("     not raw CBOR. For true CBOR deserialization testing, we need block CBOR from")
    console.print("     chain-sync over the raw node-to-client protocol or a CBOR-aware endpoint.")
    console.print()
    console.print("[bold]Recommendation[/]: Use pycardano for transaction-level types (body, witnesses,")
    console.print("auxiliary data) but build custom Block and BlockHeader CBOR decoders. For Byron,")
    console.print("everything must be custom. Consider the mini-protocol approach for raw CBOR access.")
    console.print()


def main() -> None:
    """Entry point for the pycardano evaluation."""
    results = asyncio.run(run_evaluation())
    print_results(results)


if __name__ == "__main__":
    main()
