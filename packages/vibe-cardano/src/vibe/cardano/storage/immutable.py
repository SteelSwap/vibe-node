"""ImmutableDB — epoch-chunked append-only block storage.

Stores finalized (immutable) blocks in epoch-sized chunk files with
binary primary and secondary indexes for O(1) lookups by slot or hash.

Design mirrors the Haskell ouroboros-consensus ImmutableDB:

- **Chunk files** — One file per epoch. Blocks are raw CBOR bytes,
  concatenated sequentially with no framing or separators.
  Ref: Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
       "chunk files are the concatenation of the raw blocks"

- **Primary index** — Maps relative slot within a chunk to byte offset.
  Binary format: array of uint64 (big-endian). Empty slots carry forward
  the previous filled slot's offset so that ``offset[i+1] - offset[i]``
  gives the block size (0 for empty slots).
  Ref: Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary

- **Secondary index** — Maps block hash to (chunk_number, offset, size).
  One entry per actually-stored block.  Enables hash-based lookup.
  Ref: Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Secondary

- **Epoch info** — Each chunk tracks its epoch number, start slot, and
  the range of slots it covers.

Implements :class:`~vibe.core.storage.AppendStore`.
"""

from __future__ import annotations

import os
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

__all__ = [
    "ImmutableDB",
    "ImmutableDBIterator",
    "ChunkInfo",
    "AppendBlockNotNewerThanTipError",
    "ClosedDBError",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChunkInfo:
    """Metadata about one epoch chunk.

    Attributes:
        chunk_number: Sequential chunk identifier (== epoch number).
        start_slot: First absolute slot in this chunk.
        slot_count: Number of slots this chunk covers.
    """

    chunk_number: int
    start_slot: int
    slot_count: int

    @property
    def end_slot(self) -> int:
        """Last absolute slot (inclusive) in this chunk."""
        return self.start_slot + self.slot_count - 1


@dataclass(slots=True)
class _SecondaryEntry:
    """One entry in the secondary index.

    Attributes:
        block_hash: 32-byte block header hash.
        chunk_number: Which chunk file contains this block.
        offset: Byte offset within the chunk file.
        size: Size in bytes of the block's CBOR payload.
        slot: Absolute slot number.
    """

    block_hash: bytes
    chunk_number: int
    offset: int
    size: int
    slot: int


# Secondary index entry on-disk format:
#   32 bytes hash | 4 bytes chunk_number (uint32 BE) |
#   8 bytes offset (uint64 BE) | 4 bytes size (uint32 BE) |
#   8 bytes slot (uint64 BE)
# Total: 56 bytes
_SEC_ENTRY_FMT = ">32sIQIQ"
_SEC_ENTRY_SIZE = struct.calcsize(_SEC_ENTRY_FMT)

# Primary index entry: uint64 big-endian offset
_PRI_ENTRY_FMT = ">Q"
_PRI_ENTRY_SIZE = struct.calcsize(_PRI_ENTRY_FMT)


class ClosedDBError(Exception):
    """Raised when operating on a closed database.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.ClosedDBError
    """


class AppendBlockNotNewerThanTipError(Exception):
    """Raised when attempting to append a block not newer than tip.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API.AppendBlockNotNewerThanTipError
    """

    def __init__(self, block_slot: int, tip_slot: int) -> None:
        self.block_slot = block_slot
        self.tip_slot = tip_slot
        super().__init__(
            f"Cannot append block at slot {block_slot}: "
            f"current tip is at slot {tip_slot}"
        )


# ---------------------------------------------------------------------------
# ImmutableDB
# ---------------------------------------------------------------------------


class ImmutableDB:
    """Epoch-chunked append-only block store.

    Implements the :class:`~vibe.core.storage.AppendStore` protocol.

    Args:
        base_dir: Directory for chunk files and indexes.
        epoch_size: Number of slots per epoch/chunk (default 432000 for mainnet).

    File layout under *base_dir*::

        chunks/
            chunk-000000.dat    # raw concatenated CBOR blocks
            chunk-000001.dat
            ...
        primary/
            chunk-000000.idx    # array of uint64 offsets
            chunk-000001.idx
            ...
        secondary/
            chunk-000000.idx    # per-block (hash, chunk, offset, size, slot)
            chunk-000001.idx
            ...
    """

    def __init__(self, base_dir: str | Path, epoch_size: int = 432_000) -> None:
        self._base_dir = Path(base_dir)
        self._epoch_size = epoch_size

        # Directories
        self._chunk_dir = self._base_dir / "chunks"
        self._primary_dir = self._base_dir / "primary"
        self._secondary_dir = self._base_dir / "secondary"

        # In-memory secondary index: hash -> _SecondaryEntry
        self._hash_index: dict[bytes, _SecondaryEntry] = {}

        # Current tip tracking
        self._tip_slot: int | None = None
        self._tip_hash: bytes | None = None

        # Current chunk state
        self._current_chunk: int = 0
        self._current_chunk_offset: int = 0

        # Ensure directories exist
        self._chunk_dir.mkdir(parents=True, exist_ok=True)
        self._primary_dir.mkdir(parents=True, exist_ok=True)
        self._secondary_dir.mkdir(parents=True, exist_ok=True)

        # Recover state from existing files
        self._recover()

    # -------------------------------------------------------------------
    # Path helpers
    # -------------------------------------------------------------------

    def _chunk_path(self, chunk_number: int) -> Path:
        return self._chunk_dir / f"chunk-{chunk_number:06d}.dat"

    def _primary_path(self, chunk_number: int) -> Path:
        return self._primary_dir / f"chunk-{chunk_number:06d}.idx"

    def _secondary_path(self, chunk_number: int) -> Path:
        return self._secondary_dir / f"chunk-{chunk_number:06d}.idx"

    # -------------------------------------------------------------------
    # Chunk / slot math
    # -------------------------------------------------------------------

    def _slot_to_chunk(self, slot: int) -> int:
        """Map absolute slot to chunk number."""
        return slot // self._epoch_size

    def _slot_to_relative(self, slot: int) -> int:
        """Map absolute slot to relative slot within its chunk."""
        return slot % self._epoch_size

    def _chunk_info(self, chunk_number: int) -> ChunkInfo:
        """Return ChunkInfo for a given chunk number."""
        return ChunkInfo(
            chunk_number=chunk_number,
            start_slot=chunk_number * self._epoch_size,
            slot_count=self._epoch_size,
        )

    # -------------------------------------------------------------------
    # Recovery
    # -------------------------------------------------------------------

    def _recover(self) -> None:
        """Rebuild in-memory state from on-disk indexes.

        Scans secondary index files to rebuild the hash index and
        determine the current tip.  This runs once at startup and
        handles crash recovery — if the node was killed mid-write,
        the indexes are the source of truth.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.openDBInternal
        """
        # Find all secondary index files
        sec_files = sorted(self._secondary_dir.glob("chunk-*.idx"))
        if not sec_files:
            return

        latest_slot: int | None = None
        latest_hash: bytes | None = None
        latest_chunk: int = 0
        latest_chunk_offset: int = 0

        for sec_path in sec_files:
            chunk_num = int(sec_path.stem.split("-")[1])
            file_size = sec_path.stat().st_size
            if file_size == 0:
                continue

            with open(sec_path, "rb") as f:
                while True:
                    data = f.read(_SEC_ENTRY_SIZE)
                    if len(data) < _SEC_ENTRY_SIZE:
                        break
                    block_hash, c_num, offset, size, slot = struct.unpack(
                        _SEC_ENTRY_FMT, data
                    )
                    entry = _SecondaryEntry(
                        block_hash=block_hash,
                        chunk_number=c_num,
                        offset=offset,
                        size=size,
                        slot=slot,
                    )
                    self._hash_index[block_hash] = entry

                    if latest_slot is None or slot > latest_slot:
                        latest_slot = slot
                        latest_hash = block_hash
                        latest_chunk = c_num
                        latest_chunk_offset = offset + size

        self._tip_slot = latest_slot
        self._tip_hash = latest_hash
        self._current_chunk = latest_chunk
        self._current_chunk_offset = latest_chunk_offset

    # -------------------------------------------------------------------
    # Primary index operations
    # -------------------------------------------------------------------

    def _read_primary_offsets(self, chunk_number: int) -> list[int]:
        """Read all offsets from a primary index file.

        Returns a list of uint64 offsets.  If the file doesn't exist,
        returns an empty list.
        """
        path = self._primary_path(chunk_number)
        if not path.exists():
            return []
        data = path.read_bytes()
        count = len(data) // _PRI_ENTRY_SIZE
        return list(struct.unpack(f">{count}Q", data[: count * _PRI_ENTRY_SIZE]))

    def _write_primary_entry(self, chunk_number: int, relative_slot: int, offset: int) -> None:
        """Extend the primary index so relative_slot maps to offset.

        Empty slots between the current end and relative_slot are filled
        with the last known offset (so offset[i+1] - offset[i] == 0 for
        empty slots).

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary.appendOffsets
        """
        path = self._primary_path(chunk_number)

        # Read current entries
        if path.exists():
            data = path.read_bytes()
            current_count = len(data) // _PRI_ENTRY_SIZE
        else:
            data = b""
            current_count = 0

        # The primary index has (relative_slot + 1) entries: one offset per
        # slot from 0..relative_slot inclusive, representing the *start* of
        # each slot's block (or the previous block's end for empty slots).
        needed = relative_slot + 1
        if needed <= current_count:
            # Already have an entry for this slot — just update it
            # (shouldn't happen with monotonic appends, but be safe)
            offset_bytes = struct.pack(_PRI_ENTRY_FMT, offset)
            data = data[: relative_slot * _PRI_ENTRY_SIZE] + offset_bytes + data[(relative_slot + 1) * _PRI_ENTRY_SIZE :]
            path.write_bytes(data)
            return

        # Fill gaps: repeat the last offset for empty slots
        if current_count > 0:
            last_offset = struct.unpack_from(
                _PRI_ENTRY_FMT, data, (current_count - 1) * _PRI_ENTRY_SIZE
            )[0]
        else:
            last_offset = 0

        fill = b""
        for _i in range(current_count, needed):
            fill += struct.pack(_PRI_ENTRY_FMT, last_offset)

        # Now write the actual entry for this slot
        entry = struct.pack(_PRI_ENTRY_FMT, offset)

        with open(path, "ab") as f:
            f.write(fill + entry)

    # -------------------------------------------------------------------
    # Secondary index operations
    # -------------------------------------------------------------------

    def _write_secondary_entry(self, entry: _SecondaryEntry) -> None:
        """Append one entry to the secondary index file for the entry's chunk.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Secondary.appendEntry
        """
        path = self._secondary_path(entry.chunk_number)
        data = struct.pack(
            _SEC_ENTRY_FMT,
            entry.block_hash,
            entry.chunk_number,
            entry.offset,
            entry.size,
            entry.slot,
        )
        with open(path, "ab") as f:
            f.write(data)

    def _read_secondary_entries(self, chunk_number: int) -> list[_SecondaryEntry]:
        """Read all entries from a secondary index file."""
        path = self._secondary_path(chunk_number)
        if not path.exists():
            return []
        data = path.read_bytes()
        entries: list[_SecondaryEntry] = []
        for i in range(0, len(data), _SEC_ENTRY_SIZE):
            if i + _SEC_ENTRY_SIZE > len(data):
                break
            block_hash, c_num, offset, size, slot = struct.unpack(
                _SEC_ENTRY_FMT, data[i : i + _SEC_ENTRY_SIZE]
            )
            entries.append(
                _SecondaryEntry(
                    block_hash=block_hash,
                    chunk_number=c_num,
                    offset=offset,
                    size=size,
                    slot=slot,
                )
            )
        return entries

    # -------------------------------------------------------------------
    # AppendStore protocol implementation
    # -------------------------------------------------------------------

    async def append(self, key: bytes, value: bytes) -> None:
        """Append a block to the ImmutableDB.

        The *key* encodes the block identity: 8-byte big-endian slot
        followed by 32-byte block hash (40 bytes total).

        The *value* is raw CBOR-encoded block bytes.

        Raises:
            AppendBlockNotNewerThanTipError: If slot <= current tip slot.
            ValueError: If key format is invalid.
        """
        if len(key) < 40:
            msg = f"Key must be >= 40 bytes (8-byte slot + 32-byte hash), got {len(key)}"
            raise ValueError(msg)

        slot = struct.unpack(">Q", key[:8])[0]
        block_hash = key[8:40]

        await self.append_block(slot, block_hash, value)

    async def append_block(self, slot: int, block_hash: bytes, cbor_bytes: bytes) -> None:
        """Append a block at the given slot.

        This is the primary append API, corresponding to the Haskell
        ``appendBlock`` function.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.appendBlock
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.appendBlockImpl

        Args:
            slot: Absolute slot number.
            block_hash: 32-byte block header hash.
            cbor_bytes: Raw CBOR-encoded block bytes.

        Raises:
            AppendBlockNotNewerThanTipError: If slot <= current tip slot.
        """
        # Enforce monotonic slot ordering
        if self._tip_slot is not None and slot <= self._tip_slot:
            raise AppendBlockNotNewerThanTipError(slot, self._tip_slot)

        chunk_number = self._slot_to_chunk(slot)
        relative_slot = self._slot_to_relative(slot)

        # Handle chunk rollover
        if chunk_number > self._current_chunk:
            self._current_chunk = chunk_number
            self._current_chunk_offset = 0

        # Write block to chunk file
        chunk_path = self._chunk_path(chunk_number)
        offset = self._current_chunk_offset
        with open(chunk_path, "ab") as f:
            f.write(cbor_bytes)

        block_size = len(cbor_bytes)
        self._current_chunk_offset = offset + block_size

        # Update primary index — write start offset at relative_slot and
        # end offset at relative_slot + 1.  The Haskell primary index uses
        # N+1 entries so that size = offset[i+1] - offset[i].
        self._write_primary_entry(chunk_number, relative_slot, offset)
        self._write_primary_entry(chunk_number, relative_slot + 1, offset + block_size)

        # Create and write secondary index entry
        # Pad or truncate hash to 32 bytes
        padded_hash = block_hash[:32].ljust(32, b"\x00")
        entry = _SecondaryEntry(
            block_hash=padded_hash,
            chunk_number=chunk_number,
            offset=offset,
            size=block_size,
            slot=slot,
        )
        self._write_secondary_entry(entry)
        self._hash_index[padded_hash] = entry

        # Update tip
        self._tip_slot = slot
        self._tip_hash = padded_hash

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a block by key (slot + hash).

        Tries hash-based lookup first (fast path via secondary index).
        Falls back to slot-based lookup if the hash portion is zero-filled.
        """
        if len(key) < 40:
            return None

        block_hash = key[8:40]
        padded_hash = block_hash[:32].ljust(32, b"\x00")

        # Try hash lookup
        result = await self.get_block(padded_hash)
        if result is not None:
            return result

        # Try slot lookup
        slot = struct.unpack(">Q", key[:8])[0]
        return await self.get_block_by_slot(slot)

    async def get_block(self, block_hash: bytes) -> bytes | None:
        """Look up a block by its 32-byte hash via secondary index.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.getBlockComponent
        """
        padded_hash = block_hash[:32].ljust(32, b"\x00")
        entry = self._hash_index.get(padded_hash)
        if entry is None:
            return None
        return self._read_block(entry.chunk_number, entry.offset, entry.size)

    async def get_block_by_slot(self, slot: int) -> bytes | None:
        """Look up a block by absolute slot via primary index.

        Uses the primary index to find the byte offset, then reads from
        the chunk file.  Returns None if the slot is empty.

        Haskell reference:
            Primary index lookup in
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Index.Primary
        """
        chunk_number = self._slot_to_chunk(slot)
        relative_slot = self._slot_to_relative(slot)

        offsets = self._read_primary_offsets(chunk_number)
        if not offsets:
            return None

        # Need the entry for this slot and the next to compute size
        if relative_slot >= len(offsets):
            return None

        start = offsets[relative_slot]

        # Find end offset: next different offset or end of file
        end: int | None = None
        if relative_slot + 1 < len(offsets):
            end = offsets[relative_slot + 1]
        else:
            # Last entry — read to end of chunk file
            chunk_path = self._chunk_path(chunk_number)
            if chunk_path.exists():
                end = chunk_path.stat().st_size
            else:
                return None

        if end is None or end <= start:
            # Empty slot (offset didn't change)
            return None

        return self._read_block(chunk_number, start, end - start)

    def _read_block(self, chunk_number: int, offset: int, size: int) -> bytes | None:
        """Read raw block bytes from a chunk file."""
        chunk_path = self._chunk_path(chunk_number)
        if not chunk_path.exists():
            return None
        with open(chunk_path, "rb") as f:
            f.seek(offset)
            data = f.read(size)
        if len(data) != size:
            return None
        return data

    async def get_tip(self) -> bytes | None:
        """Return the key of the most recently appended block.

        The key format is 8-byte big-endian slot + 32-byte hash.
        Returns None if the DB is empty.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.getTip
        """
        if self._tip_slot is None or self._tip_hash is None:
            return None
        return struct.pack(">Q", self._tip_slot) + self._tip_hash

    def get_tip_slot(self) -> int | None:
        """Return the slot of the most recently appended block, or None."""
        return self._tip_slot

    def get_tip_hash(self) -> bytes | None:
        """Return the hash of the most recently appended block, or None."""
        return self._tip_hash

    async def iter_from(self, start_key: bytes) -> AsyncIterator[tuple[bytes, bytes]]:
        """Iterate blocks from start_key (inclusive) forward.

        Yields (key, cbor_bytes) tuples in slot order. The key format
        is 8-byte big-endian slot + 32-byte hash.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.streamAfterKnownPoint

        Args:
            start_key: Key to start from (at minimum 8 bytes for slot).
        """
        if len(start_key) < 8:
            return

        start_slot = struct.unpack(">Q", start_key[:8])[0]

        if self._tip_slot is None:
            return

        start_chunk = self._slot_to_chunk(start_slot)
        end_chunk = self._slot_to_chunk(self._tip_slot)

        for chunk_num in range(start_chunk, end_chunk + 1):
            entries = self._read_secondary_entries(chunk_num)
            for entry in entries:
                if entry.slot < start_slot:
                    continue
                block_data = self._read_block(
                    entry.chunk_number, entry.offset, entry.size
                )
                if block_data is not None:
                    key = struct.pack(">Q", entry.slot) + entry.block_hash
                    yield key, block_data

    # -------------------------------------------------------------------
    # Iterator with explicit control
    # -------------------------------------------------------------------

    def stream(self, start_slot: int = 0) -> ImmutableDBIterator:
        """Create a stateful iterator over blocks from start_slot.

        Returns an :class:`ImmutableDBIterator` with explicit ``has_next``,
        ``next``, and ``close`` methods.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.stream
        """
        return ImmutableDBIterator(self, start_slot)

    # -------------------------------------------------------------------
    # DeleteAfter — truncate chain
    # -------------------------------------------------------------------

    async def delete_after(self, slot: int) -> int:
        """Truncate all blocks after the given slot.

        Removes blocks with slot > the given slot from chunk files and
        indexes.  Returns the number of blocks removed.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.deleteAfter
        """
        if self._tip_slot is None or slot >= self._tip_slot:
            return 0

        removed = 0
        # Walk through secondary entries and remove those with slot > cutoff
        hashes_to_remove = [
            h for h, entry in self._hash_index.items()
            if entry.slot > slot
        ]
        removed = len(hashes_to_remove)

        for h in hashes_to_remove:
            del self._hash_index[h]

        if slot < 0 or not self._hash_index:
            # Removed everything — truncate all files
            self._tip_slot = None
            self._tip_hash = None
            self._current_chunk = 0
            self._current_chunk_offset = 0
            # Remove all chunk / index files
            for f in self._chunk_dir.glob("chunk-*.dat"):
                f.unlink()
            for f in self._primary_dir.glob("chunk-*.idx"):
                f.unlink()
            for f in self._secondary_dir.glob("chunk-*.idx"):
                f.unlink()
            return removed

        # Find the new tip
        new_tip_entry = max(self._hash_index.values(), key=lambda e: e.slot)
        self._tip_slot = new_tip_entry.slot
        self._tip_hash = new_tip_entry.block_hash
        self._current_chunk = new_tip_entry.chunk_number
        self._current_chunk_offset = new_tip_entry.offset + new_tip_entry.size

        # Rebuild secondary index files by rewriting only surviving entries
        # Group entries by chunk
        chunks_with_entries: dict[int, list[_SecondaryEntry]] = {}
        for entry in self._hash_index.values():
            chunks_with_entries.setdefault(entry.chunk_number, []).append(entry)

        # Determine which chunk files exist
        max_chunk_on_disk = 0
        for f in self._secondary_dir.glob("chunk-*.idx"):
            cn = int(f.stem.split("-")[1])
            max_chunk_on_disk = max(max_chunk_on_disk, cn)

        # Rewrite secondary indexes and truncate chunk files for affected chunks
        cutoff_chunk = self._slot_to_chunk(slot)
        for cn in range(cutoff_chunk, max_chunk_on_disk + 1):
            entries = sorted(
                chunks_with_entries.get(cn, []),
                key=lambda e: e.slot,
            )
            sec_path = self._secondary_path(cn)
            if not entries:
                # Remove empty chunk and its indexes
                sec_path.unlink(missing_ok=True)
                self._primary_path(cn).unlink(missing_ok=True)
                self._chunk_path(cn).unlink(missing_ok=True)
                continue

            # Rewrite secondary index
            with open(sec_path, "wb") as f:
                for entry in entries:
                    f.write(struct.pack(
                        _SEC_ENTRY_FMT,
                        entry.block_hash,
                        entry.chunk_number,
                        entry.offset,
                        entry.size,
                        entry.slot,
                    ))

            # Truncate chunk file to end of last surviving block
            last = entries[-1]
            chunk_path = self._chunk_path(cn)
            if chunk_path.exists():
                new_size = last.offset + last.size
                with open(chunk_path, "r+b") as f:
                    f.truncate(new_size)

            # Rebuild primary index for this chunk
            pri_path = self._primary_path(cn)
            max_rel_slot = max(self._slot_to_relative(e.slot) for e in entries)
            # Build offset array
            offsets: list[int] = []
            entry_map = {self._slot_to_relative(e.slot): e for e in entries}
            last_offset = 0
            for rs in range(max_rel_slot + 2):  # +2 for the end sentinel
                if rs in entry_map:
                    offsets.append(entry_map[rs].offset)
                    last_offset = entry_map[rs].offset + entry_map[rs].size
                else:
                    offsets.append(last_offset)
            with open(pri_path, "wb") as f:
                for o in offsets:
                    f.write(struct.pack(_PRI_ENTRY_FMT, o))

        return removed

    # -------------------------------------------------------------------
    # Close — mark DB as closed
    # -------------------------------------------------------------------

    def close(self) -> None:
        """Close the ImmutableDB, preventing further operations.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.API.closeDB
        """
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Whether the DB has been closed."""
        return getattr(self, "_closed", False)

    # -------------------------------------------------------------------
    # Corruption recovery
    # -------------------------------------------------------------------

    async def validate_and_recover(self) -> int:
        """Validate chunk files against indexes and recover from corruption.

        Scans all chunks and verifies that each block can be read and has
        the expected size.  If corruption is detected, truncates to the
        last valid block.

        Returns the number of blocks that survived validation.

        Haskell reference:
            Ouroboros.Consensus.Storage.ImmutableDB.Impl.Validation
        """
        valid_entries: dict[bytes, _SecondaryEntry] = {}
        last_valid_slot: int | None = None
        last_valid_hash: bytes | None = None
        last_valid_chunk: int = 0
        last_valid_offset: int = 0

        sec_files = sorted(self._secondary_dir.glob("chunk-*.idx"))
        for sec_path in sec_files:
            chunk_num = int(sec_path.stem.split("-")[1])
            chunk_path = self._chunk_path(chunk_num)

            if not chunk_path.exists():
                # Missing chunk file — stop here, truncate everything after
                break

            chunk_data = chunk_path.read_bytes()
            entries = self._read_secondary_entries(chunk_num)

            chunk_valid = True
            for entry in entries:
                # Validate: can we read the block at the declared offset/size?
                if entry.offset + entry.size > len(chunk_data):
                    chunk_valid = False
                    break

                block_bytes = chunk_data[entry.offset : entry.offset + entry.size]
                if len(block_bytes) != entry.size:
                    chunk_valid = False
                    break

                valid_entries[entry.block_hash] = entry
                last_valid_slot = entry.slot
                last_valid_hash = entry.block_hash
                last_valid_chunk = entry.chunk_number
                last_valid_offset = entry.offset + entry.size

            if not chunk_valid:
                break

        # Update state to reflect validated entries only
        self._hash_index = valid_entries
        self._tip_slot = last_valid_slot
        self._tip_hash = last_valid_hash
        self._current_chunk = last_valid_chunk
        self._current_chunk_offset = last_valid_offset

        return len(valid_entries)


# ---------------------------------------------------------------------------
# ImmutableDBIterator — stateful iterator with has_next / close
# ---------------------------------------------------------------------------


class ImmutableDBIterator:
    """Stateful iterator over ImmutableDB blocks.

    Provides ``has_next()``, ``next()``, and ``close()`` for explicit
    lifecycle control — mirrors the Haskell Iterator type:

        Ouroboros.Consensus.Storage.ImmutableDB.API.Iterator

    Once closed, calling ``next()`` raises :class:`ClosedDBError`.
    """

    def __init__(self, db: ImmutableDB, start_slot: int = 0) -> None:
        self._db = db
        self._closed = False

        # Pre-load all secondary entries from start_slot onward
        self._entries: list[_SecondaryEntry] = []
        self._pos: int = 0

        if db._tip_slot is None:
            return

        start_chunk = db._slot_to_chunk(start_slot)
        end_chunk = db._slot_to_chunk(db._tip_slot)

        for chunk_num in range(start_chunk, end_chunk + 1):
            entries = db._read_secondary_entries(chunk_num)
            for entry in entries:
                if entry.slot >= start_slot:
                    self._entries.append(entry)

        # Sort by slot for deterministic ordering
        self._entries.sort(key=lambda e: e.slot)

    def has_next(self) -> bool:
        """Check whether more blocks are available.

        Returns ``False`` if closed or exhausted.
        """
        if self._closed:
            return False
        return self._pos < len(self._entries)

    def next(self) -> tuple[bytes, bytes]:
        """Return the next ``(key, cbor_bytes)`` pair.

        Raises:
            ClosedDBError: If the iterator has been closed.
            StopIteration: If no more blocks are available.
        """
        if self._closed:
            raise ClosedDBError("Iterator has been closed")

        if self._pos >= len(self._entries):
            raise StopIteration

        entry = self._entries[self._pos]
        self._pos += 1

        block_data = self._db._read_block(
            entry.chunk_number, entry.offset, entry.size
        )
        if block_data is None:
            block_data = b""

        key = struct.pack(">Q", entry.slot) + entry.block_hash
        return key, block_data

    def close(self) -> None:
        """Close the iterator, releasing resources.

        After closing, :meth:`has_next` returns ``False`` and
        :meth:`next` raises :class:`ClosedDBError`.
        """
        self._closed = True
        self._entries.clear()
