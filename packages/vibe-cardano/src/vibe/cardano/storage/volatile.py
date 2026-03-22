"""VolatileDB — hash-indexed recent block storage with successor map.

Stores recent (not yet finalized) blocks indexed by block hash.  Implements
the :class:`~vibe.core.storage.interfaces.KeyValueStore` protocol and adds
Cardano-specific operations: successor map for chain selection, block metadata
tracking, and garbage collection of finalized blocks.

Haskell reference:
    Ouroboros.Consensus.Storage.VolatileDB.Impl
    - putBlock, getBlockComponent, garbageCollect, filterByPredecessor

On-disk layout:
    Each block is stored as an individual file named ``<hash_hex>.block``
    inside a configurable directory.  On startup the directory is scanned
    to rebuild the in-memory indices.  This mirrors the Haskell VolatileDB's
    per-file storage model (though simplified — we use one block per file
    rather than the Haskell approach of packing multiple blocks per file).

Design rationale:
    - In-memory dicts for O(1) hash lookups and successor queries
    - On-disk files for crash recovery (scan-on-startup)
    - Successor map enables chain selection without full block decoding
    - GC removes blocks at or below the immutable tip slot
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "BlockInfo",
    "ClosedVolatileDBError",
    "VolatileDB",
]

logger = logging.getLogger(__name__)


class ClosedVolatileDBError(Exception):
    """Raised when operating on a closed VolatileDB.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.API.ClosedDBError
    """


@dataclass(frozen=True, slots=True)
class BlockInfo:
    """Lightweight metadata extracted from a block header.

    Stored alongside each block so chain selection can operate on metadata
    without decoding full CBOR block bodies.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Types.InternalBlockInfo
    """

    block_hash: bytes
    slot: int
    predecessor_hash: bytes
    block_number: int


class VolatileDB:
    """Hash-indexed store for recent (volatile) blocks.

    Satisfies the :class:`~vibe.core.storage.interfaces.KeyValueStore`
    protocol structurally, while exposing additional methods for
    successor-map queries and garbage collection.

    Args:
        db_dir: Directory for on-disk block files.  Created if it doesn't
            exist.  Pass ``None`` for a pure in-memory store (no persistence).
    """

    def __init__(self, db_dir: Path | None = None) -> None:
        # Core index: block_hash -> CBOR block bytes
        self._blocks: dict[bytes, bytes] = {}

        # Metadata index: block_hash -> BlockInfo
        self._block_info: dict[bytes, BlockInfo] = {}

        # Successor map: predecessor_hash -> [successor_hashes]
        self._successors: dict[bytes, list[bytes]] = {}

        # Track the maximum slot for fast tip queries
        self._max_slot: int = -1

        # On-disk persistence directory (None = pure in-memory)
        self._db_dir: Path | None = db_dir
        if db_dir is not None:
            db_dir.mkdir(parents=True, exist_ok=True)

        # Closed flag
        self._closed: bool = False

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    def _check_closed(self) -> None:
        """Raise if the DB has been closed."""
        if self._closed:
            raise ClosedVolatileDBError("VolatileDB has been closed")

    def close(self) -> None:
        """Close the VolatileDB, preventing further operations.

        Haskell reference:
            Ouroboros.Consensus.Storage.VolatileDB.API.closeDB
        """
        self._closed = True

    @property
    def is_closed(self) -> bool:
        """Whether the DB has been closed."""
        return self._closed

    # -------------------------------------------------------------------
    # KeyValueStore protocol methods
    # -------------------------------------------------------------------

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve block CBOR bytes by block hash.

        Args:
            key: The 32-byte block header hash.

        Returns:
            CBOR-encoded block bytes, or ``None`` if not present.
        """
        self._check_closed()
        return self._blocks.get(key)

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a block by hash.  Delegates to :meth:`add_block` with
        dummy metadata.  Prefer :meth:`add_block` for production use.

        This method exists to satisfy the KeyValueStore protocol.
        Without metadata, successor map and slot tracking are not updated.

        Args:
            key: Block hash.
            value: CBOR block bytes.
        """
        self._blocks[key] = value
        if self._db_dir is not None:
            self._write_file(key, value)

    async def delete(self, key: bytes) -> bool:
        """Delete a block by hash.

        Removes the block from all indices and from disk.

        Args:
            key: Block hash to remove.

        Returns:
            ``True`` if the block existed and was removed.
        """
        return self._remove_block(key)

    async def contains(self, key: bytes) -> bool:
        """Check whether a block hash is in the store."""
        return key in self._blocks

    async def keys(self) -> list[bytes]:
        """Return all block hashes currently stored."""
        return list(self._blocks.keys())

    # -------------------------------------------------------------------
    # Cardano-specific VolatileDB operations
    # -------------------------------------------------------------------

    async def add_block(
        self,
        block_hash: bytes,
        slot: int,
        predecessor_hash: bytes,
        block_number: int,
        cbor_bytes: bytes,
    ) -> None:
        """Store a block with full metadata, updating all indices.

        This is the primary insertion method.  It updates:
        - The block store (hash -> CBOR bytes)
        - The metadata index (hash -> BlockInfo)
        - The successor map (predecessor -> [successors])
        - The max slot tracker

        Haskell reference:
            Ouroboros.Consensus.Storage.VolatileDB.Impl.putBlock

        Args:
            block_hash: 32-byte block header hash.
            slot: Slot number of the block.
            predecessor_hash: Hash of the predecessor block.
            block_number: Block number (height).
            cbor_bytes: CBOR-encoded block bytes.
        """
        self._check_closed()

        info = BlockInfo(
            block_hash=block_hash,
            slot=slot,
            predecessor_hash=predecessor_hash,
            block_number=block_number,
        )

        self._blocks[block_hash] = cbor_bytes
        self._block_info[block_hash] = info

        # Update successor map
        if predecessor_hash not in self._successors:
            self._successors[predecessor_hash] = []
        if block_hash not in self._successors[predecessor_hash]:
            self._successors[predecessor_hash].append(block_hash)

        # Track max slot
        if slot > self._max_slot:
            self._max_slot = slot

        # Persist to disk
        if self._db_dir is not None:
            self._write_file(block_hash, cbor_bytes)

        logger.debug(
            "VolatileDB: added block %s at slot %d (predecessor: %s)",
            block_hash.hex()[:16],
            slot,
            predecessor_hash.hex()[:16],
        )

    async def get_block(self, block_hash: bytes) -> bytes | None:
        """Look up a block by hash.

        Alias for :meth:`get` with a more descriptive name.

        Args:
            block_hash: The block header hash.

        Returns:
            CBOR block bytes, or ``None``.
        """
        return self._blocks.get(block_hash)

    async def get_block_info(self, block_hash: bytes) -> BlockInfo | None:
        """Retrieve metadata for a block without the full CBOR payload.

        Args:
            block_hash: The block header hash.

        Returns:
            :class:`BlockInfo` or ``None`` if not present.
        """
        return self._block_info.get(block_hash)

    async def get_successors(self, block_hash: bytes) -> list[bytes]:
        """Get the hashes of all known successor blocks.

        Used by chain selection to walk forward from a given block and
        find the longest chain.

        Haskell reference:
            Ouroboros.Consensus.Storage.VolatileDB.Impl.filterByPredecessor

        Args:
            block_hash: The predecessor block hash to query.

        Returns:
            List of successor block hashes (may be empty).
        """
        return list(self._successors.get(block_hash, []))

    async def get_max_slot(self) -> int:
        """Return the highest slot number of any block in the store.

        Returns:
            The maximum slot, or ``-1`` if the store is empty.
        """
        return self._max_slot

    async def remove_block(self, block_hash: bytes) -> bool:
        """Remove a single block from the store and all indices.

        Used when promoting a block to the ImmutableDB.

        Args:
            block_hash: The block hash to remove.

        Returns:
            ``True`` if the block was found and removed.
        """
        return self._remove_block(block_hash)

    async def gc(self, immutable_tip_slot: int) -> int:
        """Garbage-collect all blocks with slot <= immutable_tip_slot.

        After the immutable tip advances, blocks at or before that slot
        are finalized and can be removed from the volatile store.

        Haskell reference:
            Ouroboros.Consensus.Storage.VolatileDB.Impl.garbageCollect

        Args:
            immutable_tip_slot: Slot of the current immutable tip.

        Returns:
            Number of blocks removed.
        """
        to_remove = [
            h
            for h, info in self._block_info.items()
            if info.slot <= immutable_tip_slot
        ]
        for h in to_remove:
            self._remove_block(h)

        logger.debug(
            "VolatileDB: GC removed %d blocks at or below slot %d",
            len(to_remove),
            immutable_tip_slot,
        )
        return len(to_remove)

    async def get_all_block_info(self) -> dict[bytes, BlockInfo]:
        """Return metadata for all blocks in the store.

        Useful for chain selection which needs to scan all volatile blocks
        to find the best chain.

        Returns:
            Dict mapping block hash to :class:`BlockInfo`.
        """
        return dict(self._block_info)

    @property
    def block_count(self) -> int:
        """Number of blocks currently in the store."""
        return len(self._blocks)

    # -------------------------------------------------------------------
    # Startup / recovery
    # -------------------------------------------------------------------

    async def load_from_disk(
        self,
        parse_header: callable,  # type: ignore[type-arg]
    ) -> int:
        """Rebuild in-memory indices by scanning on-disk block files.

        Called during startup to recover state after a crash or restart.
        Each ``.block`` file is read and its header parsed to extract
        metadata for the index and successor map.

        Args:
            parse_header: A callable ``(cbor_bytes) -> BlockInfo`` that
                extracts block metadata from the raw CBOR.  This keeps
                the VolatileDB decoupled from any specific CBOR schema.

        Returns:
            Number of blocks loaded.

        Raises:
            FileNotFoundError: If ``db_dir`` was not set.
        """
        if self._db_dir is None:
            msg = "Cannot load from disk: no db_dir configured"
            raise FileNotFoundError(msg)

        count = 0
        for filename in os.listdir(self._db_dir):
            if not filename.endswith(".block"):
                continue
            filepath = self._db_dir / filename
            cbor_bytes = filepath.read_bytes()
            try:
                info = parse_header(cbor_bytes)
            except Exception:
                logger.warning(
                    "VolatileDB: skipping corrupt block file %s", filename
                )
                continue

            self._blocks[info.block_hash] = cbor_bytes
            self._block_info[info.block_hash] = info

            if info.predecessor_hash not in self._successors:
                self._successors[info.predecessor_hash] = []
            if info.block_hash not in self._successors[info.predecessor_hash]:
                self._successors[info.predecessor_hash].append(info.block_hash)

            if info.slot > self._max_slot:
                self._max_slot = info.slot

            count += 1

        logger.info("VolatileDB loaded %d blocks from disk", count, extra={"event": "volatiledb.loaded", "block_count": count})
        return count

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _remove_block(self, block_hash: bytes) -> bool:
        """Remove a block from all in-memory indices and disk.

        Returns ``True`` if the block existed.
        """
        if block_hash not in self._blocks:
            return False

        # Remove from block store
        del self._blocks[block_hash]

        # Remove from block info and successor map
        info = self._block_info.pop(block_hash, None)
        if info is not None:
            # Remove from predecessor's successor list
            succs = self._successors.get(info.predecessor_hash)
            if succs is not None:
                try:
                    succs.remove(block_hash)
                except ValueError:
                    pass
                if not succs:
                    del self._successors[info.predecessor_hash]

        # Also remove any successor entries where this block is predecessor
        # (the successors themselves remain — they just lose their predecessor
        # link, which is fine since they'll be GC'd or re-linked)
        # We keep successor entries for now; they'll be cleaned up when
        # those successor blocks are themselves removed.

        # Remove from disk
        if self._db_dir is not None:
            self._delete_file(block_hash)

        # Recompute max slot if we removed the tip
        if info is not None and info.slot == self._max_slot:
            self._recompute_max_slot()

        return True

    def _recompute_max_slot(self) -> None:
        """Recompute _max_slot from the block_info index."""
        if self._block_info:
            self._max_slot = max(info.slot for info in self._block_info.values())
        else:
            self._max_slot = -1

    def _write_file(self, block_hash: bytes, data: bytes) -> None:
        """Write a block file to disk."""
        assert self._db_dir is not None
        filepath = self._db_dir / f"{block_hash.hex()}.block"
        filepath.write_bytes(data)

    def _delete_file(self, block_hash: bytes) -> None:
        """Remove a block file from disk."""
        assert self._db_dir is not None
        filepath = self._db_dir / f"{block_hash.hex()}.block"
        try:
            filepath.unlink()
        except FileNotFoundError:
            pass
