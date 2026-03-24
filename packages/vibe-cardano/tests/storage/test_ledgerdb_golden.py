"""LedgerDB golden vector tests — snapshot format, Arrow schema, roundtrips.

Haskell parity: the Haskell LedgerDB tests include golden/round-trip tests
for the on-disk snapshot format (BackingStore serialization). We verify
that our Arrow IPC snapshots have the expected structure, schema, metadata,
and that encode/decode/compact operations are lossless.

Haskell reference:
    Ouroboros.Consensus.Storage.LedgerDB.BackingStore (snapshot/restore)
    Test.Ouroboros.Storage.LedgerDB (golden_BackingStoreValueHandle,
                                      prop_readAfterWrite, etc.)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from vibe.cardano.storage.ledger import (
    UTXO_SCHEMA,
    LedgerDB,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_utxo_entry(
    index: int,
) -> tuple[bytes, dict]:
    """Create a deterministic UTxO entry for testing.

    The key is 34 bytes: 32-byte tx_hash + 2-byte big-endian tx_index.
    """
    tx_hash = (index).to_bytes(32, "big")
    tx_index = index % 65536
    key = tx_hash + tx_index.to_bytes(2, "big")
    col_vals = {
        "tx_hash": tx_hash,
        "tx_index": tx_index,
        "address": f"addr_test1qz{index:040d}",
        "value": (index + 1) * 1_000_000,
        "datum_hash": b"",
    }
    return key, col_vals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_golden_snapshot_format() -> None:
    """Snapshot IPC file has expected Arrow IPC structure.

    Verifies that the snapshot file is a valid Arrow IPC file that can
    be opened by pyarrow.ipc.open_file and contains the UTxO data.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))

        # Insert some UTxOs
        entries = [_make_utxo_entry(i) for i in range(5)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        handle = await db.snapshot()
        filepath = handle.metadata["path"]

        # The file must exist and be non-empty
        assert os.path.exists(filepath)
        assert os.path.getsize(filepath) > 0

        # Must be a valid Arrow IPC file
        with pa.OSFile(filepath, "rb") as f:
            reader = ipc.open_file(f)
            table = reader.read_all()

        # Must contain our 5 rows
        assert len(table) == 5

        # Must have the correct column names
        assert table.column_names == [
            "key",
            "tx_hash",
            "tx_index",
            "address",
            "value",
            "datum_hash",
        ]


@pytest.mark.asyncio
async def test_golden_utxo_schema() -> None:
    """Arrow schema matches expected columns and types.

    Golden vector: the UTXO_SCHEMA must have exactly these columns
    with exactly these Arrow types. Any schema change would break
    snapshot compatibility.
    """
    expected_fields = [
        ("key", pa.binary()),
        ("tx_hash", pa.binary()),
        ("tx_index", pa.uint16()),
        ("address", pa.string()),
        ("value", pa.uint64()),
        ("datum_hash", pa.binary()),
    ]

    assert len(UTXO_SCHEMA) == len(expected_fields)

    for i, (name, dtype) in enumerate(expected_fields):
        field = UTXO_SCHEMA.field(i)
        assert field.name == name, f"Field {i}: expected name '{name}', got '{field.name}'"
        assert field.type == dtype, f"Field '{name}': expected type {dtype}, got {field.type}"


@pytest.mark.asyncio
async def test_encode_utxo_roundtrip() -> None:
    """Encode UTxO to Arrow table, snapshot to IPC, restore — roundtrip.

    Verifies that all column values survive the full encode -> snapshot
    -> restore cycle with byte-perfect fidelity.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))

        entries = [_make_utxo_entry(i) for i in range(10)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        # Snapshot
        handle = await db.snapshot()

        # Create a fresh LedgerDB and restore
        db2 = LedgerDB(k=10, snapshot_dir=Path(tmpdir))
        await db2.restore(handle)

        # All UTxOs must be present and identical
        assert db2.utxo_count == 10

        for key, col_vals in entries:
            result = db2.get_utxo(key)
            assert result is not None, f"Key not found after restore: {key!r}"
            assert result["tx_hash"] == col_vals["tx_hash"]
            assert result["tx_index"] == col_vals["tx_index"]
            assert result["address"] == col_vals["address"]
            assert result["value"] == col_vals["value"]
            assert result["datum_hash"] == col_vals["datum_hash"]


@pytest.mark.asyncio
async def test_decode_snapshot_from_bytes() -> None:
    """Load a snapshot from known bytes — verifies the IPC decoder.

    We construct a minimal Arrow IPC file in memory, write it to disk,
    and restore a LedgerDB from it. This tests the decode path
    independently of the encode path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "manual-snapshot.arrow"

        # Build a small table manually
        keys = [b"\x00" * 32 + b"\x00\x00", b"\x01" * 32 + b"\x00\x01"]
        tx_hashes = [b"\x00" * 32, b"\x01" * 32]
        tx_indices = [0, 1]
        addresses = ["addr_test_0", "addr_test_1"]
        values = [2_000_000, 3_000_000]
        datum_hashes = [b"", b"\xab" * 32]

        table = pa.table(
            {
                "key": keys,
                "tx_hash": tx_hashes,
                "tx_index": pa.array(tx_indices, type=pa.uint16()),
                "address": addresses,
                "value": pa.array(values, type=pa.uint64()),
                "datum_hash": datum_hashes,
            },
            schema=UTXO_SCHEMA,
        )

        # Write IPC file
        with pa.OSFile(str(filepath), "wb") as f:
            writer = ipc.new_file(f, UTXO_SCHEMA)
            writer.write_table(table)
            writer.close()

        # Restore into a LedgerDB
        from vibe.core.storage.interfaces import SnapshotHandle

        handle = SnapshotHandle(
            snapshot_id="manual",
            metadata={"path": str(filepath), "utxo_count": "2"},
        )

        db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))
        await db.restore(handle)

        assert db.utxo_count == 2

        # Verify first entry
        r0 = db.get_utxo(keys[0])
        assert r0 is not None
        assert r0["tx_hash"] == b"\x00" * 32
        assert r0["value"] == 2_000_000

        # Verify second entry
        r1 = db.get_utxo(keys[1])
        assert r1 is not None
        assert r1["tx_hash"] == b"\x01" * 32
        assert r1["datum_hash"] == b"\xab" * 32


@pytest.mark.asyncio
async def test_snapshot_metadata_format() -> None:
    """Metadata dict has expected keys after snapshot.

    The SnapshotHandle.metadata must contain 'path', 'utxo_count',
    and 'timestamp' — these are the golden contract for snapshot
    metadata that crash-recovery depends on.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))

        entries = [_make_utxo_entry(i) for i in range(3)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        handle = await db.snapshot()

        # Required metadata keys
        assert "path" in handle.metadata
        assert "utxo_count" in handle.metadata
        assert "timestamp" in handle.metadata

        # Values must be strings (the metadata dict is Dict[str, str])
        assert isinstance(handle.metadata["path"], str)
        assert isinstance(handle.metadata["utxo_count"], str)
        assert isinstance(handle.metadata["timestamp"], str)

        # utxo_count must match
        assert handle.metadata["utxo_count"] == "3"

        # path must point to an existing file
        assert os.path.exists(handle.metadata["path"])

        # timestamp must be a parseable float
        ts = float(handle.metadata["timestamp"])
        assert ts > 0

        # snapshot_id must be set
        assert handle.snapshot_id == "0"  # first snapshot


@pytest.mark.asyncio
async def test_compact_preserves_data() -> None:
    """Compact produces identical query results.

    After applying blocks, consuming UTxOs (creating gaps), and
    compacting, all remaining UTxOs must still be queryable with
    identical column values. This is the Haskell parity test for
    BackingStore compaction/GC.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = LedgerDB(k=10, snapshot_dir=Path(tmpdir))

        # Create 10 UTxOs
        entries = [_make_utxo_entry(i) for i in range(10)]
        db.apply_block(consumed=[], created=entries, block_slot=1)

        assert db.utxo_count == 10

        # Consume 5 of them (indices 0, 2, 4, 6, 8 — the evens)
        consumed_keys = [entries[i][0] for i in range(0, 10, 2)]
        db.apply_block(consumed=consumed_keys, created=[], block_slot=2)

        assert db.utxo_count == 5

        # Record the surviving UTxO values before compaction
        surviving = {}
        for i in range(1, 10, 2):
            key = entries[i][0]
            val = db.get_utxo(key)
            assert val is not None
            surviving[key] = val

        # Compact — should rebuild the table, removing dead rows
        db.compact()

        # Verify the same 5 UTxOs are still present with identical values
        assert db.utxo_count == 5

        for key, expected_vals in surviving.items():
            actual = db.get_utxo(key)
            assert actual is not None, f"UTxO lost after compact: {key!r}"
            assert actual["tx_hash"] == expected_vals["tx_hash"]
            assert actual["tx_index"] == expected_vals["tx_index"]
            assert actual["address"] == expected_vals["address"]
            assert actual["value"] == expected_vals["value"]
            assert actual["datum_hash"] == expected_vals["datum_hash"]

        # Consumed UTxOs must still be absent
        for key in consumed_keys:
            assert db.get_utxo(key) is None
