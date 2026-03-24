"""In-memory storage implementations for testing.

These are reference implementations of the storage protocols that keep
everything in Python dicts and lists.  They are used in unit tests and
for rapid prototyping — never in production, where we need durability.

Each implementation satisfies its corresponding Protocol structurally
(no explicit inheritance required), which validates that the Protocol
definitions are correct and implementable.
"""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator

from vibe.core.storage.interfaces import SnapshotHandle

__all__ = [
    "MemoryAppendStore",
    "MemoryKeyValueStore",
    "MemoryStateStore",
]


class MemoryAppendStore:
    """In-memory :class:`~vibe.core.storage.interfaces.AppendStore`.

    Stores entries in an ordered list with a dict index for O(1) lookups.
    Enforces monotonically increasing keys on append.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[bytes, bytes]] = []
        self._index: dict[bytes, int] = {}

    async def append(self, key: bytes, value: bytes) -> None:
        """Append a key-value pair, enforcing sequential ordering."""
        if self._entries and key <= self._entries[-1][0]:
            msg = f"Key must be greater than the current tip: {key!r} <= {self._entries[-1][0]!r}"
            raise ValueError(msg)
        self._index[key] = len(self._entries)
        self._entries.append((key, value))

    async def get(self, key: bytes) -> bytes | None:
        """Look up by key."""
        idx = self._index.get(key)
        if idx is None:
            return None
        return self._entries[idx][1]

    async def get_tip(self) -> bytes | None:
        """Return the latest appended key."""
        if not self._entries:
            return None
        return self._entries[-1][0]

    async def iter_from(self, start_key: bytes) -> AsyncIterator[tuple[bytes, bytes]]:
        """Iterate from *start_key* (inclusive) forward."""
        # Binary search for the start position.
        start_idx = self._find_start(start_key)
        for i in range(start_idx, len(self._entries)):
            yield self._entries[i]

    def _find_start(self, start_key: bytes) -> int:
        """Find the first index >= start_key via binary search."""
        lo, hi = 0, len(self._entries)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._entries[mid][0] < start_key:
                lo = mid + 1
            else:
                hi = mid
        return lo


class MemoryKeyValueStore:
    """In-memory :class:`~vibe.core.storage.interfaces.KeyValueStore`.

    Simple dict-backed implementation.
    """

    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}

    async def get(self, key: bytes) -> bytes | None:
        """Look up by key."""
        return self._data.get(key)

    async def put(self, key: bytes, value: bytes) -> None:
        """Store a key-value pair."""
        self._data[key] = value

    async def delete(self, key: bytes) -> bool:
        """Delete a key, returning whether it existed."""
        try:
            del self._data[key]
        except KeyError:
            return False
        return True

    async def contains(self, key: bytes) -> bool:
        """Check key existence."""
        return key in self._data

    async def keys(self) -> list[bytes]:
        """Return all keys."""
        return list(self._data.keys())


class MemoryStateStore:
    """In-memory :class:`~vibe.core.storage.interfaces.StateStore`.

    Dict-backed with snapshot support via deep-copying the state.
    """

    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}
        self._snapshots: dict[str, dict[bytes, bytes]] = {}
        self._next_snapshot_id: int = 0

    async def get(self, key: bytes) -> bytes | None:
        """Point lookup."""
        return self._data.get(key)

    async def batch_put(self, items: list[tuple[bytes, bytes]]) -> None:
        """Batch write."""
        for k, v in items:
            self._data[k] = v

    async def batch_delete(self, keys: list[bytes]) -> None:
        """Batch delete, silently ignoring missing keys."""
        for k in keys:
            self._data.pop(k, None)

    async def snapshot(self) -> SnapshotHandle:
        """Snapshot current state by deep-copying."""
        sid = str(self._next_snapshot_id)
        self._next_snapshot_id += 1
        self._snapshots[sid] = copy.deepcopy(self._data)
        return SnapshotHandle(snapshot_id=sid)

    async def restore(self, handle: SnapshotHandle) -> None:
        """Restore from a snapshot, replacing current state."""
        if handle.snapshot_id not in self._snapshots:
            msg = f"Unknown snapshot: {handle.snapshot_id!r}"
            raise KeyError(msg)
        self._data = copy.deepcopy(self._snapshots[handle.snapshot_id])
