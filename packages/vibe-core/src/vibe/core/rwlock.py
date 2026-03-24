"""Read-write lock for thread-safe shared state access.

Multiple concurrent readers, exclusive writer. Matches the semantics
of Haskell STM TVars where multiple threads can read atomically but
writes are exclusive.

Usage:
    lock = RWLock()
    with lock.read():
        data = shared_state.read()
    with lock.write():
        shared_state.mutate()

Haskell reference:
    STM TVars provide atomic read/write with optimistic concurrency.
    Our RWLock uses pessimistic locking but achieves the same
    concurrency pattern: multiple readers, exclusive writer.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Generator

__all__ = ["RWLock"]


class RWLock:
    """Read-write lock. Multiple concurrent readers, exclusive writer.

    Write-preferring policy: when a writer is waiting, new readers
    block until the writer completes. This prevents writer starvation
    in high-read scenarios.

    Thread-safe. Works with Python's GIL (I/O-bound concurrency) and
    with free-threaded Python 3.13+ (true parallelism).
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers: int = 0
        self._writers_waiting: int = 0
        self._writer_active: bool = False

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        """Acquire read lock. Multiple readers can hold simultaneously.

        Blocks if a writer is active or waiting (write-preferring).
        """
        with self._cond:
            while self._writer_active or self._writers_waiting > 0:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        """Acquire write lock. Exclusive access, blocks all readers."""
        with self._cond:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                self._cond.wait()
            self._writers_waiting -= 1
            self._writer_active = True
        try:
            yield
        finally:
            with self._cond:
                self._writer_active = False
                self._cond.notify_all()
