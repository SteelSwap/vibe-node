"""LedgerDB — Arrow-backed UTxO state store with dict index and diff layer.

This is the performance-critical component of the Cardano node's storage
subsystem. It maintains the UTxO set using:

1. **Arrow UTxO table** — PyArrow Table for columnar data storage.
   Columns: key (binary), tx_hash (binary), tx_index (uint16),
   address (string), value (uint64), datum_hash (binary).

2. **Dict index** — ``dict[bytes, int]`` mapping TxIn (34-byte key)
   to row index in the Arrow table. O(1) lookup at ~0.23us.

3. **Diff layer** — ``collections.deque[BlockDiff]`` with maxlen=k
   (security parameter, default 2160). Each diff records consumed
   and created UTxOs for rollback support.

Performance targets (from data-architecture.md benchmarks, 86x faster
than LMDB):
    - Lookup: 0.23 us/op
    - Block apply (300 mutations): 0.37 ms
    - Rollback 2160 blocks: ~0.8 s

Implements :class:`~vibe.core.storage.interfaces.StateStore` from
``vibe.core``.

Haskell reference:
    Ouroboros.Consensus.Storage.LedgerDB.API
    Ouroboros.Consensus.Storage.LedgerDB.BackingStore
    The Haskell LedgerDB maintains a windowed sequence of ledger states
    with the security parameter k bounding how far back rollbacks can go.
    Our implementation stores the UTxO set directly (not full ledger
    states) with a diff layer for rollback, which is more memory-efficient
    for the UTxO-focused operations we need.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as ipc

from vibe.core.storage.interfaces import SnapshotHandle

__all__ = [
    "BlockDiff",
    "ExceededRollbackError",
    "LedgerDB",
    "UTXO_SCHEMA",
]

# ---------------------------------------------------------------------------
# Arrow schema for the UTxO table
# ---------------------------------------------------------------------------

UTXO_SCHEMA = pa.schema(
    [
        pa.field("key", pa.binary()),  # 34-byte TxIn: tx_hash(32) + tx_index(2)
        pa.field("tx_hash", pa.binary()),  # 32-byte transaction hash
        pa.field("tx_index", pa.uint16()),  # Output index within the transaction
        pa.field("address", pa.string()),  # Bech32 or hex address
        pa.field("value", pa.uint64()),  # Lovelace value
        pa.field("datum_hash", pa.binary()),  # Optional datum hash (empty bytes if none)
    ]
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlockDiff:
    """Records the UTxO mutations from a single block application.

    Consumed entries store the full row data so rollback can restore them.
    Created entries store the full row data so rollback can remove them.

    Attributes:
        consumed: UTxOs spent — ``(key, column_values)`` pairs for undo.
        created: UTxOs produced — ``(key, column_values)`` pairs.
        block_slot: Optional slot number for debugging/ordering.
    """

    consumed: list[tuple[bytes, dict[str, Any]]]
    created: list[tuple[bytes, dict[str, Any]]]
    block_slot: int = 0


class ExceededRollbackError(Exception):
    """Raised when a rollback exceeds the maximum allowed depth.

    Mirrors the Haskell ``ExceededRollback`` error from
    ``Ouroboros.Consensus.Storage.LedgerDB.API``.

    Attributes:
        rollback_maximum: The maximum number of blocks that can be rolled back.
        rollback_requested: The number of blocks the caller tried to roll back.
    """

    def __init__(self, rollback_maximum: int, rollback_requested: int) -> None:
        self.rollback_maximum = rollback_maximum
        self.rollback_requested = rollback_requested
        super().__init__(
            f"Exceeded rollback: requested={rollback_requested}, maximum={rollback_maximum}"
        )


# ---------------------------------------------------------------------------
# LedgerDB
# ---------------------------------------------------------------------------


class LedgerDB:
    """Arrow-backed UTxO state store with dict index and diff-based rollback.

    This implements the :class:`~vibe.core.storage.interfaces.StateStore`
    protocol using PyArrow tables for columnar data and a Python dict for
    O(1) point lookups.

    Args:
        k: Security parameter — maximum rollback depth. Defaults to 2160
           (Cardano mainnet value).
        snapshot_dir: Directory for Arrow IPC snapshot files. Defaults to
           a temp directory if not specified.
    """

    def __init__(self, k: int = 2160, snapshot_dir: Path | None = None) -> None:
        self._k = k
        self._snapshot_dir = snapshot_dir or Path("/tmp/vibe-ledgerdb-snapshots")

        # The Arrow table holding all live UTxOs.
        self._table: pa.Table = pa.table(
            {name: [] for name in UTXO_SCHEMA.names},
            schema=UTXO_SCHEMA,
        )

        # Dict index: TxIn key (bytes) -> row index in _table.
        self._index: dict[bytes, int] = {}

        # Diff layer for rollback support, bounded at k.
        self._diffs: deque[BlockDiff] = deque(maxlen=k)

        # Monotonic snapshot counter.
        self._next_snapshot_id: int = 0

        # Free list of row indices (from deletions) for reuse.
        self._free_rows: list[int] = []

    # -- Properties ----------------------------------------------------------

    @property
    def k(self) -> int:
        """The security parameter (max rollback depth)."""
        return self._k

    @property
    def max_rollback(self) -> int:
        """Current maximum rollback depth (number of diffs stored)."""
        return len(self._diffs)

    @property
    def utxo_count(self) -> int:
        """Number of live UTxOs in the set."""
        return len(self._index)

    # -- Point lookup --------------------------------------------------------

    async def get(self, key: bytes) -> bytes | None:
        """Look up a UTxO by its TxIn key.

        Returns the key bytes if found (for StateStore protocol compliance),
        or None if not in the UTxO set.
        """
        if key not in self._index:
            return None
        return key

    def get_utxo(self, txin: bytes) -> dict[str, Any] | None:
        """Look up a UTxO by TxIn key, returning column values as a dict.

        This is the primary lookup method — synchronous for maximum
        performance. Returns a dict with column names as keys, or None
        if the TxIn is not in the UTxO set.

        Args:
            txin: The 34-byte TxIn key (tx_hash + tx_index).

        Returns:
            Dict of column values, or None if not found.
        """
        row_idx = self._index.get(txin)
        if row_idx is None:
            return None
        return self._read_row(row_idx)

    def _read_row(self, row_idx: int) -> dict[str, Any]:
        """Read a single row from the Arrow table as a dict."""
        row = {}
        for col_name in UTXO_SCHEMA.names:
            col = self._table.column(col_name)
            value = col[row_idx].as_py()
            row[col_name] = value
        return row

    # -- Block application ---------------------------------------------------

    def apply_block(
        self,
        consumed: list[bytes],
        created: list[tuple[bytes, dict[str, Any]]],
        block_slot: int = 0,
    ) -> None:
        """Apply a block's UTxO mutations: delete consumed, add created.

        This is synchronous for performance. The diff is recorded for
        rollback support.

        Args:
            consumed: List of TxIn keys to remove from the UTxO set.
            created: List of ``(key, column_values)`` for new UTxOs.
                Column values must include: tx_hash, tx_index, address,
                value, datum_hash.
            block_slot: Optional slot number for the diff record.
        """
        # Save consumed UTxOs for rollback.
        consumed_with_data: list[tuple[bytes, dict[str, Any]]] = []
        for key in consumed:
            row_data = self.get_utxo(key)
            if row_data is not None:
                consumed_with_data.append((key, row_data))

        # Delete consumed UTxOs.
        rows_to_free = []
        for key in consumed:
            row_idx = self._index.pop(key, None)
            if row_idx is not None:
                rows_to_free.append(row_idx)

        self._free_rows.extend(rows_to_free)

        # Add created UTxOs.
        created_with_data: list[tuple[bytes, dict[str, Any]]] = []
        if created:
            self._bulk_insert(created)
            for key, col_vals in created:
                created_with_data.append((key, col_vals))

        # Push diff.
        diff = BlockDiff(
            consumed=consumed_with_data,
            created=created_with_data,
            block_slot=block_slot,
        )
        self._diffs.append(diff)

    def _bulk_insert(self, entries: list[tuple[bytes, dict[str, Any]]]) -> None:
        """Insert multiple UTxO entries into the Arrow table and dict index.

        Builds a new table from the entries and concatenates with the
        existing table. Updates the dict index with new row positions.
        """
        # Build column arrays for the new entries.
        keys = []
        tx_hashes = []
        tx_indices = []
        addresses = []
        values = []
        datum_hashes = []

        for key, cols in entries:
            keys.append(key)
            tx_hashes.append(cols.get("tx_hash", b""))
            tx_indices.append(cols.get("tx_index", 0))
            addresses.append(cols.get("address", ""))
            values.append(cols.get("value", 0))
            datum_hashes.append(cols.get("datum_hash", b""))

        new_table = pa.table(
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

        # Track the starting row index for the new entries.
        start_idx = len(self._table)

        # Concatenate.
        self._table = pa.concat_tables([self._table, new_table])

        # Update index.
        for i, (key, _) in enumerate(entries):
            self._index[key] = start_idx + i

    # -- Rollback ------------------------------------------------------------

    def rollback(self, n: int) -> None:
        """Roll back the last N blocks by reversing their diffs.

        Args:
            n: Number of blocks to roll back.

        Raises:
            ExceededRollbackError: If n exceeds the number of stored diffs.
        """
        if n > len(self._diffs):
            raise ExceededRollbackError(
                rollback_maximum=len(self._diffs),
                rollback_requested=n,
            )

        for _ in range(n):
            diff = self._diffs.pop()

            # Remove created UTxOs.
            for key, _ in diff.created:
                row_idx = self._index.pop(key, None)
                if row_idx is not None:
                    self._free_rows.append(row_idx)

            # Restore consumed UTxOs.
            if diff.consumed:
                entries = [(key, col_vals) for key, col_vals in diff.consumed]
                self._bulk_insert(entries)

    # -- Past ledger state lookup --------------------------------------------

    def get_past_ledger(self, blocks_back: int) -> LedgerDB | None:
        """Look up a past ledger state by rolling back N blocks.

        Returns a *copy* of this LedgerDB with the last ``blocks_back``
        diffs reversed, or ``None`` if ``blocks_back`` exceeds the stored
        diff count.

        This is a read-only operation — it does not modify the current
        LedgerDB state.

        Haskell reference:
            Ouroboros.Consensus.Storage.LedgerDB.API.getPastLedgerAt
            Uses the windowed sequence of ledger states to look up
            historical points within the last k blocks.

        Args:
            blocks_back: How many blocks back to look (0 = current state).

        Returns:
            A new LedgerDB representing the past state, or None if the
            requested point is beyond the stored history.
        """
        if blocks_back > len(self._diffs):
            return None

        if blocks_back == 0:
            # Return a shallow copy at the current state
            past = LedgerDB(k=self._k)
            past._table = self._table
            past._index = dict(self._index)
            past._diffs = deque(self._diffs, maxlen=self._k)
            past._free_rows = list(self._free_rows)
            return past

        # Create a copy and roll it back
        past = LedgerDB(k=self._k)
        past._table = self._table
        past._index = dict(self._index)
        past._diffs = deque(self._diffs, maxlen=self._k)
        past._free_rows = list(self._free_rows)
        past.rollback(blocks_back)
        return past

    # -- Compaction ----------------------------------------------------------

    def compact(self) -> None:
        """Rebuild the Arrow table, removing dead rows.

        Over time, deletions leave gaps in the table (tracked in
        _free_rows). Compaction rebuilds the table with only live rows
        and resets the index.

        Call this periodically (e.g., every N blocks) to reclaim memory.
        """
        if not self._index:
            self._table = pa.table(
                {name: [] for name in UTXO_SCHEMA.names},
                schema=UTXO_SCHEMA,
            )
            self._index.clear()
            self._free_rows.clear()
            return

        # Collect live row indices, sorted.
        live_indices = sorted(self._index.values())

        # Take only live rows.
        self._table = self._table.take(live_indices)

        # Rebuild the index.
        old_to_new = {old: new for new, old in enumerate(live_indices)}
        self._index = {key: old_to_new[old_idx] for key, old_idx in self._index.items()}
        self._free_rows.clear()

    # -- StateStore protocol: batch operations --------------------------------

    async def batch_put(self, items: list[tuple[bytes, bytes]]) -> None:
        """Atomically write a batch of key-value pairs.

        For StateStore protocol compliance. Keys are TxIn bytes, values
        are CBOR-encoded UTxO data. This is a simplified interface — for
        full column data, use :meth:`apply_block`.
        """
        entries = []
        for key, value in items:
            # Minimal column values from raw bytes.
            col_vals = {
                "tx_hash": key[:32] if len(key) >= 32 else key,
                "tx_index": int.from_bytes(key[32:34], "big") if len(key) >= 34 else 0,
                "address": "",
                "value": 0,
                "datum_hash": b"",
            }
            entries.append((key, col_vals))
        self._bulk_insert(entries)

    async def batch_delete(self, keys: list[bytes]) -> None:
        """Atomically delete a batch of keys.

        For StateStore protocol compliance.
        """
        for key in keys:
            row_idx = self._index.pop(key, None)
            if row_idx is not None:
                self._free_rows.append(row_idx)

    # -- Snapshot / restore ---------------------------------------------------

    async def snapshot(self) -> SnapshotHandle:
        """Write the current Arrow table to an IPC file.

        Returns a SnapshotHandle with the file path and metadata.
        """
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)

        sid = str(self._next_snapshot_id)
        self._next_snapshot_id += 1

        filename = f"ledgerdb-snapshot-{sid}.arrow"
        filepath = self._snapshot_dir / filename

        # Compact before snapshot to minimize file size.
        self.compact()

        # Write Arrow IPC file.
        with pa.OSFile(str(filepath), "wb") as f:
            writer = ipc.new_file(f, self._table.schema)
            writer.write_table(self._table)
            writer.close()

        return SnapshotHandle(
            snapshot_id=sid,
            metadata={
                "path": str(filepath),
                "utxo_count": str(self.utxo_count),
                "timestamp": str(time.time()),
            },
        )

    async def restore(self, handle: SnapshotHandle) -> None:
        """Restore state from an Arrow IPC snapshot file.

        Loads the table, rebuilds the dict index, and clears the diff layer.

        Args:
            handle: The handle from a prior :meth:`snapshot` call.

        Raises:
            KeyError: If the snapshot file does not exist.
        """
        filepath = handle.metadata.get("path")
        if filepath is None:
            msg = f"Snapshot handle missing 'path' metadata: {handle!r}"
            raise KeyError(msg)

        if not os.path.exists(filepath):
            msg = f"Snapshot file not found: {filepath}"
            raise KeyError(msg)

        # Read Arrow IPC file.
        with pa.OSFile(filepath, "rb") as f:
            reader = ipc.open_file(f)
            self._table = reader.read_all()

        # Rebuild dict index from the key column.
        self._index.clear()
        key_col = self._table.column("key")
        for i in range(len(key_col)):
            key_bytes = key_col[i].as_py()
            self._index[key_bytes] = i

        # Clear diff layer — we're starting fresh from the snapshot.
        self._diffs.clear()
        self._free_rows.clear()

    # -- Inspection ----------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of live UTxOs."""
        return self.utxo_count

    def __contains__(self, key: bytes) -> bool:
        """Check if a TxIn key is in the UTxO set."""
        return key in self._index

    def __repr__(self) -> str:
        return f"LedgerDB(k={self._k}, utxos={self.utxo_count}, diffs={len(self._diffs)})"
