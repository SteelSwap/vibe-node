#!/usr/bin/env python3
"""Generate block CBOR test fixtures from cardano-node via N2C chain-sync.

Connects directly to the cardano-node Unix socket using a minimal Ouroboros
N2C (node-to-client) multiplexer and local-chain-sync client to fetch raw
block CBOR. Also queries Ogmios for block metadata (hash, era, tx count)
as the oracle of truth.

This script must have access to the cardano-node Unix socket. Two modes:

    # Mode 1: Run inside Docker with node socket mounted
    docker run --rm \\
      -v vibe-node_cardano-node-ipc:/ipc:ro \\
      -v $(pwd)/tests/conformance:/tests/conformance \\
      -v $(pwd)/packages/vibe-cardano/src:/src \\
      -e PYTHONPATH=/src \\
      --network vibe-node_vibe-node \\
      python:3.14-slim \\
      bash -c "pip install cbor2 websockets && python3 /tests/conformance/generate_fixtures.py"

    # Mode 2: Run locally if node socket is accessible
    CARDANO_NODE_SOCKET_PATH=/path/to/node.socket uv run python tests/conformance/generate_fixtures.py

Environment variables:
    CARDANO_NODE_SOCKET_PATH  Path to node socket (default: /ipc/node.socket)
    NETWORK_MAGIC             Network magic number (default: 1 for preprod)
    OGMIOS_URL                Ogmios WebSocket URL (default: ws://ogmios:1337)
    FIXTURE_DIR               Output directory (default: tests/conformance/fixtures/blocks)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(os.environ.get(
    "FIXTURE_DIR",
    str(Path(__file__).parent / "fixtures" / "blocks"),
))
NODE_SOCKET = os.environ.get("CARDANO_NODE_SOCKET_PATH", "/ipc/node.socket")
NETWORK_MAGIC = int(os.environ.get("NETWORK_MAGIC", "1"))
OGMIOS_URL = os.environ.get("OGMIOS_URL", "ws://ogmios:1337")


# ---------------------------------------------------------------------------
# Minimal Ouroboros multiplexer (N2C)
# ---------------------------------------------------------------------------

def _mux_header(protocol_id: int, payload_len: int) -> bytes:
    """Encode a mux segment header (8 bytes)."""
    return struct.pack("!IHH", 0, protocol_id, payload_len)


def _send_mux(sock: socket.socket, protocol_id: int, payload: bytes) -> None:
    """Send a multiplexed message."""
    header = _mux_header(protocol_id, len(payload))
    sock.sendall(header + payload)


def _recv_mux_segment(sock: socket.socket) -> tuple[int, bytes]:
    """Receive a single mux segment."""
    header = b""
    while len(header) < 8:
        chunk = sock.recv(8 - len(header))
        if not chunk:
            raise ConnectionError("Socket closed")
        header += chunk

    _ts, proto_id, payload_len = struct.unpack("!IHH", header)
    proto_id_clean = proto_id & 0x7FFF

    payload = b""
    while len(payload) < payload_len:
        chunk = sock.recv(payload_len - len(payload))
        if not chunk:
            raise ConnectionError("Socket closed during payload read")
        payload += chunk

    return proto_id_clean, payload


def _recv_mux(sock: socket.socket) -> tuple[int, bytes]:
    """Receive a complete mux message, reassembling multi-segment payloads."""
    import cbor2

    proto_id, payload = _recv_mux_segment(sock)

    try:
        cbor2.loads(payload)
        return proto_id, payload
    except Exception:
        pass

    buffer = bytearray(payload)
    for _ in range(1000):
        next_proto, next_payload = _recv_mux_segment(sock)
        assert next_proto == proto_id, (
            f"Expected continuation on proto {proto_id}, got {next_proto}"
        )
        buffer.extend(next_payload)

        try:
            cbor2.loads(bytes(buffer))
            return proto_id, bytes(buffer)
        except Exception:
            continue

    raise RuntimeError("Could not reassemble complete message")


# ---------------------------------------------------------------------------
# Minimal N2C Handshake
# ---------------------------------------------------------------------------

def _handshake_propose(network_magic: int) -> bytes:
    """Build MsgProposeVersions for N2C handshake."""
    import cbor2
    versions = {}
    for v in range(16, 23):
        versions[0x8000 | v] = [network_magic, False]
    return cbor2.dumps([0, versions])


def _handshake_accept(payload: bytes) -> int:
    """Parse MsgAcceptVersion. Returns accepted version number."""
    import cbor2
    msg = cbor2.loads(payload)
    if isinstance(msg, list) and len(msg) >= 2 and msg[0] == 1:
        return msg[1]
    raise RuntimeError(f"Handshake rejected: {msg}")


# ---------------------------------------------------------------------------
# Minimal N2C Local Chain-Sync
# ---------------------------------------------------------------------------

def _chain_sync_find_intersect_origin() -> bytes:
    """Build MsgFindIntersect with origin point."""
    import cbor2
    return cbor2.dumps([4, [[]]])  # [4, [origin]] where origin = []


def _chain_sync_request_next() -> bytes:
    """Build MsgRequestNext."""
    import cbor2
    return cbor2.dumps([0])


def _parse_chain_sync_response(payload: bytes) -> dict:
    """Parse a chain-sync response."""
    import cbor2

    msg = cbor2.loads(payload)
    if not isinstance(msg, list) or len(msg) < 1:
        return {"type": "unknown", "raw": msg}

    tag = msg[0]
    if tag == 1:
        return {"type": "awaitReply"}
    elif tag == 2:
        # MsgRollForward [2, block_data, tip]
        block_data = msg[1] if len(msg) > 1 else None
        if isinstance(block_data, cbor2.CBORTag) and block_data.tag == 24:
            return {"type": "rollForward", "block_cbor": block_data.value}
        elif isinstance(block_data, bytes):
            return {"type": "rollForward", "block_cbor": block_data}
        return {"type": "rollForward", "block_data": block_data}
    elif tag == 3:
        return {"type": "rollBackward", "point": msg[1] if len(msg) > 1 else None}
    elif tag == 5:
        return {"type": "intersectFound", "point": msg[1] if len(msg) > 1 else None}
    elif tag == 6:
        return {"type": "intersectNotFound"}
    else:
        return {"type": "unknown", "tag": tag}


# ---------------------------------------------------------------------------
# Ogmios metadata query
# ---------------------------------------------------------------------------

async def _query_ogmios_metadata(ogmios_url: str, slots: list[int]) -> dict[int, dict]:
    """Query Ogmios for block metadata at specific slots."""
    import websockets

    metadata: dict[int, dict] = {}
    slot_set = set(slots)

    try:
        async with websockets.connect(ogmios_url) as ws:
            await ws.send(json.dumps({
                "jsonrpc": "2.0",
                "method": "findIntersection",
                "params": {"points": ["origin"]},
                "id": "meta-start",
            }))
            resp = json.loads(await ws.recv())
            if "error" in resp:
                print(f"WARNING: Ogmios findIntersection failed: {resp['error']}")
                return metadata

            max_slot = max(slots) if slots else 0
            for _ in range(max_slot + 100_000):
                if len(metadata) >= len(slots):
                    break

                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "nextBlock",
                    "id": "meta",
                }))
                resp = json.loads(await ws.recv())
                result = resp.get("result", {})

                if result.get("direction") == "forward":
                    block = result.get("block", {})
                    if isinstance(block, dict):
                        block_slot = block.get("slot")
                        if block_slot in slot_set:
                            txs = block.get("transactions", [])
                            metadata[block_slot] = {
                                "hash": block.get("id"),
                                "era": (block.get("era") or "").lower(),
                                "height": block.get("height"),
                                "tx_count": len(txs) if isinstance(txs, list) else 0,
                            }
                        if block_slot and block_slot > max_slot:
                            break
    except Exception as e:
        print(f"WARNING: Ogmios query failed: {e}")

    return metadata


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _collect_blocks_from_node(target_count: int = 12) -> list[dict]:
    """Connect to cardano-node and collect post-Byron blocks."""
    blocks: list[dict] = []

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(NODE_SOCKET)
        print("Connected to cardano-node")

        # Handshake
        _send_mux(sock, 0, _handshake_propose(NETWORK_MAGIC))
        proto_id, resp_payload = _recv_mux(sock)
        version = _handshake_accept(resp_payload)
        print(f"Handshake accepted, version {version & 0x7FFF}")

        # FindIntersect at origin
        _send_mux(sock, 5, _chain_sync_find_intersect_origin())
        proto_id, resp_payload = _recv_mux(sock)
        resp = _parse_chain_sync_response(resp_payload)
        if resp["type"] != "intersectFound":
            print(f"ERROR: FindIntersect failed: {resp}")
            return blocks
        print("FindIntersect at origin: OK")

        # Walk forward, collecting blocks
        # Inline _strip_tag and Era to avoid dependency on vibe-core
        from enum import IntEnum

        class Era(IntEnum):
            BYRON_MAIN = 0
            BYRON_EBB = 1
            SHELLEY = 2
            ALLEGRA = 3
            MARY = 4
            ALONZO = 5
            BABBAGE = 6
            CONWAY = 7

        def _strip_tag(cbor_bytes: bytes) -> tuple:
            if len(cbor_bytes) < 1:
                raise ValueError("Empty CBOR bytes")
            initial = cbor_bytes[0]
            major_type = initial >> 5
            additional = initial & 0x1F
            if major_type != 6:
                raise ValueError(
                    f"Expected CBOR tag (major type 6), got major type {major_type}")
            if additional <= 23:
                return additional, cbor_bytes[1:]
            elif additional == 24:
                return cbor_bytes[1], cbor_bytes[2:]
            else:
                raise ValueError(f"Unexpected additional info {additional}")

        era_counts: dict[str, int] = {}
        target_per_era = 2
        max_walk = 1_000_000

        for i in range(max_walk):
            _send_mux(sock, 5, _chain_sync_request_next())
            proto_id, resp_payload = _recv_mux(sock)
            resp = _parse_chain_sync_response(resp_payload)

            if i < 5:
                print(f"  Block {i}: proto={proto_id}, type={resp['type']}, "
                      f"payload_len={len(resp_payload)}, keys={list(resp.keys())}")
                if resp["type"] == "rollForward" and resp.get("block_cbor") is None:
                    # Debug: show what block_data looks like
                    import cbor2 as _cbor2
                    raw_msg = _cbor2.loads(resp_payload)
                    if isinstance(raw_msg, list) and len(raw_msg) > 1:
                        bd = raw_msg[1]
                        print(f"    block_data type: {type(bd).__name__}")
                        if isinstance(bd, _cbor2.CBORTag):
                            print(f"    CBORTag: tag={bd.tag}, value type={type(bd.value).__name__}, "
                                  f"value len={len(bd.value) if isinstance(bd.value, (bytes, list)) else '?'}")
                        elif isinstance(bd, bytes):
                            print(f"    bytes len={len(bd)}, first 20 hex: {bd[:20].hex()}")
                        elif isinstance(bd, list):
                            print(f"    list len={len(bd)}")
                        else:
                            print(f"    value: {str(bd)[:200]}")

            if resp["type"] == "awaitReply":
                # At tip, get the actual response
                proto_id, resp_payload = _recv_mux(sock)
                resp = _parse_chain_sync_response(resp_payload)

            if resp["type"] == "rollBackward":
                continue
            elif resp["type"] != "rollForward":
                if i == 0:
                    print(f"First response type: {resp['type']}")
                    print(f"  Keys: {list(resp.keys())}")
                print(f"Unexpected response at block {i}: {resp['type']}")
                break

            block_cbor = resp.get("block_cbor")
            if block_cbor is None:
                if i < 3:
                    print(f"  Block {i}: rollForward but no block_cbor, "
                          f"keys: {list(resp.keys())}")
                continue

            if i < 5:
                print(f"    block_cbor type={type(block_cbor).__name__}, "
                      f"len={len(block_cbor)}, first_bytes={block_cbor[:4].hex() if isinstance(block_cbor, bytes) else 'N/A'}")

            # N2C local chain-sync returns blocks as [era_id, block_data]
            # instead of the N2N CBOR tag wrapping. We need to handle both.
            import cbor2 as _cbor2
            try:
                # Try N2N format first (CBOR tag)
                tag_num, _ = _strip_tag(block_cbor)
                era = Era(tag_num)
                tagged_block = block_cbor  # Already in tagged format
            except ValueError:
                # N2C format: [era_id, serialised_block]
                try:
                    wrapper = _cbor2.loads(block_cbor)
                    if isinstance(wrapper, list) and len(wrapper) == 2:
                        era_id = wrapper[0]
                        era = Era(era_id)
                        # Reconstruct the tagged block CBOR:
                        # Prepend the CBOR tag byte for the era
                        if era_id <= 23:
                            tag_byte = bytes([0xC0 | era_id])
                        else:
                            tag_byte = bytes([0xD8, era_id])
                        # The inner block data might be bytes (serialised)
                        # or already decoded CBOR
                        inner = wrapper[1]
                        if isinstance(inner, bytes):
                            tagged_block = tag_byte + inner
                        else:
                            tagged_block = tag_byte + _cbor2.dumps(inner)
                    else:
                        if i < 5:
                            print(f"    Unknown block format: {type(wrapper)}")
                        continue
                except Exception as e2:
                    if i < 5:
                        print(f"    Block parse failed: {e2}")
                    continue
            except Exception as e:
                if i < 5:
                    print(f"    Unexpected era error: {type(e).__name__}: {e}")
                continue

            if era in (Era.BYRON_MAIN, Era.BYRON_EBB):
                if i % 1000 == 0:
                    print(f"  Walking Byron... block {i}")
                continue

            era_name = era.name.lower()
            era_count = era_counts.get(era_name, 0)

            if era_count < target_per_era:
                blocks.append({
                    "cbor": tagged_block.hex(),
                    "era_tag": era.value,
                    "era_name": era_name,
                })
                era_counts[era_name] = era_count + 1
                print(f"  Collected {era_name} block ({era_count + 1}/{target_per_era})")

            # Check if we have enough
            if len(blocks) >= target_count or all(
                era_counts.get(e, 0) >= target_per_era
                for e in ["shelley", "allegra"]  # minimum: these two
            ):
                # Keep going if we haven't hit later eras yet
                if all(
                    era_counts.get(e, 0) >= target_per_era
                    for e in ["shelley", "allegra", "mary", "alonzo", "babbage", "conway"]
                ):
                    break
                if len(blocks) >= target_count:
                    break

            if i % 5000 == 0 and i > 0:
                print(f"  ... walked {i} blocks, eras: {era_counts}")

    except Exception as e:
        print(f"ERROR during block collection: {e}")
        import traceback
        traceback.print_exc()
        print(f"  Blocks collected so far: {len(blocks)}")
    finally:
        sock.close()

    return blocks


def main() -> None:
    print(f"Node socket: {NODE_SOCKET}")
    print(f"Network magic: {NETWORK_MAGIC}")
    print(f"Fixture dir: {FIXTURE_DIR}")
    print()

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Collect block CBOR from node
    print("=== Step 1: Collecting block CBOR from cardano-node ===")
    raw_blocks = _collect_blocks_from_node()
    if not raw_blocks:
        print("No blocks collected. Check node socket path.")
        sys.exit(1)

    # Step 2: Decode slot from each block for Ogmios lookup
    import cbor2 as _cbor2

    def _strip_tag_inline(data: bytes) -> tuple:
        initial = data[0]
        if (initial >> 5) != 6:
            raise ValueError(f"Not a CBOR tag: major type {initial >> 5}")
        additional = initial & 0x1F
        if additional <= 23:
            return additional, data[1:]
        elif additional == 24:
            return data[1], data[2:]
        raise ValueError(f"Unexpected additional info {additional}")

    slots: list[int] = []
    for rb in raw_blocks:
        cbor_bytes = bytes.fromhex(rb["cbor"])
        tag_num, payload = _strip_tag_inline(cbor_bytes)
        block_array = _cbor2.loads(payload)
        if isinstance(block_array, list) and len(block_array) >= 1:
            header = block_array[0]
            if isinstance(header, list) and len(header) >= 1:
                header_body = header[0]
                if isinstance(header_body, list) and len(header_body) >= 2:
                    slot = header_body[1]
                    rb["slot"] = slot
                    slots.append(slot)
                    # Count transactions
                    if len(block_array) >= 2:
                        tx_bodies = block_array[1]
                        if isinstance(tx_bodies, (list, dict)):
                            rb["tx_count_decoded"] = len(tx_bodies)

    print(f"\nCollected {len(raw_blocks)} blocks at slots: {slots}")

    # Step 3: Query Ogmios for metadata
    print(f"\n=== Step 2: Querying Ogmios for block metadata ===")
    ogmios_meta = asyncio.run(_query_ogmios_metadata(OGMIOS_URL, slots))
    print(f"Got metadata for {len(ogmios_meta)} blocks from Ogmios")

    # Step 4: Write fixture files
    print(f"\n=== Step 3: Writing fixtures ===")
    for rb in raw_blocks:
        slot = rb.get("slot")
        if slot is None:
            continue

        meta = ogmios_meta.get(slot, {})
        era_name = meta.get("era") or rb.get("era_name", "unknown")

        fixture = {
            "slot": slot,
            "hash": meta.get("hash", ""),
            "era": era_name,
            "height": meta.get("height", 0),
            "tx_count": meta.get("tx_count", rb.get("tx_count_decoded", 0)),
            "cbor": rb["cbor"],
        }

        filename = f"{era_name}_{slot}.json"
        filepath = FIXTURE_DIR / filename
        with open(filepath, "w") as f:
            json.dump(fixture, f, indent=2)
            f.write("\n")

        print(f"  {filename} ({len(rb['cbor']) // 2} bytes CBOR)")

    print(f"\nDone! Fixtures saved to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
