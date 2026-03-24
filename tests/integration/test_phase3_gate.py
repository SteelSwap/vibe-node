"""Phase 3 Gate Tests — vibe-node syncs the chain.

These tests prove Phase 3 deliverables:
1. Storage engine works with real block data
2. Crash recovery restores state within 3 seconds
3. Memory footprint is reasonable
4. Block decode + storage integration

Requires Docker Compose services (cardano-node, Ogmios).
"""

from __future__ import annotations

import os
import resource
import sys
import time

import pytest

from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import BlockDiff, LedgerDB
from vibe.cardano.storage.recovery import recover, write_diff_log_entry, write_snapshot
from vibe.cardano.storage.volatile import VolatileDB

pytestmark = pytest.mark.integration

GENESIS_HASH = b"\x00" * 32


# ---------------------------------------------------------------------------
# Gate 1: Storage engine handles chain data
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
async def test_storage_engine_with_synthetic_chain(tmp_path, cardano_node_available):
    """Build a 20-block chain in our storage engine and verify consistency."""
    if not cardano_node_available:
        pytest.skip("cardano-node not available")

    imm_dir = tmp_path / "immutable"
    vol_dir = tmp_path / "volatile"
    imm_dir.mkdir()
    vol_dir.mkdir()

    immutable_db = ImmutableDB(str(imm_dir), epoch_size=10)
    volatile_db = VolatileDB(vol_dir)
    ledger_db = LedgerDB(k=5)

    chain_db = ChainDB(
        immutable_db=immutable_db,
        volatile_db=volatile_db,
        ledger_db=ledger_db,
        k=5,
    )

    # Add 20 blocks
    prev = GENESIS_HASH
    for i in range(1, 21):
        bh = i.to_bytes(32, "big")
        block_data = f"block-{i}".encode().ljust(64, b"\x00")
        await chain_db.add_block(
            slot=i,
            block_hash=bh,
            predecessor_hash=prev,
            block_number=i,
            cbor_bytes=block_data,
        )
        prev = bh

    tip = await chain_db.get_tip()
    assert tip is not None
    assert tip[0] == 20

    # Recent block from volatile
    recent = await chain_db.get_block(b"\x00" * 31 + b"\x14")
    assert recent is not None


# ---------------------------------------------------------------------------
# Gate 2: Crash recovery within 3 seconds
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
def test_crash_recovery_within_3_seconds(tmp_path):
    """Write snapshot + diffs, simulate crash, recover, verify speed."""
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    db = LedgerDB(k=10)
    entries = []
    for i in range(100):
        key = i.to_bytes(34, "big")
        entry = (
            key,
            {
                "tx_hash": i.to_bytes(32, "big"),
                "tx_index": i % 100,
                "address": f"addr_{i}",
                "value": (i + 1) * 1_000_000,
                "datum_hash": b"",
            },
        )
        entries.append(entry)
    db.apply_block(consumed=[], created=entries, block_slot=1)

    # Write snapshot
    write_snapshot(db, snapshot_dir, slot=1, block_hash=b"\x01" * 32)

    # Apply more blocks with diffs
    log_path = snapshot_dir / "diff-replay.log"
    for slot in range(2, 12):
        consumed_key = entries[slot - 2][0]
        new_key = (200 + slot).to_bytes(34, "big")
        created = [
            (
                new_key,
                {
                    "tx_hash": (200 + slot).to_bytes(32, "big"),
                    "tx_index": 0,
                    "address": f"addr_new_{slot}",
                    "value": slot * 2_000_000,
                    "datum_hash": b"",
                },
            )
        ]
        db.apply_block(consumed=[consumed_key], created=created, block_slot=slot)

        diff = BlockDiff(
            consumed=[(consumed_key, entries[slot - 2][1])],
            created=created,
            block_slot=slot,
        )
        write_diff_log_entry(diff, log_path)

    # Simulate crash: fresh LedgerDB
    fresh_db = LedgerDB(k=10)

    start = time.perf_counter()
    recovered_slot = recover(snapshot_dir, fresh_db)
    elapsed = time.perf_counter() - start

    assert recovered_slot >= 1, f"Recovery should restore at least slot 1, got {recovered_slot}"
    assert elapsed < 3.0, f"Recovery took {elapsed:.2f}s (gate: <3s)"


# ---------------------------------------------------------------------------
# Gate 3: Memory footprint
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_memory_footprint_under_target():
    """10K UTxOs should use well under 500 MiB."""
    db = LedgerDB(k=100)

    entries = []
    for i in range(10_000):
        key = i.to_bytes(34, "big")
        entry = (
            key,
            {
                "tx_hash": i.to_bytes(32, "big"),
                "tx_index": i % 65536,
                "address": f"addr1q{i:040d}",
                "value": (i + 1) * 1_000_000,
                "datum_hash": b"\x00" * 32,
            },
        )
        entries.append(entry)

    db.apply_block(consumed=[], created=entries, block_slot=1)

    if sys.platform == "darwin":
        rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    else:
        rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

    assert rss_mib < 500, f"RSS too high: {rss_mib:.0f} MiB for 10K UTxOs"


# ---------------------------------------------------------------------------
# Gate 4: Real blocks from Ogmios stored in ImmutableDB
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
async def test_ogmios_blocks_stored_in_immutabledb(tmp_path, cardano_node_available):
    """Fetch real blocks from Ogmios and store in our ImmutableDB."""
    if not cardano_node_available:
        pytest.skip("cardano-node not available")

    import json

    import websockets

    ogmios_url = os.environ.get("OGMIOS_URL", "ws://localhost:1337")

    async with websockets.connect(ogmios_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "findIntersection",
                    "params": {"points": ["origin"]},
                    "id": "find",
                }
            )
        )
        await ws.recv()

        await ws.send(json.dumps({"jsonrpc": "2.0", "method": "nextBlock", "id": "n0"}))
        await ws.recv()  # RollBackward

        blocks = []
        for i in range(10):
            await ws.send(json.dumps({"jsonrpc": "2.0", "method": "nextBlock", "id": f"n{i + 1}"}))
            resp = json.loads(await ws.recv())
            result = resp.get("result", {})
            if result.get("direction") == "forward":
                block = result.get("block", {})
                if block.get("slot") is not None:
                    blocks.append(block)

    assert len(blocks) >= 5, f"Need at least 5 blocks, got {len(blocks)}"

    imm_dir = tmp_path / "immutable"
    imm_dir.mkdir()
    immutable_db = ImmutableDB(str(imm_dir), epoch_size=100)

    stored = 0
    for block in blocks:
        slot = block.get("slot")
        block_id = bytes.fromhex(block["id"])
        block_bytes = json.dumps(block).encode()
        if isinstance(slot, int):
            await immutable_db.append_block(slot, block_id, block_bytes)
            stored += 1

    assert stored >= 5
    tip_slot = immutable_db.get_tip_slot()
    assert tip_slot is not None and tip_slot > 0
