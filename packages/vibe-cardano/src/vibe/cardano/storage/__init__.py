"""vibe.cardano.storage — Cardano-specific storage implementations.

- :class:`ChainDB` — coordinator for ImmutableDB, VolatileDB, and LedgerDB
- :class:`ImmutableDB` — epoch-chunked append-only block storage
- :class:`VolatileDB` — hash-indexed recent block storage
- :class:`LedgerDB` — Arrow-backed UTxO state store with diff-based rollback
"""

from .chaindb import ChainDB, ChainSelectionError
from .immutable import ImmutableDB
from .ledger import BlockDiff, ExceededRollbackError, LedgerDB
from .volatile import BlockInfo, VolatileDB

__all__ = [
    "BlockDiff",
    "BlockInfo",
    "ChainDB",
    "ChainSelectionError",
    "ExceededRollbackError",
    "ImmutableDB",
    "LedgerDB",
    "VolatileDB",
]
