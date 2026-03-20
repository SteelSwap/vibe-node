"""vibe.cardano.storage — Cardano-specific storage implementations.

This package contains the concrete storage backends for the three
subsystems of a Cardano node:

- :class:`ImmutableDB` — epoch-chunked append-only block storage
  (implements :class:`~vibe.core.storage.AppendStore`)

Haskell reference:
    ouroboros-consensus/src/ouroboros-consensus/Ouroboros/Consensus/Storage/
"""

from .immutable import ImmutableDB

__all__ = [
    "ImmutableDB",
]
