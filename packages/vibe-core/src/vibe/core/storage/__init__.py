"""vibe.core.storage — Protocol-agnostic storage abstractions.

This package defines the storage interface contracts that concrete
backends implement.  Three protocols capture the distinct access
patterns of a blockchain node's storage subsystems:

- :class:`AppendStore` — append-only sequential storage (ImmutableDB)
- :class:`KeyValueStore` — mutable key-value storage (VolatileDB)
- :class:`StateStore` — batch state with snapshots (LedgerDB)

All interfaces operate on raw ``bytes`` keys and values.  Higher-level
code in ``vibe-cardano`` wraps these with typed serialization.

Public API
----------
AppendStore, KeyValueStore, StateStore, SnapshotHandle
    Core protocol interfaces from :mod:`~vibe.core.storage.interfaces`.
MemoryAppendStore, MemoryKeyValueStore, MemoryStateStore
    In-memory reference implementations from :mod:`~vibe.core.storage.memory`.
"""

from .interfaces import AppendStore, KeyValueStore, SnapshotHandle, StateStore
from .memory import MemoryAppendStore, MemoryKeyValueStore, MemoryStateStore

__all__ = [
    "AppendStore",
    "KeyValueStore",
    "MemoryAppendStore",
    "MemoryKeyValueStore",
    "MemoryStateStore",
    "SnapshotHandle",
    "StateStore",
]
