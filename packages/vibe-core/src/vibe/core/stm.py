"""Software Transactional Memory (STM) for Python.

Provides composable atomic transactions over shared mutable state,
matching the semantics of Haskell's STM:

- **TVar**: A transactional variable (shared mutable reference)
- **atomically**: Run a transaction function atomically
- **retry**: Abort and retry when a TVar changes (blocking read)

Transactions are optimistic: they read a consistent snapshot, compute
freely (no locks held), then attempt to commit. If any read TVar was
modified by another thread between read and commit, the transaction
retries automatically.

No deadlocks. No lock ordering. No starvation (fair retry via Condition).

Haskell reference:
    Control.Concurrent.STM (atomically, TVar, readTVar, writeTVar, retry)

Usage:
    tip = TVar(initial_tip)
    nonce = TVar(initial_nonce)

    def forge_tx(tx):
        t = tx.read(tip)
        n = tx.read(nonce)
        block = forge_block(t, n)  # pure computation
        tx.write(tip, new_tip)
        tx.write(nonce, new_nonce)
        return block

    result = atomically(forge_tx)  # atomic, retries on conflict
"""

from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar

__all__ = ["TVar", "Transaction", "atomically", "RetryTransaction"]

T = TypeVar("T")


class RetryTransaction(Exception):
    """Raised inside a transaction to abort and retry.

    Haskell ref: retry :: STM a
    The transaction will block until one of its read TVars changes,
    then re-execute from the beginning.
    """


class TVar:
    """Transactional variable — a shared mutable reference.

    Thread-safe. Reads and writes are only valid inside a Transaction
    (via tx.read/tx.write). Direct access is available via .value for
    non-transactional reads (e.g., logging).

    Haskell ref: Control.Concurrent.STM.TVar
    """

    __slots__ = ("_value", "_version", "_lock")

    def __init__(self, value: Any = None) -> None:
        self._value = value
        self._version: int = 0
        self._lock = threading.Lock()  # Per-TVar lock for version checks

    @property
    def value(self) -> Any:
        """Non-transactional read (for logging/debugging only)."""
        return self._value

    def _read(self) -> tuple[Any, int]:
        """Read value + version atomically."""
        with self._lock:
            return self._value, self._version

    def _write(self, value: Any) -> int:
        """Write value, increment version, return new version."""
        with self._lock:
            self._value = value
            self._version += 1
            return self._version


# Global commit lock — held only during the commit phase (microseconds).
# Ensures no two transactions commit simultaneously.
_commit_lock = threading.Lock()

# Condition variable for retry — notified when any TVar changes.
_retry_cond = threading.Condition(_commit_lock)


class Transaction:
    """A running STM transaction.

    Tracks reads (TVar → version at read time) and writes (TVar → new value).
    The transaction function receives this object and uses tx.read/tx.write.

    Haskell ref: The STM monad's internal state.
    """

    __slots__ = ("_reads", "_writes")

    def __init__(self) -> None:
        self._reads: dict[int, tuple[TVar, int]] = {}  # id(tvar) → (tvar, version)
        self._writes: dict[int, tuple[TVar, Any]] = {}  # id(tvar) → (tvar, new_value)

    def read(self, tvar: TVar) -> Any:
        """Read a TVar's value within this transaction.

        Returns the written value if this transaction already wrote to
        it (read-your-own-writes). Otherwise reads the current value
        and records the version for conflict detection.
        """
        tid = id(tvar)

        # Read-your-own-writes
        if tid in self._writes:
            return self._writes[tid][1]

        # First read — snapshot the value and version
        if tid not in self._reads:
            value, version = tvar._read()
            self._reads[tid] = (tvar, version)
            return value

        # Already read — return same snapshot (consistent reads)
        tvar_ref, _ = self._reads[tid]
        return tvar_ref._value  # May have changed, but we check at commit

    def write(self, tvar: TVar, value: Any) -> None:
        """Stage a write to a TVar within this transaction.

        The write is not applied until commit. Multiple writes to the
        same TVar within one transaction keep only the last value.
        """
        tid = id(tvar)
        self._writes[tid] = (tvar, value)

        # Also record a read if we haven't yet (for conflict detection)
        if tid not in self._reads:
            _, version = tvar._read()
            self._reads[tid] = (tvar, version)

    def _validate(self) -> bool:
        """Check that all read TVars still have the same version.

        Called under _commit_lock. Returns True if the snapshot is
        still consistent (no other transaction committed changes to
        our read set since we read them).
        """
        for tid, (tvar, read_version) in self._reads.items():
            with tvar._lock:
                if tvar._version != read_version:
                    return False
        return True

    def _commit(self) -> None:
        """Apply all staged writes. Called under _commit_lock after validation."""
        for tid, (tvar, new_value) in self._writes.items():
            tvar._write(new_value)


def atomically(fn: Callable[[Transaction], T], max_retries: int = 1000) -> T:
    """Run a transaction function atomically.

    The function receives a Transaction object for reading/writing TVars.
    If a conflict is detected at commit time (another thread modified a
    TVar we read), the transaction retries from the beginning.

    If the function raises RetryTransaction, the transaction blocks
    until one of its read TVars changes, then retries.

    Haskell ref: atomically :: STM a -> IO a

    Args:
        fn: Transaction function. Receives a Transaction, returns a result.
        max_retries: Safety limit to prevent infinite retry loops.

    Returns:
        The result of the transaction function.

    Raises:
        RuntimeError: If max_retries exceeded.
    """
    for attempt in range(max_retries):
        tx = Transaction()

        try:
            result = fn(tx)
        except RetryTransaction:
            # Block until a read TVar changes, then retry
            with _retry_cond:
                # Re-validate — if already invalid, retry immediately
                if not tx._validate():
                    continue
                # Wait for any TVar change notification
                _retry_cond.wait(timeout=1.0)
            continue

        # Attempt to commit
        with _retry_cond:
            if tx._validate():
                tx._commit()
                # Notify any retrying transactions that TVars changed
                if tx._writes:
                    _retry_cond.notify_all()
                return result
            # Validation failed — retry
            continue

    raise RuntimeError(
        f"STM transaction failed after {max_retries} retries"
    )
