"""Mempool types — data structures for transaction staging and ordering.

Haskell reference:
    Ouroboros.Consensus.Mempool.API (MempoolSnapshot, TxTicket)
    Ouroboros.Consensus.Mempool.TxSeq (TxTicket, TxMeasure)
    Ouroboros.Consensus.Mempool.Impl.Types (InternalState)

These types are intentionally kept simple and immutable (frozen dataclasses)
to minimise allocation overhead. The mempool must be lean — every byte
matters when we're competing against a mature Haskell implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TxMeasure:
    """Size measurement for a transaction, used for capacity tracking.

    Haskell reference:
        Ouroboros.Consensus.Mempool.TxSeq.TxMeasure
        In the Haskell node this is a monoid that tracks both byte size
        and execution units. We start with byte size only — ExUnit
        tracking can be added when we implement Alonzo script budget
        enforcement in the mempool.
    """

    size_bytes: int
    """Serialized CBOR size in bytes."""


@dataclass(frozen=True, slots=True)
class ValidatedTx:
    """A transaction that has passed mempool validation.

    This is the mempool's internal representation of a transaction that
    has been validated against the cached ledger state. It caches the
    tx_id and size to avoid recomputation.

    Haskell reference:
        Ouroboros.Consensus.Mempool.API.Validated (tx)
    """

    tx_cbor: bytes
    """Raw CBOR-encoded transaction bytes."""

    tx_id: bytes
    """Transaction hash (32 bytes, Blake2b-256 of the tx body)."""

    tx_size: int
    """Serialized size in bytes (len of tx_cbor)."""


@dataclass(frozen=True, slots=True)
class TxTicket:
    """A validated transaction with a monotonic ticket number for ordering.

    Ticket numbers are assigned at insertion time and never change. They
    provide a total order over mempool transactions that is stable across
    re-validations (transactions keep their original ticket number even
    after a tip change re-validation pass).

    Haskell reference:
        Ouroboros.Consensus.Mempool.TxSeq.TxTicket
        data TxTicket tx = TxTicket !tx !TicketNo !TxMeasure
    """

    validated_tx: ValidatedTx
    """The validated transaction."""

    ticket_no: int
    """Monotonic ticket number (insertion order)."""

    measure: TxMeasure
    """Size measurement for capacity tracking."""


@dataclass(frozen=True, slots=True)
class MempoolSnapshot:
    """An atomic point-in-time snapshot of the mempool contents.

    Snapshots are cheap to create (just a list copy + metadata) and
    provide a consistent view for consumers like the block forger and
    tx-submission server.

    Haskell reference:
        Ouroboros.Consensus.Mempool.API.MempoolSnapshot
    """

    tickets: list[TxTicket]
    """Ordered list of transaction tickets (by ticket_no)."""

    slot: int
    """Slot number of the ledger state the mempool was validated against."""

    total_size_bytes: int
    """Total size of all transactions in the snapshot, in bytes."""

    capacity_bytes: int
    """Maximum capacity of the mempool in bytes."""


@dataclass(frozen=True, slots=True)
class MempoolConfig:
    """Configuration for the mempool.

    Haskell reference:
        Ouroboros.Consensus.Mempool.Impl.Types.MempoolCapacityBytesOverride
        Default capacity = 2 * maxBlockBodySize from protocol parameters.

    Attributes:
        capacity_bytes: Maximum total size of mempool transactions in bytes.
            Default is 2 * 90112 = 180224 (2 * Babbage maxBlockBodySize).
            This can be overridden, but the Haskell node uses 2x as the
            default multiplier.
        tx_timeout_slots: Number of slots after which a tx is considered
            expired and eligible for eviction. None means no timeout.
            The Haskell node doesn't have an explicit timeout — it relies
            on TTL in the tx body. We add this as a safety net for txs
            without TTL or with very long TTL.
    """

    capacity_bytes: int = 2 * 90112
    """Maximum mempool size in CBOR bytes. Default: 2 * maxBlockBodySize."""

    tx_timeout_slots: int | None = None
    """Optional slot-based timeout for transaction eviction. None = no timeout."""
