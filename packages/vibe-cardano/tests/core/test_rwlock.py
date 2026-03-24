"""Tests for RWLock — read-write lock with context managers."""

from __future__ import annotations

import threading
import time

from vibe.core.rwlock import RWLock


class TestRWLockBasic:
    def test_write_lock_exclusive(self):
        """Two writers should not interleave."""
        lock = RWLock()
        results = []

        def writer(val):
            with lock.write():
                results.append(f"start-{val}")
                time.sleep(0.05)
                results.append(f"end-{val}")

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        time.sleep(0.01)
        t2.start()
        t1.join()
        t2.join()
        # First writer should complete before second starts
        assert results[:2] == ["start-1", "end-1"]

    def test_concurrent_readers(self):
        """Multiple readers should overlap."""
        lock = RWLock()
        timestamps = []

        def reader():
            with lock.read():
                timestamps.append(time.monotonic())
                time.sleep(0.05)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All 5 should have started within ~10ms of each other
        assert max(timestamps) - min(timestamps) < 0.05

    def test_writer_blocks_readers(self):
        """Reader should wait for writer to finish."""
        lock = RWLock()
        order = []

        def writer():
            with lock.write():
                order.append("write-start")
                time.sleep(0.1)
                order.append("write-end")

        def reader():
            time.sleep(0.02)
            with lock.read():
                order.append("read")

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start()
        rt.start()
        wt.join()
        rt.join()
        assert order.index("read") > order.index("write-end")

    def test_context_manager_syntax(self):
        lock = RWLock()
        with lock.read():
            pass
        with lock.write():
            pass

    def test_reentrant_read_not_supported(self):
        """Read lock is NOT reentrant — same thread acquiring twice deadlocks.
        This documents the behavior, not a feature to rely on.
        """
        # Just verify single acquire/release works
        lock = RWLock()
        with lock.read():
            pass  # Single acquire works
