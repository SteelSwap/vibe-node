"""Resource limits -- memory monitoring, FD tracking, volatile pruning.

Production Cardano nodes run for days or weeks without restart.  Without
active resource monitoring the process can silently bloat until the OOM
killer intervenes -- which is indistinguishable from a crash and violates
the "recover from power-loss" acceptance criterion.

This module provides three lightweight resource guards:

* **MemoryMonitor** -- tracks RSS via ``resource.getrusage``, triggers
  ``gc.collect()`` when usage exceeds a configurable fraction of the
  soft limit, and logs warnings so operators notice before things go
  sideways.

* **FDTracker** -- counts open file descriptors (via ``/dev/fd`` on
  macOS or ``/proc/self/fd`` on Linux) and warns when usage approaches
  the RLIMIT_NOFILE soft limit.

* **VolatilePruner** -- callable that prunes VolatileDB blocks beyond
  *k* depth, preventing the volatile store from growing without bound
  during long sync runs.

Haskell reference:
    The Haskell node uses GHC RTS options (-M, -H) and the
    ``Ouroboros.Consensus.Storage.VolatileDB.Impl.garbageCollect``
    function for volatile pruning.  Our MemoryMonitor and FDTracker
    have no direct Haskell analogue -- they're a Python-specific
    necessity since we lack the GHC RTS memory manager.
"""

from __future__ import annotations

import gc
import logging
import os
import platform
import resource
from dataclasses import dataclass

from vibe.cardano.storage.volatile import VolatileDB

__all__ = ["FDTracker", "MemoryMonitor", "VolatilePruner"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ONE_GB = 1024 * 1024 * 1024

# Default soft limit: 4 GB RSS
DEFAULT_MEMORY_SOFT_LIMIT: int = 4 * _ONE_GB

# Fraction of the soft limit at which gc.collect() is triggered
DEFAULT_GC_THRESHOLD: float = 0.80

# Fraction of RLIMIT_NOFILE at which FD warnings fire
DEFAULT_FD_WARN_THRESHOLD: float = 0.80


# ---------------------------------------------------------------------------
# MemoryMonitor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MemoryMonitor:
    """Track RSS and trigger gc/warnings at configurable thresholds.

    Uses ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` which reports
    the peak resident set size.  On macOS the unit is bytes; on Linux
    it is kilobytes -- we normalise to bytes internally.

    Attributes:
        soft_limit: RSS threshold in bytes for warning (default 4 GB).
        gc_threshold: Fraction of soft_limit at which ``gc.collect()``
            is triggered (default 0.80).
    """

    soft_limit: int = DEFAULT_MEMORY_SOFT_LIMIT
    gc_threshold: float = DEFAULT_GC_THRESHOLD

    def _get_rss_bytes(self) -> int:
        """Return current max RSS in bytes.

        ``ru_maxrss`` is in bytes on macOS and kilobytes on Linux.
        """
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = usage.ru_maxrss
        if platform.system() == "Linux":
            rss *= 1024  # KB -> bytes
        return rss

    def check(self) -> int:
        """Check current memory usage and take action if needed.

        Returns:
            Current RSS in bytes.

        Side effects:
            - Calls ``gc.collect()`` if RSS >= gc_threshold * soft_limit.
            - Logs a warning if RSS >= soft_limit.
        """
        rss = self._get_rss_bytes()
        gc_trigger = int(self.soft_limit * self.gc_threshold)

        if rss >= gc_trigger:
            collected = gc.collect()
            logger.info(
                "MemoryMonitor: RSS %d bytes >= gc threshold %d bytes "
                "(%.0f%% of %d limit), collected %d objects",
                rss,
                gc_trigger,
                100 * rss / self.soft_limit,
                self.soft_limit,
                collected,
            )

        if rss >= self.soft_limit:
            logger.warning(
                "MemoryMonitor: RSS %d bytes >= soft limit %d bytes -- memory pressure is HIGH",
                rss,
                self.soft_limit,
            )

        return rss


# ---------------------------------------------------------------------------
# FDTracker
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FDTracker:
    """Track open file descriptors and warn near the OS limit.

    Counts FDs via ``/dev/fd`` (macOS) or ``/proc/self/fd`` (Linux).
    Falls back to ``/dev/fd`` if neither exists (best effort).

    Attributes:
        warn_threshold: Fraction of RLIMIT_NOFILE soft limit at which
            a warning is logged (default 0.80).
    """

    warn_threshold: float = DEFAULT_FD_WARN_THRESHOLD

    def _get_fd_dir(self) -> str:
        """Return the filesystem path that lists open FDs."""
        if os.path.isdir("/proc/self/fd"):
            return "/proc/self/fd"
        return "/dev/fd"

    def _get_fd_limit(self) -> int:
        """Return the soft RLIMIT_NOFILE."""
        soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return soft

    def count_fds(self) -> int:
        """Return the number of currently open file descriptors."""
        fd_dir = self._get_fd_dir()
        try:
            # Each entry in the FD directory is a symlink to the open file.
            # Subtract 1 for the directory FD opened by listdir itself,
            # but in practice this is negligible -- keep it simple.
            return len(os.listdir(fd_dir))
        except OSError:
            logger.debug("FDTracker: cannot list %s", fd_dir)
            return -1

    def check(self) -> int:
        """Check current FD usage and warn if near the limit.

        Returns:
            Current open FD count (or -1 on error).

        Side effects:
            - Logs a warning if count >= warn_threshold * soft_limit.
        """
        count = self.count_fds()
        if count < 0:
            return count

        limit = self._get_fd_limit()
        warn_at = int(limit * self.warn_threshold)

        if count >= warn_at:
            logger.warning(
                "FDTracker: %d open FDs >= warning threshold %d (%.0f%% of %d limit)",
                count,
                warn_at,
                100 * count / limit if limit > 0 else 0,
                limit,
            )

        return count


# ---------------------------------------------------------------------------
# VolatilePruner
# ---------------------------------------------------------------------------


class VolatilePruner:
    """Prune VolatileDB blocks beyond *k* depth.

    Wraps :meth:`VolatileDB.gc` with a simple callable interface that
    can be invoked periodically (e.g., from the slot clock loop or a
    background task).

    Haskell reference:
        Ouroboros.Consensus.Storage.VolatileDB.Impl.garbageCollect
        Called from copyToImmutableDB when the chain grows past k.

    Args:
        volatile_db: The volatile block store to prune.
        k: Security parameter -- blocks older than (tip - k) slots
            are eligible for removal.
    """

    def __init__(self, volatile_db: VolatileDB, k: int = 2160) -> None:
        self._volatile_db = volatile_db
        self._k = k

    async def prune(self) -> int:
        """Remove blocks that are deeper than k below the current tip.

        Computes the immutable slot threshold as (max_slot - k) and
        delegates to :meth:`VolatileDB.gc`.

        Returns:
            Number of blocks removed.
        """
        max_slot = self._volatile_db.get_max_slot()
        if max_slot < 0:
            return 0

        immutable_slot = max_slot - self._k
        if immutable_slot < 0:
            return 0

        removed = self._volatile_db.gc(immutable_slot)
        if removed > 0:
            logger.info(
                "VolatilePruner: pruned %d blocks at or below slot %d (tip slot %d, k=%d)",
                removed,
                immutable_slot,
                max_slot,
                self._k,
            )
        return removed

    async def __call__(self) -> int:
        """Allow using the pruner as a simple callable."""
        return await self.prune()
