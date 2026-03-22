"""Crash recovery — Arrow IPC snapshots + diff replay log.

Implements the crash recovery design from the data architecture:

1. **Periodic snapshots** — Every ``SNAPSHOT_INTERVAL`` slots (default 2000),
   the LedgerDB's Arrow table is written to an IPC file with LZ4 compression.
   A metadata sidecar (JSON) records the slot, block hash, and UTxO count.

2. **Diff replay log** — Between snapshots, each block's diff (BlockDiff) is
   appended to a binary replay log. Each entry is fsynced to disk immediately
   so that on crash we lose at most one block application.

3. **Recovery** — On unclean shutdown, load the latest snapshot, then replay
   any diffs from the replay log that are newer than the snapshot's slot.

Target: cold start recovery in ~3 seconds (snapshot load ~2s + diff replay ~1s).

File layout::

    <snapshot_dir>/
        snapshot-<slot>.arrow     — Arrow IPC with LZ4 compression
        snapshot-<slot>.meta      — JSON metadata (slot, hash, utxo_count, timestamp)
        diff-replay.log           — append-only binary diff log
        diff-replay.log.offset    — last-flushed-slot marker for the log

Haskell reference:
    Ouroboros.Consensus.Storage.LedgerDB.Snapshots
    - writeSnapshot, readSnapshot, deleteSnapshot
    The Haskell node takes snapshots every k blocks (or on request).
    We snapshot every SNAPSHOT_INTERVAL slots for predictable recovery time.

    Ouroboros.Consensus.Storage.LedgerDB.DiskPolicy
    - onDiskShouldTakeSnapshot
"""

from __future__ import annotations

import json
import logging
import os
import struct
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc

from vibe.cardano.storage import BlockDiff, LedgerDB
from vibe.cardano.storage.ledger import UTXO_SCHEMA

__all__ = [
    "recover",
    "write_diff_log_entry",
    "write_snapshot",
    "SNAPSHOT_INTERVAL",
]

logger = logging.getLogger(__name__)

# Snapshot every 2000 slots for ~3s recovery target.
SNAPSHOT_INTERVAL = 2000

# Diff log entry header: magic(4) + slot(8) + n_consumed(4) + n_created(4) = 20 bytes
_DIFF_HEADER_FMT = ">4sQII"
_DIFF_HEADER_SIZE = struct.calcsize(_DIFF_HEADER_FMT)
_DIFF_MAGIC = b"VDIF"

# Per-entry formats for consumed/created UTxOs:
#   key_len(4) + key_bytes + json_len(4) + json_bytes
_LEN_FMT = ">I"
_LEN_SIZE = struct.calcsize(_LEN_FMT)


# ---------------------------------------------------------------------------
# Snapshot writing
# ---------------------------------------------------------------------------


def write_snapshot(
    ledger_db: LedgerDB,
    snapshot_dir: Path,
    slot: int | None = None,
    block_hash: bytes | None = None,
) -> Path:
    """Write a LedgerDB snapshot as Arrow IPC with LZ4 compression.

    The snapshot captures the current UTxO table state. A JSON metadata
    sidecar is written alongside it recording the slot, hash, UTxO count,
    and timestamp.

    Args:
        ledger_db: The LedgerDB to snapshot.
        snapshot_dir: Directory to write snapshot files into.
        slot: Current tip slot (for the filename and metadata).
        block_hash: Current tip block hash (for metadata).

    Returns:
        Path to the written ``.arrow`` snapshot file.
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    slot_label = slot if slot is not None else 0
    arrow_path = snapshot_dir / f"snapshot-{slot_label}.arrow"
    meta_path = snapshot_dir / f"snapshot-{slot_label}.meta"

    # Compact the LedgerDB before writing to minimize snapshot size.
    ledger_db.compact()

    # Write Arrow IPC with LZ4 compression.
    options = ipc.IpcWriteOptions(compression="lz4")
    with pa.OSFile(str(arrow_path), "wb") as sink:
        writer = ipc.new_file(sink, ledger_db._table.schema, options=options)
        writer.write_table(ledger_db._table)
        writer.close()

    # Fsync the Arrow file to ensure durability.
    _fsync_file(arrow_path)

    # Write metadata sidecar.
    metadata = {
        "slot": slot_label,
        "block_hash": block_hash.hex() if block_hash else "",
        "utxo_count": ledger_db.utxo_count,
        "timestamp": time.time(),
    }
    meta_path.write_text(json.dumps(metadata, indent=2))
    _fsync_file(meta_path)

    snapshot_size = arrow_path.stat().st_size
    logger.info("Ledger snapshot written at slot %d (%d UTxOs, %d bytes)", slot_label, ledger_db.utxo_count, snapshot_size, extra={"event": "ledger.snapshot.write", "slot": slot_label, "utxo_count": ledger_db.utxo_count, "size_bytes": snapshot_size})

    return arrow_path


# ---------------------------------------------------------------------------
# Diff replay log
# ---------------------------------------------------------------------------


def write_diff_log_entry(diff: BlockDiff, log_path: Path) -> None:
    """Append a single block diff to the replay log, fsynced.

    Each entry is self-describing with a magic header and length-prefixed
    fields so the log can be read sequentially during recovery.

    Binary format per entry:
      - Header: magic(4) + slot(8) + n_consumed(4) + n_created(4)
      - For each consumed: key_len(4) + key + json_len(4) + json_bytes
      - For each created:  key_len(4) + key + json_len(4) + json_bytes

    All writes are fsynced to ensure durability even on power loss.

    Args:
        diff: The BlockDiff to append.
        log_path: Path to the replay log file (created if not exists).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)

    buf = bytearray()

    # Header
    buf.extend(
        struct.pack(
            _DIFF_HEADER_FMT,
            _DIFF_MAGIC,
            diff.block_slot,
            len(diff.consumed),
            len(diff.created),
        )
    )

    # Consumed entries
    for key, col_vals in diff.consumed:
        buf.extend(struct.pack(_LEN_FMT, len(key)))
        buf.extend(key)
        json_bytes = _serialize_col_vals(col_vals)
        buf.extend(struct.pack(_LEN_FMT, len(json_bytes)))
        buf.extend(json_bytes)

    # Created entries
    for key, col_vals in diff.created:
        buf.extend(struct.pack(_LEN_FMT, len(key)))
        buf.extend(key)
        json_bytes = _serialize_col_vals(col_vals)
        buf.extend(struct.pack(_LEN_FMT, len(json_bytes)))
        buf.extend(json_bytes)

    # Append and fsync
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    try:
        os.write(fd, bytes(buf))
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_diff_log(log_path: Path) -> list[BlockDiff]:
    """Read all diff entries from a replay log file.

    Tolerates truncated entries at the end (crash during write) by
    stopping at the first incomplete entry.

    Args:
        log_path: Path to the replay log.

    Returns:
        List of BlockDiff entries in log order.
    """
    if not log_path.exists():
        return []

    data = log_path.read_bytes()
    pos = 0
    diffs: list[BlockDiff] = []

    while pos + _DIFF_HEADER_SIZE <= len(data):
        magic, slot, n_consumed, n_created = struct.unpack_from(
            _DIFF_HEADER_FMT, data, pos
        )
        if magic != _DIFF_MAGIC:
            logger.warning(
                "Diff log: bad magic at offset %d, stopping replay", pos
            )
            break

        pos += _DIFF_HEADER_SIZE

        consumed: list[tuple[bytes, dict[str, Any]]] = []
        created: list[tuple[bytes, dict[str, Any]]] = []

        try:
            for _ in range(n_consumed):
                key, col_vals, pos = _read_entry(data, pos)
                consumed.append((key, col_vals))

            for _ in range(n_created):
                key, col_vals, pos = _read_entry(data, pos)
                created.append((key, col_vals))
        except (struct.error, IndexError, ValueError):
            # Truncated entry — stop here (crash during write).
            logger.warning(
                "Diff log: truncated entry at offset %d for slot %d, "
                "stopping replay (last complete diff was slot %d)",
                pos,
                slot,
                diffs[-1].block_slot if diffs else -1,
            )
            break

        diffs.append(BlockDiff(consumed=consumed, created=created, block_slot=slot))

    return diffs


def _read_entry(
    data: bytes, pos: int
) -> tuple[bytes, dict[str, Any], int]:
    """Read one (key, col_vals) entry from the diff log at the given offset.

    Returns (key, col_vals, new_pos).
    """
    # Key
    (key_len,) = struct.unpack_from(_LEN_FMT, data, pos)
    pos += _LEN_SIZE
    key = data[pos : pos + key_len]
    pos += key_len

    # Column values (JSON)
    (json_len,) = struct.unpack_from(_LEN_FMT, data, pos)
    pos += _LEN_SIZE
    json_bytes = data[pos : pos + json_len]
    pos += json_len

    col_vals = _deserialize_col_vals(json_bytes)

    return key, col_vals, pos


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def recover(
    snapshot_dir: Path,
    ledger_db: LedgerDB,
) -> int:
    """Recover LedgerDB state from the latest snapshot + diff replay.

    Recovery procedure:
    1. Find the latest snapshot-*.arrow file (by slot number in filename)
    2. Load the Arrow IPC table into the LedgerDB
    3. Read the diff replay log
    4. Replay any diffs with slot > snapshot_slot
    5. Truncate the diff log (no longer needed after recovery)

    Args:
        snapshot_dir: Directory containing snapshots and diff log.
        ledger_db: The LedgerDB to restore into.

    Returns:
        The recovered tip slot (from the last replayed diff, or the
        snapshot slot if no diffs needed replay). Returns -1 if no
        snapshot was found.
    """
    if not snapshot_dir.is_dir():
        logger.info("No snapshot directory found at %s", snapshot_dir, extra={"event": "recovery.no_dir", "path": str(snapshot_dir)})
        return -1

    # Find the latest snapshot.
    snapshot_files = sorted(snapshot_dir.glob("snapshot-*.arrow"))
    if not snapshot_files:
        logger.info("No snapshots found in %s", snapshot_dir, extra={"event": "recovery.no_snapshots", "path": str(snapshot_dir)})
        return -1

    latest_snapshot = snapshot_files[-1]
    snapshot_slot = _slot_from_snapshot_path(latest_snapshot)

    logger.info("Loading snapshot at slot %d", snapshot_slot, extra={"event": "recovery.loading", "slot": snapshot_slot, "path": str(latest_snapshot)})

    # Load the Arrow IPC snapshot.
    with pa.OSFile(str(latest_snapshot), "rb") as source:
        reader = ipc.open_file(source)
        table = reader.read_all()

    # Replace the LedgerDB's table and rebuild the index.
    ledger_db._table = table
    ledger_db._index.clear()
    key_col = table.column("key")
    for i in range(len(key_col)):
        key_bytes = key_col[i].as_py()
        ledger_db._index[key_bytes] = i
    ledger_db._diffs.clear()
    ledger_db._free_rows.clear()

    logger.info("Snapshot loaded: %d UTxOs at slot %d", ledger_db.utxo_count, snapshot_slot, extra={"event": "recovery.loaded", "utxo_count": ledger_db.utxo_count, "slot": snapshot_slot})

    # Replay diffs from the log.
    log_path = snapshot_dir / "diff-replay.log"
    diffs = _read_diff_log(log_path)

    replayed = 0
    tip_slot = snapshot_slot

    for diff in diffs:
        if diff.block_slot <= snapshot_slot:
            # This diff is already captured in the snapshot — skip.
            continue

        # Apply the diff: remove consumed, add created.
        consumed_keys = [key for key, _ in diff.consumed]
        ledger_db.apply_block(
            consumed=consumed_keys,
            created=diff.created,
            block_slot=diff.block_slot,
        )
        tip_slot = diff.block_slot
        replayed += 1

    if replayed > 0:
        logger.info("Replayed %d diffs (slot %d -> %d)", replayed, snapshot_slot, tip_slot, extra={"event": "recovery.replayed", "diff_count": replayed, "from_slot": snapshot_slot, "to_slot": tip_slot})

    # Truncate the diff log — we've recovered, so start fresh.
    if log_path.exists():
        log_path.write_bytes(b"")
        _fsync_file(log_path)

    return tip_slot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slot_from_snapshot_path(path: Path) -> int:
    """Extract the slot number from a snapshot filename.

    Expects filenames like ``snapshot-12345.arrow``.
    """
    stem = path.stem  # "snapshot-12345"
    parts = stem.split("-", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def _fsync_file(path: Path) -> None:
    """Fsync a file to ensure durability."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _serialize_col_vals(col_vals: dict[str, Any]) -> bytes:
    """Serialize column values to JSON bytes, handling bytes fields.

    Bytes values are hex-encoded for JSON compatibility.
    """
    serializable = {}
    for k, v in col_vals.items():
        if isinstance(v, bytes):
            serializable[k] = {"__bytes__": v.hex()}
        else:
            serializable[k] = v
    return json.dumps(serializable, separators=(",", ":")).encode("utf-8")


def _deserialize_col_vals(json_bytes: bytes) -> dict[str, Any]:
    """Deserialize column values from JSON bytes.

    Reverses the hex encoding applied by _serialize_col_vals for bytes fields.
    """
    raw = json.loads(json_bytes)
    result: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "__bytes__" in v:
            result[k] = bytes.fromhex(v["__bytes__"])
        else:
            result[k] = v
    return result
