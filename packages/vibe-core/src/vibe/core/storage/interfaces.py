"""Storage protocol interfaces — protocol-agnostic abstract stores.

These are structural types (Python Protocols) that define the contracts
for the three storage subsystems in a blockchain node:

- **AppendStore** — sequential, append-only storage (used by ImmutableDB)
- **KeyValueStore** — mutable key-value storage (used by VolatileDB)
- **StateStore** — batch-oriented state storage with snapshots (used by LedgerDB)

All interfaces use ``bytes`` for keys and values to remain serialization-
agnostic.  Higher-level code wraps these with typed encoders/decoders.

Haskell reference:
    ouroboros-consensus/src/ouroboros-consensus/Ouroboros/Consensus/Storage/
    The Haskell node defines ImmutableDB, VolatileDB, and LedgerDB as
    separate subsystems with distinct access patterns.  Our Protocol
    interfaces capture the essential contract of each without coupling
    to Cardano-specific types.

Design rationale:
    These live in vibe-core (not vibe-cardano) because the access patterns
    — append-only, key-value, state-with-snapshots — are universal to any
    blockchain node implementation.  Cardano-specific storage logic goes in
    vibe-cardano and implements these protocols with concrete backends.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "AppendStore",
    "KeyValueStore",
    "SnapshotHandle",
    "StateStore",
]


@dataclass(frozen=True, slots=True)
class SnapshotHandle:
    """Opaque handle for a point-in-time state snapshot.

    Returned by :meth:`StateStore.snapshot` and consumed by
    :meth:`StateStore.restore`.  The ``snapshot_id`` is an opaque
    identifier — its format is backend-defined (could be a filename,
    a monotonic counter, an LSN, etc.).

    Attributes:
        snapshot_id: Backend-defined opaque identifier for this snapshot.
        metadata: Optional key-value metadata (e.g., slot number, block hash).
    """

    snapshot_id: str
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AppendStore — for ImmutableDB
# ---------------------------------------------------------------------------


@runtime_checkable
class AppendStore(Protocol):
    """Append-only sequential store.

    Models the access pattern of the Haskell ImmutableDB: blocks are
    appended in slot order and never modified or deleted.  Reads can
    look up by key or iterate forward from a given key.

    Haskell reference:
        Ouroboros.Consensus.Storage.ImmutableDB.API
        - appendBlock, getBlockComponent, streamAfterKnownPoint
    """

    async def append(self, key: bytes, value: bytes) -> None:
        """Append a key-value pair in sequential order.

        The caller must ensure keys are appended in monotonically
        increasing order (e.g., slot numbers encoded as big-endian bytes).
        Implementations may raise if ordering is violated.

        Args:
            key: The lookup key (e.g., encoded slot + block hash).
            value: The payload (e.g., serialized block).

        Raises:
            ValueError: If the key violates sequential ordering.
        """
        ...

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key, or ``None`` if not found.

        Args:
            key: The key to look up.

        Returns:
            The stored bytes, or ``None`` if the key does not exist.
        """
        ...

    async def get_tip(self) -> bytes | None:
        """Return the key of the most recently appended entry.

        Returns:
            The tip key, or ``None`` if the store is empty.
        """
        ...

    async def iter_from(self, start_key: bytes) -> AsyncIterator[tuple[bytes, bytes]]:
        """Iterate key-value pairs starting from *start_key* (inclusive).

        Yields pairs in the order they were appended.  If *start_key*
        does not exist, iteration starts from the next key after it.

        Args:
            start_key: The key to start iteration from.

        Yields:
            ``(key, value)`` tuples in append order.
        """
        ...
        # Make the function an async generator so type checkers are happy.
        # Concrete implementations override the entire method body.
        if False:  # pragma: no cover
            yield b"", b""


# ---------------------------------------------------------------------------
# KeyValueStore — for VolatileDB
# ---------------------------------------------------------------------------


@runtime_checkable
class KeyValueStore(Protocol):
    """Mutable key-value store.

    Models the access pattern of the Haskell VolatileDB: recent blocks
    are stored by hash and may be added, queried, or garbage-collected.

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.API
        - putBlock, getBlockComponent, garbageCollect, filterByPredecessor
    """

    async def get(self, key: bytes) -> bytes | None:
        """Retrieve a value by key, or ``None`` if not found.

        Args:
            key: The key to look up.

        Returns:
            The stored bytes, or ``None`` if the key does not exist.
        """
        ...

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair, overwriting any existing value.

        Args:
            key: The key to store under.
            value: The payload to store.
        """
        ...

    async def delete(self, key: bytes) -> bool:
        """Delete a key-value pair.

        Args:
            key: The key to delete.

        Returns:
            ``True`` if the key existed and was deleted, ``False`` otherwise.
        """
        ...

    async def contains(self, key: bytes) -> bool:
        """Check whether a key exists in the store.

        Args:
            key: The key to check.

        Returns:
            ``True`` if the key exists, ``False`` otherwise.
        """
        ...

    async def keys(self) -> list[bytes]:
        """Return all keys currently in the store.

        Returns:
            A list of all stored keys (order is implementation-defined).
        """
        ...


# ---------------------------------------------------------------------------
# StateStore — for LedgerDB
# ---------------------------------------------------------------------------


@runtime_checkable
class StateStore(Protocol):
    """Batch-oriented state store with snapshot support.

    Models the access pattern of the Haskell LedgerDB: the ledger state
    is a large key-value map that gets bulk-updated at each block
    application, with periodic snapshots for crash recovery.

    Haskell reference:
        Ouroboros.Consensus.Storage.LedgerDB.API
        - getCurrent, takeSnapshot, restoreSnapshot
        Ouroboros.Consensus.Storage.LedgerDB.BackingStore
        - bsRead, bsWrite, bsCopy
    """

    async def get(self, key: bytes) -> bytes | None:
        """Point lookup for a single key.

        Args:
            key: The key to look up.

        Returns:
            The stored bytes, or ``None`` if the key does not exist.
        """
        ...

    async def batch_put(self, items: list[tuple[bytes, bytes]]) -> None:
        """Atomically write a batch of key-value pairs.

        All pairs are applied as a single logical operation.  If the
        backend supports transactions, the batch is committed atomically.

        Args:
            items: A list of ``(key, value)`` pairs to write.
        """
        ...

    async def batch_delete(self, keys: list[bytes]) -> None:
        """Atomically delete a batch of keys.

        Missing keys are silently ignored.

        Args:
            keys: A list of keys to delete.
        """
        ...

    async def snapshot(self) -> SnapshotHandle:
        """Create a consistent point-in-time snapshot.

        The snapshot captures the current state so that concurrent
        readers see a stable view even as new writes are applied.

        Returns:
            An opaque :class:`SnapshotHandle` identifying this snapshot.
        """
        ...

    async def restore(self, handle: SnapshotHandle) -> None:
        """Restore state from a previously taken snapshot.

        All current state is replaced with the snapshot's contents.

        Args:
            handle: The handle returned by a prior :meth:`snapshot` call.

        Raises:
            KeyError: If the snapshot handle is unknown or expired.
        """
        ...
