"""Tests for resource limits -- memory monitor, FD tracker, volatile pruner.

Validates that:
- MemoryMonitor warns at the soft limit and triggers gc.collect()
- FDTracker counts file descriptors and warns near the OS limit
- VolatilePruner removes blocks beyond k depth from VolatileDB

These are unit tests using mocks for the OS-level resource queries so
they run reliably in CI regardless of actual memory/FD state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vibe.cardano.node.resource_limits import (
    FDTracker,
    MemoryMonitor,
    VolatilePruner,
)
from vibe.cardano.storage.volatile import VolatileDB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_rusage(rss_bytes: int):
    """Create a mock resource.getrusage return value with the given RSS."""
    import platform

    mock = MagicMock()
    if platform.system() == "Linux":
        mock.ru_maxrss = rss_bytes // 1024  # Linux reports KB
    else:
        mock.ru_maxrss = rss_bytes  # macOS reports bytes
    return mock


# ---------------------------------------------------------------------------
# MemoryMonitor tests
# ---------------------------------------------------------------------------


class TestMemoryMonitor:
    """Tests for MemoryMonitor."""

    def test_memory_monitor_warns_at_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """MemoryMonitor logs a warning when RSS >= soft_limit."""
        monitor = MemoryMonitor(soft_limit=1000, gc_threshold=0.80)
        with patch.object(MemoryMonitor, "_get_rss_bytes", return_value=1000):
            rss = monitor.check()

        assert rss == 1000
        assert any("memory pressure is HIGH" in r.message for r in caplog.records)

    def test_memory_monitor_triggers_gc(self) -> None:
        """MemoryMonitor calls gc.collect() when RSS >= gc_threshold * soft_limit."""
        monitor = MemoryMonitor(soft_limit=1000, gc_threshold=0.80)

        with (
            patch.object(MemoryMonitor, "_get_rss_bytes", return_value=850),
            patch("vibe.cardano.node.resource_limits.gc.collect", return_value=42) as mock_gc,
        ):
            rss = monitor.check()

        assert rss == 850
        mock_gc.assert_called_once()

    def test_memory_monitor_no_gc_below_threshold(self) -> None:
        """MemoryMonitor does NOT trigger gc when RSS is below gc_threshold."""
        monitor = MemoryMonitor(soft_limit=1000, gc_threshold=0.80)

        with (
            patch.object(MemoryMonitor, "_get_rss_bytes", return_value=700),
            patch("vibe.cardano.node.resource_limits.gc.collect") as mock_gc,
        ):
            rss = monitor.check()

        assert rss == 700
        mock_gc.assert_not_called()

    def test_memory_monitor_no_warning_below_limit(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning logged when RSS < soft_limit."""
        monitor = MemoryMonitor(soft_limit=1000, gc_threshold=0.80)
        with patch.object(MemoryMonitor, "_get_rss_bytes", return_value=500):
            monitor.check()

        assert not any("memory pressure is HIGH" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# FDTracker tests
# ---------------------------------------------------------------------------


class TestFDTracker:
    """Tests for FDTracker."""

    def test_fd_tracker_counts_fds(self) -> None:
        """FDTracker.count_fds returns a positive integer on any platform."""
        tracker = FDTracker()
        count = tracker.count_fds()
        # We should always have at least stdin/stdout/stderr open
        assert count >= 3

    def test_fd_tracker_warns_at_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """FDTracker warns when open FDs >= warn_threshold * RLIMIT_NOFILE."""
        tracker = FDTracker(warn_threshold=0.80)

        # Simulate: 90 FDs open out of a limit of 100
        with (
            patch("vibe.cardano.node.resource_limits.os.listdir", return_value=["0"] * 90),
            patch(
                "vibe.cardano.node.resource_limits.resource.getrlimit",
                return_value=(100, 100),
            ),
        ):
            count = tracker.check()

        assert count == 90
        assert any("open FDs >= warning threshold" in r.message for r in caplog.records)

    def test_fd_tracker_no_warning_below_threshold(self, caplog: pytest.LogCaptureFixture) -> None:
        """No warning when FD usage is below the threshold."""
        tracker = FDTracker(warn_threshold=0.80)

        with (
            patch("vibe.cardano.node.resource_limits.os.listdir", return_value=["0"] * 10),
            patch(
                "vibe.cardano.node.resource_limits.resource.getrlimit",
                return_value=(100, 100),
            ),
        ):
            tracker.check()

        assert not any("open FDs >= warning threshold" in r.message for r in caplog.records)

    def test_fd_tracker_handles_listdir_error(self) -> None:
        """FDTracker returns -1 gracefully when the FD directory is unreadable."""
        tracker = FDTracker()

        with patch(
            "vibe.cardano.node.resource_limits.os.listdir",
            side_effect=OSError("permission denied"),
        ):
            count = tracker.count_fds()

        assert count == -1


# ---------------------------------------------------------------------------
# VolatilePruner tests
# ---------------------------------------------------------------------------


class TestVolatilePruner:
    """Tests for VolatilePruner."""

    @pytest.mark.asyncio
    async def test_volatile_pruner_removes_old_blocks(self) -> None:
        """VolatilePruner removes blocks older than (tip_slot - k)."""
        vdb = VolatileDB()

        # Add blocks at slots 0..19 (20 blocks total)
        for i in range(20):
            block_hash = i.to_bytes(32, "big")
            pred_hash = (i - 1).to_bytes(32, "big") if i > 0 else b"\x00" * 32
            await vdb.add_block(
                block_hash=block_hash,
                slot=i * 10,  # slots 0, 10, 20, ..., 190
                predecessor_hash=pred_hash,
                block_number=i,
                cbor_bytes=b"block-" + str(i).encode(),
            )

        assert vdb.block_count == 20

        # Prune with k=5: immutable_slot = 190 - 5 = 185
        # Blocks with slot <= 185 should be removed (slots 0..180 = 19 blocks)
        # Only slot 190 (block 19) survives
        pruner = VolatilePruner(vdb, k=5)
        removed = await pruner.prune()

        assert removed == 19
        assert vdb.block_count == 1

    @pytest.mark.asyncio
    async def test_volatile_pruner_noop_when_empty(self) -> None:
        """VolatilePruner does nothing on an empty VolatileDB."""
        vdb = VolatileDB()
        pruner = VolatilePruner(vdb, k=10)
        removed = await pruner.prune()
        assert removed == 0

    @pytest.mark.asyncio
    async def test_volatile_pruner_noop_when_within_k(self) -> None:
        """VolatilePruner does nothing when all blocks are within k of tip."""
        vdb = VolatileDB()

        # Add 3 blocks at slots 0, 1, 2
        for i in range(3):
            block_hash = i.to_bytes(32, "big")
            pred_hash = (i - 1).to_bytes(32, "big") if i > 0 else b"\x00" * 32
            await vdb.add_block(
                block_hash=block_hash,
                slot=i,
                predecessor_hash=pred_hash,
                block_number=i,
                cbor_bytes=b"block",
            )

        # k=100 means immutable_slot = 2 - 100 = -98 < 0 => no pruning
        pruner = VolatilePruner(vdb, k=100)
        removed = await pruner.prune()
        assert removed == 0
        assert vdb.block_count == 3

    @pytest.mark.asyncio
    async def test_volatile_pruner_callable(self) -> None:
        """VolatilePruner works as a callable via __call__."""
        vdb = VolatileDB()
        pruner = VolatilePruner(vdb, k=10)
        # Should be callable and return 0 for empty DB
        result = await pruner()
        assert result == 0
