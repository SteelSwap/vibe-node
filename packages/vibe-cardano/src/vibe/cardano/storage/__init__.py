"""vibe.cardano.storage — Cardano-specific storage backends.

This package provides high-performance storage implementations for the
Cardano node, built on top of the protocol-agnostic interfaces defined
in ``vibe.core.storage``.

Public API
----------
LedgerDB
    Arrow-backed UTxO state store with O(1) dict lookups, diff-based
    rollback, and IPC snapshot support.
"""

from .ledger import BlockDiff, ExceededRollbackError, LedgerDB

__all__ = [
    "BlockDiff",
    "ExceededRollbackError",
    "LedgerDB",
]
