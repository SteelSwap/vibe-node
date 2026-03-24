"""Tests for vibe.core.storage — protocol interfaces and memory implementations.

Each test class exercises a memory implementation against the interface
contract to verify that:
  1. The implementation satisfies the Protocol structurally.
  2. The behavioral contracts (ordering, atomicity, snapshots) hold.
"""

from __future__ import annotations

import pytest

from vibe.core.storage.interfaces import (
    AppendStore,
    KeyValueStore,
    SnapshotHandle,
    StateStore,
)
from vibe.core.storage.memory import (
    MemoryAppendStore,
    MemoryKeyValueStore,
    MemoryStateStore,
)

# ---------------------------------------------------------------------------
# Protocol conformance — structural subtyping checks
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Verify that memory implementations satisfy the Protocol types."""

    def test_memory_append_store_is_append_store(self) -> None:
        assert isinstance(MemoryAppendStore(), AppendStore)

    def test_memory_kv_store_is_key_value_store(self) -> None:
        assert isinstance(MemoryKeyValueStore(), KeyValueStore)

    def test_memory_state_store_is_state_store(self) -> None:
        assert isinstance(MemoryStateStore(), StateStore)


# ---------------------------------------------------------------------------
# AppendStore contract tests
# ---------------------------------------------------------------------------


class TestAppendStore:
    """Test MemoryAppendStore against the AppendStore contract."""

    @pytest.fixture
    def store(self) -> MemoryAppendStore:
        return MemoryAppendStore()

    async def test_empty_store_tip_is_none(self, store: MemoryAppendStore) -> None:
        assert await store.get_tip() is None

    async def test_append_and_get(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"block-1")
        assert await store.get(b"\x01") == b"block-1"

    async def test_get_missing_key_returns_none(self, store: MemoryAppendStore) -> None:
        assert await store.get(b"\xff") is None

    async def test_tip_tracks_latest(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        await store.append(b"\x02", b"b")
        await store.append(b"\x03", b"c")
        assert await store.get_tip() == b"\x03"

    async def test_append_enforces_ordering(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x02", b"a")
        with pytest.raises(ValueError, match="greater than"):
            await store.append(b"\x01", b"b")

    async def test_append_rejects_duplicate_key(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        with pytest.raises(ValueError, match="greater than"):
            await store.append(b"\x01", b"b")

    async def test_iter_from_existing_key(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        await store.append(b"\x02", b"b")
        await store.append(b"\x03", b"c")

        result = [(k, v) async for k, v in store.iter_from(b"\x02")]
        assert result == [(b"\x02", b"b"), (b"\x03", b"c")]

    async def test_iter_from_missing_key_starts_at_next(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        await store.append(b"\x03", b"c")

        # Key b"\x02" doesn't exist — iteration starts at b"\x03".
        result = [(k, v) async for k, v in store.iter_from(b"\x02")]
        assert result == [(b"\x03", b"c")]

    async def test_iter_from_past_end_yields_nothing(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        result = [(k, v) async for k, v in store.iter_from(b"\xff")]
        assert result == []

    async def test_iter_from_beginning(self, store: MemoryAppendStore) -> None:
        await store.append(b"\x01", b"a")
        await store.append(b"\x02", b"b")

        result = [(k, v) async for k, v in store.iter_from(b"\x00")]
        assert result == [(b"\x01", b"a"), (b"\x02", b"b")]


# ---------------------------------------------------------------------------
# KeyValueStore contract tests
# ---------------------------------------------------------------------------


class TestKeyValueStore:
    """Test MemoryKeyValueStore against the KeyValueStore contract."""

    @pytest.fixture
    def store(self) -> MemoryKeyValueStore:
        return MemoryKeyValueStore()

    async def test_get_missing_returns_none(self, store: MemoryKeyValueStore) -> None:
        assert await store.get(b"nope") is None

    async def test_put_and_get(self, store: MemoryKeyValueStore) -> None:
        await store.put(b"k1", b"v1")
        assert await store.get(b"k1") == b"v1"

    async def test_put_overwrites(self, store: MemoryKeyValueStore) -> None:
        await store.put(b"k1", b"v1")
        await store.put(b"k1", b"v2")
        assert await store.get(b"k1") == b"v2"

    async def test_delete_existing(self, store: MemoryKeyValueStore) -> None:
        await store.put(b"k1", b"v1")
        assert await store.delete(b"k1") is True
        assert await store.get(b"k1") is None

    async def test_delete_missing_returns_false(self, store: MemoryKeyValueStore) -> None:
        assert await store.delete(b"nope") is False

    async def test_contains(self, store: MemoryKeyValueStore) -> None:
        await store.put(b"k1", b"v1")
        assert await store.contains(b"k1") is True
        assert await store.contains(b"k2") is False

    async def test_keys_empty(self, store: MemoryKeyValueStore) -> None:
        assert await store.keys() == []

    async def test_keys_returns_all(self, store: MemoryKeyValueStore) -> None:
        await store.put(b"a", b"1")
        await store.put(b"b", b"2")
        assert set(await store.keys()) == {b"a", b"b"}


# ---------------------------------------------------------------------------
# StateStore contract tests
# ---------------------------------------------------------------------------


class TestStateStore:
    """Test MemoryStateStore against the StateStore contract."""

    @pytest.fixture
    def store(self) -> MemoryStateStore:
        return MemoryStateStore()

    async def test_get_missing_returns_none(self, store: MemoryStateStore) -> None:
        assert await store.get(b"nope") is None

    async def test_batch_put_and_get(self, store: MemoryStateStore) -> None:
        await store.batch_put([(b"k1", b"v1"), (b"k2", b"v2")])
        assert await store.get(b"k1") == b"v1"
        assert await store.get(b"k2") == b"v2"

    async def test_batch_delete(self, store: MemoryStateStore) -> None:
        await store.batch_put([(b"k1", b"v1"), (b"k2", b"v2"), (b"k3", b"v3")])
        await store.batch_delete([b"k1", b"k3"])
        assert await store.get(b"k1") is None
        assert await store.get(b"k2") == b"v2"
        assert await store.get(b"k3") is None

    async def test_batch_delete_ignores_missing(self, store: MemoryStateStore) -> None:
        # Should not raise.
        await store.batch_delete([b"nonexistent"])

    async def test_snapshot_and_restore(self, store: MemoryStateStore) -> None:
        await store.batch_put([(b"k1", b"v1")])
        handle = await store.snapshot()

        # Mutate after snapshot.
        await store.batch_put([(b"k1", b"v2"), (b"k2", b"new")])
        assert await store.get(b"k1") == b"v2"

        # Restore brings back the snapshot state.
        await store.restore(handle)
        assert await store.get(b"k1") == b"v1"
        assert await store.get(b"k2") is None

    async def test_snapshot_handle_is_opaque(self, store: MemoryStateStore) -> None:
        handle = await store.snapshot()
        assert isinstance(handle, SnapshotHandle)
        assert isinstance(handle.snapshot_id, str)

    async def test_restore_unknown_handle_raises(self, store: MemoryStateStore) -> None:
        bogus = SnapshotHandle(snapshot_id="does-not-exist")
        with pytest.raises(KeyError, match="does-not-exist"):
            await store.restore(bogus)

    async def test_multiple_snapshots(self, store: MemoryStateStore) -> None:
        await store.batch_put([(b"k1", b"v1")])
        snap1 = await store.snapshot()

        await store.batch_put([(b"k1", b"v2")])
        snap2 = await store.snapshot()

        # Restore to snap1.
        await store.restore(snap1)
        assert await store.get(b"k1") == b"v1"

        # Restore to snap2.
        await store.restore(snap2)
        assert await store.get(b"k1") == b"v2"

    async def test_snapshot_is_isolated_from_mutations(self, store: MemoryStateStore) -> None:
        """Snapshot data must not be affected by subsequent writes."""
        await store.batch_put([(b"k1", b"v1")])
        handle = await store.snapshot()

        # Mutate heavily.
        await store.batch_put([(b"k1", b"changed")])
        await store.batch_delete([b"k1"])

        # Restore should give us the snapshot, not the mutations.
        await store.restore(handle)
        assert await store.get(b"k1") == b"v1"
