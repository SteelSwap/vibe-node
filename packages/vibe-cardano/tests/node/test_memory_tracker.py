"""Tests for vibe.cardano.node.memory_tracker -- RSS sampling and leak detection."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import patch

import pytest

from vibe.cardano.node.memory_tracker import MemoryTracker, _RingBuffer, run_memory_tracker
from vibe.cardano.node.metrics import Gauge

# ---------------------------------------------------------------------------
# Ring buffer unit tests
# ---------------------------------------------------------------------------


class TestRingBuffer:
    def test_ring_buffer_basic(self) -> None:
        rb = _RingBuffer(3)
        assert len(rb) == 0
        rb.append(10)
        assert len(rb) == 1
        assert rb[0] == 10
        assert rb[-1] == 10

    def test_ring_buffer_wraps(self) -> None:
        """After exceeding capacity, oldest entries are overwritten."""
        rb = _RingBuffer(3)
        for v in [10, 20, 30, 40, 50]:
            rb.append(v)
        # Capacity is 3, so only the last 3 survive: 30, 40, 50
        assert len(rb) == 3
        assert rb[0] == 30
        assert rb[1] == 40
        assert rb[2] == 50
        assert rb[-1] == 50
        assert rb[-3] == 30

    def test_ring_buffer_index_error(self) -> None:
        rb = _RingBuffer(3)
        with pytest.raises(IndexError):
            _ = rb[0]
        rb.append(1)
        with pytest.raises(IndexError):
            _ = rb[1]
        with pytest.raises(IndexError):
            _ = rb[-2]


# ---------------------------------------------------------------------------
# MemoryTracker tests
# ---------------------------------------------------------------------------


class TestMemoryTracker:
    def test_sample_records_rss(self) -> None:
        """sample() should record a non-zero RSS value."""
        tracker = MemoryTracker(max_samples=10)
        rss = tracker.sample()
        assert rss > 0
        assert tracker.get_rss_bytes() == rss
        assert tracker.sample_count == 1

    def test_delta_after_allocation(self) -> None:
        """Delta reflects the change between consecutive samples."""
        tracker = MemoryTracker(max_samples=10)

        # Use controlled values via patching to get predictable deltas
        with patch("vibe.cardano.node.memory_tracker._read_rss_bytes", side_effect=[1000, 2500]):
            tracker.sample()
            tracker.sample()

        assert tracker.get_delta_bytes() == 1500

    def test_delta_with_single_sample(self) -> None:
        """Delta should be 0 when only one sample exists."""
        tracker = MemoryTracker(max_samples=10)
        tracker.sample()
        assert tracker.get_delta_bytes() == 0

    def test_growth_percent_over_window(self) -> None:
        """Growth percent calculated correctly over a window of samples."""
        tracker = MemoryTracker(max_samples=100)

        # Feed controlled RSS values: 1000 -> 1100 -> 1200 -> 1500
        values = [1000, 1100, 1200, 1500]
        with patch("vibe.cardano.node.memory_tracker._read_rss_bytes", side_effect=values):
            for _ in values:
                tracker.sample()

        # Over the full 4-sample window: (1500 - 1000) / 1000 * 100 = 50.0%
        assert tracker.get_growth_percent(4) == pytest.approx(50.0)

        # Over a 2-sample window: (1500 - 1200) / 1200 * 100 = 25.0%
        assert tracker.get_growth_percent(2) == pytest.approx(25.0)

    def test_growth_percent_insufficient_samples(self) -> None:
        """Growth percent returns 0.0 with fewer than 2 samples."""
        tracker = MemoryTracker(max_samples=10)
        assert tracker.get_growth_percent(10) == 0.0
        tracker.sample()
        assert tracker.get_growth_percent(10) == 0.0

    def test_top_types_returns_sorted_list(self) -> None:
        """get_top_types returns a non-empty list of (type_name, count) sorted descending."""
        tracker = MemoryTracker(max_samples=10)
        top = tracker.get_top_types(5)

        # We're running in a real Python process, so there will always be objects.
        assert len(top) > 0
        assert len(top) <= 5

        # Each entry is (str, int)
        for name, count in top:
            assert isinstance(name, str)
            assert isinstance(count, int)
            assert count > 0

        # Sorted descending by count
        counts = [c for _, c in top]
        assert counts == sorted(counts, reverse=True)

    def test_ring_buffer_wraps_in_tracker(self) -> None:
        """MemoryTracker ring buffer correctly wraps, keeping only max_samples entries."""
        tracker = MemoryTracker(max_samples=3)

        values = [100, 200, 300, 400, 500]
        with patch("vibe.cardano.node.memory_tracker._read_rss_bytes", side_effect=values):
            for _ in values:
                tracker.sample()

        assert tracker.sample_count == 3
        # Most recent value should be the last one sampled
        assert tracker.get_rss_bytes() == 500
        # Delta should be between the last two: 500 - 400 = 100
        assert tracker.get_delta_bytes() == 100


# ---------------------------------------------------------------------------
# Async loop test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_memory_tracker_loop() -> None:
    """run_memory_tracker samples, updates gauge, and logs at interval."""
    tracker = MemoryTracker(max_samples=100)
    gauge = Gauge("test_memory_rss_bytes", "Test RSS gauge")
    logger = logging.getLogger("test_memory_tracker")

    # Run for a short burst then cancel
    task = asyncio.create_task(
        run_memory_tracker(tracker, interval_seconds=0.05, metrics=gauge, logger=logger)
    )

    # Let it run a few iterations
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Should have taken multiple samples
    assert tracker.sample_count >= 2
    # Gauge should have been updated with the RSS
    assert gauge.value > 0
    assert gauge.value == tracker.get_rss_bytes()
