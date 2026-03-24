"""Memory tracking for leak detection in the vibe Cardano node.

Provides periodic RSS sampling into a fixed-size ring buffer, delta and
growth-rate calculations, and on-demand object-type profiling via the
``gc`` module.  Designed to feed Prometheus gauges and structured log
lines so operators can spot memory leaks early.

Haskell references:
    - Cardano.Node.Tracing.Tracers (GC / heap metrics)
    - Ouroboros.Consensus.Node (resource monitoring hooks)

Design notes:
    The Haskell node surfaces GHC RTS heap stats through ekg-core.  We
    mirror the intent -- continuous memory visibility -- using Python's
    ``resource`` module for RSS and ``gc.get_objects()`` for type-level
    profiling.  The ring buffer keeps a bounded history without unbounded
    allocation, and the async loop integrates with the existing metrics
    and structured-logging infrastructure.
"""

from __future__ import annotations

import collections
import gc
import resource
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging

    from .metrics import Gauge

__all__ = [
    "MemoryTracker",
    "run_memory_tracker",
]

# ---------------------------------------------------------------------------
# Platform-aware RSS helper
# ---------------------------------------------------------------------------

_IS_DARWIN = sys.platform == "darwin"


def _read_rss_bytes() -> int:
    """Return the current process RSS in bytes.

    ``resource.getrusage`` reports ``ru_maxrss`` in bytes on macOS and in
    kilobytes on Linux.  We normalise to bytes unconditionally.
    """
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if _IS_DARWIN:
        return ru.ru_maxrss  # already bytes
    return ru.ru_maxrss * 1024  # KB -> bytes


# ---------------------------------------------------------------------------
# Ring buffer
# ---------------------------------------------------------------------------


class _RingBuffer:
    """Fixed-capacity ring buffer backed by a flat list.

    Overwrites the oldest entry once full.  Supports ``len()`` and
    negative indexing (``buffer[-1]`` is the most recent entry).
    """

    __slots__ = ("_buf", "_capacity", "_pos", "_full")

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Ring buffer capacity must be >= 1")
        self._buf: list[int] = [0] * capacity
        self._capacity = capacity
        self._pos = 0
        self._full = False

    def append(self, value: int) -> None:
        self._buf[self._pos] = value
        self._pos = (self._pos + 1) % self._capacity
        if self._pos == 0 and not self._full:
            self._full = True

    def __len__(self) -> int:
        return self._capacity if self._full else self._pos

    def __getitem__(self, index: int) -> int:
        length = len(self)
        if length == 0:
            raise IndexError("ring buffer is empty")
        if index < -length or index >= length:
            raise IndexError(f"index {index} out of range for length {length}")
        if index < 0:
            index += length
        # The oldest element starts at self._pos when full, else at 0.
        start = self._pos if self._full else 0
        real = (start + index) % self._capacity
        return self._buf[real]


# ---------------------------------------------------------------------------
# MemoryTracker
# ---------------------------------------------------------------------------


class MemoryTracker:
    """Tracks RSS samples in a ring buffer for leak detection.

    Parameters:
        max_samples: Maximum number of samples retained (ring buffer size).
            Defaults to 3600 -- one hour at one sample per second.
    """

    def __init__(self, max_samples: int = 3600) -> None:
        self._ring = _RingBuffer(max_samples)
        self._last_rss: int = 0

    # -- Sampling -----------------------------------------------------------

    def sample(self) -> int:
        """Read current RSS, store it, and return the value in bytes."""
        rss = _read_rss_bytes()
        self._ring.append(rss)
        self._last_rss = rss
        return rss

    # -- Queries ------------------------------------------------------------

    def get_rss_bytes(self) -> int:
        """Return the most recently sampled RSS in bytes.

        Returns 0 if ``sample()`` has never been called.
        """
        return self._last_rss

    def get_delta_bytes(self) -> int:
        """Return the change in RSS between the two most recent samples.

        Returns 0 if fewer than two samples exist.
        """
        n = len(self._ring)
        if n < 2:
            return 0
        return self._ring[-1] - self._ring[-2]

    def get_growth_percent(self, window: int) -> float:
        """Return percentage growth over the last *window* samples.

        If fewer than *window* samples exist, uses all available samples.
        Returns 0.0 if fewer than two samples exist or the baseline is zero.
        """
        n = len(self._ring)
        if n < 2:
            return 0.0
        effective = min(window, n)
        baseline = self._ring[-effective]
        current = self._ring[-1]
        if baseline == 0:
            return 0.0
        return ((current - baseline) / baseline) * 100.0

    def get_top_types(self, n: int = 10) -> list[tuple[str, int]]:
        """Return the top *n* types by live-object count.

        This walks ``gc.get_objects()`` which is **expensive** -- call it
        sparingly (e.g. once per minute, or on operator demand).

        Returns a list of ``(type_name, count)`` pairs sorted descending.
        """
        counts: collections.Counter[str] = collections.Counter()
        for obj in gc.get_objects():
            counts[type(obj).__name__] += 1
        return counts.most_common(n)

    @property
    def sample_count(self) -> int:
        """Number of samples currently stored."""
        return len(self._ring)


# ---------------------------------------------------------------------------
# Async periodic loop
# ---------------------------------------------------------------------------


async def run_memory_tracker(
    tracker: MemoryTracker,
    interval_seconds: float,
    metrics: Gauge,
    logger: logging.Logger,
) -> None:
    """Periodically sample RSS, update a Prometheus gauge, and log.

    This coroutine runs until cancelled.  Designed to be launched as an
    ``asyncio.Task`` alongside the main node event loop.

    Parameters:
        tracker: The ``MemoryTracker`` instance to drive.
        interval_seconds: Seconds between samples.
        metrics: A ``Gauge`` (typically ``MEMORY_RSS``) to update.
        logger: Logger for INFO-level memory lines.
    """
    import asyncio

    while True:
        rss = tracker.sample()
        delta = tracker.get_delta_bytes()
        metrics.set(rss)

        logger.info(
            "memory_rss_bytes=%d delta_bytes=%d samples=%d",
            rss,
            delta,
            tracker.sample_count,
        )

        await asyncio.sleep(interval_seconds)
