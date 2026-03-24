"""Mithril snapshot import — bootstrap from a Mithril-certified snapshot.

Reads the Haskell cardano-node's ImmutableDB on-disk format (chunk files +
primary/secondary indexes) and populates our own ImmutableDB and LedgerDB.

The Mithril snapshot contains:
  - ``immutable/`` — Haskell ImmutableDB chunk/index files
  - ``volatile/`` — VolatileDB (ignored during import)
  - ``ledger/`` — Serialized ledger state snapshots

Haskell ImmutableDB on-disk format (ouroboros-consensus):
  - Chunk files: ``NNNNN.chunk`` — concatenated raw CBOR blocks
  - Primary index: ``NNNNN.primary`` — array of uint32 offsets (4 bytes each)
    with (slot_count + 2) entries. Entry 0 is always 0 (file start). Each
    subsequent entry is the byte offset of the next block boundary. Repeated
    offsets indicate empty (no-block) slots. The Haskell secondary index
    entry size is prepended as a uint16 at offset 0 of the file.
  - Secondary index: ``NNNNN.secondary`` — per-block entries with hash,
    offset, block-or-EBB flag, etc.

The secondary index entry format (from Haskell source):
  - 32 bytes: block hash
  - 8 bytes: block offset (uint64 BE) — relative to chunk start, but in
    practice the secondary entries are used mainly for hash lookup. We parse
    chunks sequentially using the primary index offsets instead.

We parse chunk files using the primary index to locate block boundaries,
then decode each block's header to extract slot and hash. This avoids
depending on the secondary index format which varies across node versions.

Spec references:
  Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
  Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Secondary
  Ouroboros.Consensus.Storage.ImmutableDB.Impl.Types (ChunkNo)
"""

from __future__ import annotations

import hashlib
import logging
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import cbor2pure as cbor2
import pyarrow as pa

from vibe.cardano.storage import ImmutableDB, LedgerDB
from vibe.cardano.storage.ledger import UTXO_SCHEMA

__all__ = [
    "import_mithril_snapshot",
    "parse_immutable_chunks",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Haskell ImmutableDB primary index parsing
# ---------------------------------------------------------------------------

# The Haskell primary index file starts with a 2-byte uint16 header
# indicating the secondary index entry size, followed by an array of
# 4-byte uint32 offsets (one per relative slot + 1 sentinel).
_HASKELL_PRIMARY_HEADER_SIZE = 2
_HASKELL_PRIMARY_ENTRY_SIZE = 4
_HASKELL_PRIMARY_ENTRY_FMT = ">I"


def _read_haskell_primary_index(primary_path: Path) -> list[int]:
    """Read block boundary offsets from a Haskell primary index file.

    The primary index is an array of uint32 big-endian offsets. Consecutive
    equal offsets mean an empty slot (no block). Consecutive different offsets
    define a block: start = offsets[i], end = offsets[i+1].

    Returns:
        List of byte offsets into the chunk file.
    """
    data = primary_path.read_bytes()
    if len(data) < _HASKELL_PRIMARY_HEADER_SIZE:
        return []

    # Skip the 2-byte secondary-entry-size header.
    payload = data[_HASKELL_PRIMARY_HEADER_SIZE:]
    count = len(payload) // _HASKELL_PRIMARY_ENTRY_SIZE
    if count == 0:
        return []

    offsets: list[int] = []
    for i in range(count):
        start = i * _HASKELL_PRIMARY_ENTRY_SIZE
        (val,) = struct.unpack_from(_HASKELL_PRIMARY_ENTRY_FMT, payload, start)
        offsets.append(val)
    return offsets


def _extract_blocks_from_chunk(
    chunk_data: bytes,
    offsets: list[int],
) -> Iterator[tuple[int, int]]:
    """Yield (start_offset, end_offset) for each block in a chunk.

    Walks the primary index offsets: whenever offsets[i+1] > offsets[i],
    there is a block from offsets[i] to offsets[i+1].
    """
    for i in range(len(offsets) - 1):
        start = offsets[i]
        end = offsets[i + 1]
        if end > start and end <= len(chunk_data):
            yield start, end


# ---------------------------------------------------------------------------
# Block header extraction (lightweight — just slot + hash)
# ---------------------------------------------------------------------------


def _strip_cbor_tag(data: bytes) -> tuple[int, bytes]:
    """Strip a CBOR tag prefix, return (tag_number, payload_bytes).

    CBOR major type 6 encoding:
      0xC0..0xD7: tag 0..23 in 1 byte
      0xD8 XX:    tag 24..255 in 2 bytes
    """
    if not data:
        raise ValueError("Empty CBOR bytes")

    initial = data[0]
    major_type = initial >> 5
    additional = initial & 0x1F

    if major_type != 6:
        # No tag — return tag -1 to signal untagged data.
        return -1, data

    if additional <= 23:
        return additional, data[1:]
    elif additional == 24:
        if len(data) < 2:
            raise ValueError("Truncated CBOR tag")
        return data[1], data[2:]
    else:
        raise ValueError(f"Unexpected additional info {additional} for tag")


def _extract_slot_and_hash(cbor_bytes: bytes) -> tuple[int, bytes]:
    """Extract (slot, block_hash) from a raw CBOR block.

    Handles both tagged (era-wrapped) and untagged blocks.

    For Shelley+ blocks: block = [header, ...], header = [header_body, sig]
    header_body[1] = slot.
    Block hash = Blake2b-256 of the CBOR-encoded header.

    For Byron blocks (tags 0, 1): uses a simplified extraction from the
    Byron block structure.

    Returns:
        (slot_number, 32-byte block hash)

    Raises:
        ValueError: If the block structure cannot be parsed.
    """
    tag, payload = _strip_cbor_tag(cbor_bytes)

    block = cbor2.loads(payload)

    if tag in (0, 1):
        # Byron main block (tag 0): [[header, body, extra], ...]
        # Byron EBB (tag 1): [[header, body, extra], ...]
        # Byron header contains [protocol_magic, prev_hash, body_proof, consensus_data, extra_data]
        # consensus_data for main blocks: [slot_id, pub_key, difficulty, signature]
        # slot_id: [epoch, slot_within_epoch]
        # For EBBs the slot is conventionally the first slot of the epoch.
        try:
            if tag == 0:
                # Main Byron block
                header = block[0]
                consensus_data = header[3]
                slot_id = consensus_data[0]
                # Byron slot encoding: [epoch, slot_in_epoch]
                # We approximate absolute slot as epoch * 21600 + slot_in_epoch
                # (Byron had 21600 slots per epoch on mainnet)
                epoch = slot_id[0]
                slot_in_epoch = slot_id[1]
                slot = epoch * 21600 + slot_in_epoch
            else:
                # Byron EBB — epoch boundary block, slot = first slot of epoch
                header = block[0]
                # EBB header: [protocol_magic, prev_hash, body_proof, consensus_data, extra_data]
                # consensus_data for EBB is just the epoch number
                epoch = header[3]
                slot = epoch * 21600
        except (IndexError, TypeError, KeyError) as exc:
            raise ValueError(f"Failed to parse Byron block header: {exc}") from exc

        # Byron block hash = Blake2b-256 of the CBOR-encoded header
        header_cbor = cbor2.dumps(block[0])
        block_hash = hashlib.blake2b(header_cbor, digest_size=32).digest()
        return slot, block_hash

    # Shelley+ block: [header, tx_bodies, tx_witnesses, auxiliary]
    if not isinstance(block, list) or len(block) < 4:
        raise ValueError(
            f"Expected Shelley+ block array of >= 4 elements, got {type(block).__name__}"
        )

    header = block[0]
    if not isinstance(header, list) or len(header) < 2:
        raise ValueError("Expected header as 2-element array")

    header_body = header[0]
    if not isinstance(header_body, list) or len(header_body) < 2:
        raise ValueError("Expected header_body as array with slot at index 1")

    slot = header_body[1]

    # Block hash = Blake2b-256 of the CBOR-serialized header
    header_cbor = cbor2.dumps(header)
    block_hash = hashlib.blake2b(header_cbor, digest_size=32).digest()

    return slot, block_hash


# ---------------------------------------------------------------------------
# Chunk file iteration
# ---------------------------------------------------------------------------


def parse_immutable_chunks(
    chunk_dir: Path,
) -> Iterator[tuple[int, bytes, bytes]]:
    """Parse Haskell ImmutableDB chunk files, yielding blocks.

    Scans the chunk directory for ``NNNNN.chunk`` files with matching
    ``NNNNN.primary`` index files. Uses the primary index to locate block
    boundaries within each chunk, then decodes each block's header to
    extract the slot number and block hash.

    Yields:
        ``(slot, block_hash, cbor_bytes)`` tuples in chunk order.

    Args:
        chunk_dir: Directory containing ``.chunk`` and ``.primary`` files.
            This is typically ``<snapshot>/immutable/`` from a Mithril snapshot.

    Raises:
        FileNotFoundError: If chunk_dir does not exist.
    """
    if not chunk_dir.is_dir():
        raise FileNotFoundError(f"Chunk directory not found: {chunk_dir}")

    # Find all chunk files, sorted by chunk number.
    chunk_files = sorted(chunk_dir.glob("*.chunk"))
    if not chunk_files:
        logger.warning("No .chunk files found in %s", chunk_dir)
        return

    for chunk_path in chunk_files:
        chunk_stem = chunk_path.stem  # e.g., "00000"
        primary_path = chunk_path.with_suffix(".primary")

        if not primary_path.exists():
            logger.warning("No primary index for chunk %s, skipping", chunk_stem)
            continue

        # Read the primary index to get block boundary offsets.
        offsets = _read_haskell_primary_index(primary_path)
        if len(offsets) < 2:
            logger.debug("Chunk %s: primary index too short, skipping", chunk_stem)
            continue

        # Read the chunk data.
        chunk_data = chunk_path.read_bytes()
        if not chunk_data:
            continue

        block_count = 0
        for start, end in _extract_blocks_from_chunk(chunk_data, offsets):
            cbor_bytes = chunk_data[start:end]
            try:
                slot, block_hash = _extract_slot_and_hash(cbor_bytes)
            except (ValueError, Exception) as exc:
                logger.warning(
                    "Chunk %s offset %d: failed to parse block header: %s",
                    chunk_stem,
                    start,
                    exc,
                )
                continue

            block_count += 1
            yield slot, block_hash, cbor_bytes

        logger.debug("Chunk %s: parsed %d blocks", chunk_stem, block_count)


# ---------------------------------------------------------------------------
# Ledger state import
# ---------------------------------------------------------------------------


def _decode_ledger_snapshot(
    ledger_dir: Path,
) -> pa.Table | None:
    """Attempt to decode a ledger state snapshot into a UTxO Arrow table.

    Mithril ledger snapshots contain a CBOR-encoded ledger state. The UTxO
    set is extracted and converted to our Arrow schema.

    This is a best-effort decoder — the Haskell ledger state serialization
    is complex and version-dependent. If we cannot decode it, we return None
    and the caller should fall back to replaying blocks.

    Args:
        ledger_dir: Directory containing ledger snapshot files.

    Returns:
        Arrow table with UTXO_SCHEMA, or None if decoding fails.
    """
    # Look for the ledger state file. The Haskell node names these
    # with the slot number, e.g., ``<slot>`` or ``<slot>_<hash>``.
    snapshot_files = sorted(ledger_dir.glob("*"))
    if not snapshot_files:
        logger.info(
            "No ledger snapshot files found in %s",
            ledger_dir,
            extra={"event": "mithril.ledger.empty", "path": str(ledger_dir)},
        )
        return None

    # Take the most recent (largest filename = highest slot).
    snapshot_file = snapshot_files[-1]
    logger.info(
        "Decoding ledger snapshot from %s",
        snapshot_file,
        extra={"event": "mithril.ledger.decode", "path": str(snapshot_file)},
    )

    try:
        raw = snapshot_file.read_bytes()
        # The Haskell ledger state is deeply nested CBOR. The UTxO set
        # is buried several layers deep. We attempt a shallow decode to
        # extract what we can.
        state = cbor2.loads(raw)
        return _utxo_table_from_ledger_state(state)
    except Exception as exc:
        logger.warning(
            "Could not decode ledger snapshot %s: %s — "
            "will fall back to block replay for UTxO set",
            snapshot_file,
            exc,
        )
        return None


def _utxo_table_from_ledger_state(state: Any) -> pa.Table | None:
    """Extract UTxO entries from a decoded Haskell ledger state.

    The Haskell NewEpochState serialization (simplified):
      [nesEL, nesBprev, nesBcur, nesEs, nesRu, nesPd, stashAvvm]
    where nesEs (EpochState) contains the UTxOState deep inside.

    This is inherently fragile — the exact nesting depends on the era
    and serialization version. We try common patterns and bail if none match.

    Returns:
        Arrow table, or None if extraction fails.
    """
    keys: list[bytes] = []
    tx_hashes: list[bytes] = []
    tx_indices: list[int] = []
    addresses: list[str] = []
    values: list[int] = []
    datum_hashes: list[bytes] = []

    utxo_map = _find_utxo_map(state)
    if utxo_map is None:
        return None

    for txin, txout in utxo_map.items():
        try:
            if isinstance(txin, (list, tuple)) and len(txin) >= 2:
                tx_hash = txin[0] if isinstance(txin[0], bytes) else b""
                tx_idx = int(txin[1])
            elif isinstance(txin, bytes) and len(txin) >= 34:
                tx_hash = txin[:32]
                tx_idx = int.from_bytes(txin[32:34], "big")
            else:
                continue

            # Build the 34-byte key
            key = tx_hash[:32].ljust(32, b"\x00") + tx_idx.to_bytes(2, "big")

            # Extract address and value from TxOut
            addr = ""
            val = 0
            dhash = b""

            if isinstance(txout, (list, tuple)):
                if len(txout) >= 2:
                    addr_raw = txout[0]
                    addr = addr_raw.hex() if isinstance(addr_raw, bytes) else str(addr_raw)
                    val_raw = txout[1]
                    if isinstance(val_raw, int):
                        val = val_raw
                    elif isinstance(val_raw, (list, tuple)) and len(val_raw) >= 1:
                        val = int(val_raw[0]) if isinstance(val_raw[0], int) else 0
                if len(txout) >= 3 and isinstance(txout[2], bytes):
                    dhash = txout[2]
            elif isinstance(txout, dict):
                addr = str(txout.get(0, ""))
                val_entry = txout.get(1, 0)
                val = val_entry if isinstance(val_entry, int) else 0
                dhash = txout.get(2, b"")
                if not isinstance(dhash, bytes):
                    dhash = b""

            keys.append(key)
            tx_hashes.append(tx_hash[:32].ljust(32, b"\x00"))
            tx_indices.append(tx_idx)
            addresses.append(addr)
            values.append(val)
            datum_hashes.append(dhash)

        except ValueError, TypeError, IndexError:
            continue

    if not keys:
        return None

    return pa.table(
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


def _find_utxo_map(obj: Any, depth: int = 0, max_depth: int = 10) -> dict | None:
    """Recursively search a decoded CBOR structure for a UTxO-like map.

    A UTxO map is a dict where keys are either:
      - (bytes, int) tuples (TxIn)
      - bytes of length >= 34 (serialized TxIn)

    Returns the first matching dict found, or None.
    """
    if depth > max_depth:
        return None

    if isinstance(obj, dict) and len(obj) > 0:
        # Check if this looks like a UTxO map.
        sample_key = next(iter(obj))
        if isinstance(sample_key, (list, tuple)) and len(sample_key) >= 2:
            if isinstance(sample_key[0], bytes):
                return obj
        if isinstance(sample_key, bytes) and len(sample_key) >= 34:
            return obj

        # Recurse into values.
        for v in obj.values():
            result = _find_utxo_map(v, depth + 1, max_depth)
            if result is not None:
                return result

    if isinstance(obj, (list, tuple)):
        for item in obj:
            result = _find_utxo_map(item, depth + 1, max_depth)
            if result is not None:
                return result

    return None


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------


async def import_mithril_snapshot(
    snapshot_dir: Path,
    immutable_db: ImmutableDB,
    ledger_db: LedgerDB,
) -> tuple[int, bytes]:
    """Import a Mithril snapshot into our storage layer.

    This is the primary entry point for bootstrapping from a Mithril
    snapshot. It:

    1. Parses all chunk files from the snapshot's immutable/ directory
    2. Writes each block to our ImmutableDB
    3. Attempts to decode the ledger state snapshot for the UTxO set
    4. If ledger decode fails, the UTxO set must be built by replaying
       blocks (not handled here — that's the chain-sync module's job)

    The Docker Compose Mithril service downloads snapshots to /data/,
    which contains the standard Haskell node directory layout:
      /data/immutable/  — chunk files
      /data/ledger/     — ledger state
      /data/volatile/   — volatile DB (ignored)

    Args:
        snapshot_dir: Root of the snapshot (contains immutable/, ledger/, etc.)
        immutable_db: Our ImmutableDB to populate.
        ledger_db: Our LedgerDB to populate with the UTxO set.

    Returns:
        ``(tip_slot, tip_hash)`` — the slot and hash of the last imported block.

    Raises:
        FileNotFoundError: If snapshot_dir or required subdirectories don't exist.
        ValueError: If no blocks could be imported.
    """
    if not snapshot_dir.is_dir():
        raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")

    immutable_dir = snapshot_dir / "immutable"
    ledger_dir = snapshot_dir / "ledger"

    if not immutable_dir.is_dir():
        raise FileNotFoundError(f"Immutable directory not found: {immutable_dir}")

    # Phase 1: Import blocks from chunk files into our ImmutableDB.
    tip_slot: int | None = None
    tip_hash: bytes | None = None
    block_count = 0
    skipped = 0

    logger.info(
        "Importing blocks from %s",
        immutable_dir,
        extra={"event": "mithril.blocks.start", "path": str(immutable_dir)},
    )

    for slot, block_hash, cbor_bytes in parse_immutable_chunks(immutable_dir):
        # Skip blocks that are already in our DB (idempotent import).
        current_tip = immutable_db.get_tip_slot()
        if current_tip is not None and slot <= current_tip:
            skipped += 1
            continue

        try:
            await immutable_db.append_block(slot, block_hash, cbor_bytes)
        except Exception as exc:
            logger.warning("Failed to append block at slot %d: %s", slot, exc)
            continue

        tip_slot = slot
        tip_hash = block_hash
        block_count += 1

        if block_count % 10_000 == 0:
            logger.info(
                "Imported %d blocks (tip slot %d)",
                block_count,
                slot,
                extra={
                    "event": "mithril.blocks.progress",
                    "block_count": block_count,
                    "slot": slot,
                },
            )

    if tip_slot is None or tip_hash is None:
        raise ValueError(
            f"No blocks imported from {immutable_dir} (skipped {skipped} already-imported blocks)"
        )

    logger.info(
        "Import complete: %d blocks (skipped %d), tip at slot %d",
        block_count,
        skipped,
        tip_slot,
        extra={
            "event": "mithril.blocks.done",
            "block_count": block_count,
            "skipped": skipped,
            "tip_slot": tip_slot,
            "tip_hash": tip_hash.hex()[:16],
        },
    )

    # Phase 2: Try to import the ledger state.
    if ledger_dir.is_dir():
        utxo_table = _decode_ledger_snapshot(ledger_dir)
        if utxo_table is not None and len(utxo_table) > 0:
            # Populate the LedgerDB with the decoded UTxO set.
            entries: list[tuple[bytes, dict[str, Any]]] = []
            for i in range(len(utxo_table)):
                row = {col: utxo_table.column(col)[i].as_py() for col in UTXO_SCHEMA.names}
                key = row["key"]
                entries.append((key, row))

            ledger_db._bulk_insert(entries)
            logger.info(
                "Loaded %d UTxOs from ledger snapshot",
                len(entries),
                extra={"event": "mithril.utxo.loaded", "utxo_count": len(entries)},
            )
        else:
            logger.info(
                "Could not decode ledger snapshot — UTxO set must be built by replaying blocks",
                extra={"event": "mithril.utxo.decode_failed"},
            )
    else:
        logger.info(
            "No ledger directory in snapshot — skipping UTxO import",
            extra={"event": "mithril.utxo.skip"},
        )

    return tip_slot, tip_hash
