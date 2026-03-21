"""Core mempool implementation — transaction staging with validation.

The mempool is the staging area for transactions between the network layer
(tx-submission miniprotocol) and the block forger. It:

1. Validates incoming transactions against a cached ledger state
2. Tracks transactions with monotonic ticket numbers for ordering
3. Enforces capacity limits (total CBOR bytes <= 2 * maxBlockBodySize)
4. Re-validates all transactions when the chain tip changes
5. Provides atomic snapshots for the block forger and tx-submission server

Thread safety: all mutations are protected by an asyncio.Lock to support
concurrent access from multiple tx-submission clients and the block forger.

Haskell reference:
    Ouroboros.Consensus.Mempool.Impl.Common (implTryAddTx, implRemoveTxs)
    Ouroboros.Consensus.Mempool.Impl.Pure (pureRemoveTxs, pureSyncWithLedger)
    Ouroboros.Consensus.Mempool.TxSeq (TxSeq, appendTx, removeTxs)

Spec reference:
    Ouroboros consensus spec, Section "Mempool" — describes the mempool
    as a pure function from (ledger state, tx) -> (ledger state', [error])
    with re-validation on every tip change.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Callable, Protocol

from vibe.cardano.mempool.types import (
    MempoolConfig,
    MempoolSnapshot,
    TxMeasure,
    TxTicket,
    ValidatedTx,
)

__all__ = ["Mempool", "TxValidator"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validator protocol (structural typing)
# ---------------------------------------------------------------------------


class TxValidator(Protocol):
    """Protocol for transaction validation against a ledger state.

    The mempool uses this to validate transactions without being coupled
    to a specific ledger era. Implementors must provide a validate method
    that checks a raw CBOR transaction against the current UTxO state.

    The validate method returns a list of error strings — empty means valid.
    """

    def validate_tx(
        self,
        tx_cbor: bytes,
        current_slot: int,
    ) -> list[str]:
        """Validate a transaction against the current ledger state.

        Args:
            tx_cbor: Raw CBOR-encoded transaction bytes.
            current_slot: Current slot number for TTL/validity checks.

        Returns:
            List of validation error strings. Empty list means valid.
        """
        ...

    def apply_tx(
        self,
        tx_cbor: bytes,
        current_slot: int,
    ) -> None:
        """Apply a validated transaction to the cached ledger state.

        This updates the internal UTxO state so subsequent validations
        see the effects of this transaction. Must only be called after
        validate_tx returns no errors.

        Args:
            tx_cbor: Raw CBOR-encoded transaction bytes.
            current_slot: Current slot number.
        """
        ...

    def snapshot_state(self) -> Any:
        """Return an opaque snapshot of the current ledger state.

        Used to save/restore state during re-validation.
        """
        ...

    def restore_state(self, state: Any) -> None:
        """Restore the ledger state from a prior snapshot.

        Args:
            state: The opaque state object from snapshot_state().
        """
        ...


# ---------------------------------------------------------------------------
# Mempool
# ---------------------------------------------------------------------------


class Mempool:
    """Transaction mempool with validation, capacity management, and re-validation.

    The mempool maintains an ordered sequence of validated transactions,
    indexed by monotonic ticket numbers. It supports:

    - **add_tx**: Validate and add a transaction
    - **remove_txs**: Remove transactions by ID (after block inclusion)
    - **get_snapshot**: Atomic snapshot of current contents
    - **sync_with_ledger**: Re-validate all txs against new ledger state
    - **get_txs_for_block**: Select transactions for block forging

    Haskell reference:
        Ouroboros.Consensus.Mempool.API (Mempool type class)
        Ouroboros.Consensus.Mempool.Impl.Common (MempoolEnv, implTryAddTx)

    Args:
        config: Mempool configuration (capacity, etc.)
        validator: Transaction validator implementing TxValidator protocol.
        current_slot: Initial slot number for validation.
    """

    __slots__ = (
        "_config",
        "_validator",
        "_current_slot",
        "_tickets",
        "_tx_index",
        "_total_size",
        "_next_ticket_no",
        "_lock",
    )

    def __init__(
        self,
        config: MempoolConfig,
        validator: TxValidator,
        current_slot: int = 0,
    ) -> None:
        self._config = config
        self._validator = validator
        self._current_slot = current_slot

        # Ordered sequence of transaction tickets.
        # We use a list and maintain insertion order via ticket_no.
        self._tickets: list[TxTicket] = []

        # Index: tx_id -> TxTicket for O(1) lookup by ID.
        self._tx_index: dict[bytes, TxTicket] = {}

        # Running total of transaction sizes in bytes.
        self._total_size: int = 0

        # Monotonic ticket counter — never decremented, never reused.
        self._next_ticket_no: int = 0

        # Mutex for all mutations.
        self._lock = asyncio.Lock()

    # -- Properties ----------------------------------------------------------

    @property
    def config(self) -> MempoolConfig:
        """The mempool configuration."""
        return self._config

    @property
    def current_slot(self) -> int:
        """The slot number the mempool was last validated against."""
        return self._current_slot

    @property
    def size(self) -> int:
        """Number of transactions currently in the mempool."""
        return len(self._tickets)

    @property
    def total_size_bytes(self) -> int:
        """Total size of all mempool transactions in CBOR bytes."""
        return self._total_size

    @property
    def capacity_bytes(self) -> int:
        """Maximum capacity in CBOR bytes."""
        return self._config.capacity_bytes

    @property
    def available_bytes(self) -> int:
        """Remaining capacity in CBOR bytes."""
        return max(0, self._config.capacity_bytes - self._total_size)

    # -- Core operations -----------------------------------------------------

    async def add_tx(self, tx_cbor: bytes) -> ValidatedTx:
        """Validate and add a transaction to the mempool.

        The transaction is validated against the cached ledger state
        (which includes the effects of all existing mempool transactions).
        If valid and there is sufficient capacity, it is added and assigned
        a ticket number.

        Haskell reference:
            Ouroboros.Consensus.Mempool.Impl.Common.implTryAddTx
            The Haskell implementation validates against the "ticked" ledger
            state (ledger state after applying all mempool txs).

        Args:
            tx_cbor: Raw CBOR-encoded transaction bytes.

        Returns:
            ValidatedTx if the transaction was accepted.

        Raises:
            MempoolCapacityError: If adding the tx would exceed capacity.
            MempoolValidationError: If the tx fails validation.
            MempoolDuplicateError: If the tx is already in the mempool.
        """
        tx_size = len(tx_cbor)
        tx_id = _compute_tx_id(tx_cbor)

        async with self._lock:
            # Check for duplicates.
            if tx_id in self._tx_index:
                raise MempoolDuplicateError(tx_id)

            # Check capacity.
            if self._total_size + tx_size > self._config.capacity_bytes:
                raise MempoolCapacityError(
                    needed=tx_size,
                    available=self._config.capacity_bytes - self._total_size,
                    capacity=self._config.capacity_bytes,
                )

            # Validate against the cached ledger state.
            errors = self._validator.validate_tx(tx_cbor, self._current_slot)
            if errors:
                raise MempoolValidationError(tx_id, errors)

            # Apply to cached ledger state so subsequent validations see
            # the effects of this transaction.
            self._validator.apply_tx(tx_cbor, self._current_slot)

            # Create the validated tx and ticket.
            validated = ValidatedTx(
                tx_cbor=tx_cbor,
                tx_id=tx_id,
                tx_size=tx_size,
            )
            ticket = TxTicket(
                validated_tx=validated,
                ticket_no=self._next_ticket_no,
                measure=TxMeasure(size_bytes=tx_size),
            )
            self._next_ticket_no += 1

            # Add to the sequence and index.
            self._tickets.append(ticket)
            self._tx_index[tx_id] = ticket
            self._total_size += tx_size

            logger.debug(
                "Mempool: added tx %s (size=%d, total=%d/%d, count=%d)",
                tx_id.hex()[:16],
                tx_size,
                self._total_size,
                self._config.capacity_bytes,
                len(self._tickets),
            )

            return validated

    async def remove_txs(self, tx_ids: set[bytes]) -> int:
        """Remove transactions by ID (typically after block inclusion).

        Transactions that are not in the mempool are silently ignored.

        Haskell reference:
            Ouroboros.Consensus.Mempool.Impl.Common.implRemoveTxs
            Removes confirmed transactions and triggers re-validation
            of remaining transactions. We separate removal from
            re-validation — call sync_with_ledger after if the ledger
            state has changed.

        Args:
            tx_ids: Set of transaction IDs to remove.

        Returns:
            Number of transactions actually removed.
        """
        async with self._lock:
            return self._remove_txs_locked(tx_ids)

    def _remove_txs_locked(self, tx_ids: set[bytes]) -> int:
        """Remove transactions by ID (caller must hold the lock)."""
        removed = 0
        new_tickets: list[TxTicket] = []

        for ticket in self._tickets:
            if ticket.validated_tx.tx_id in tx_ids:
                del self._tx_index[ticket.validated_tx.tx_id]
                self._total_size -= ticket.validated_tx.tx_size
                removed += 1
            else:
                new_tickets.append(ticket)

        self._tickets = new_tickets

        if removed > 0:
            logger.debug(
                "Mempool: removed %d txs, remaining=%d, size=%d/%d",
                removed,
                len(self._tickets),
                self._total_size,
                self._config.capacity_bytes,
            )

        return removed

    async def get_snapshot(self) -> MempoolSnapshot:
        """Return an atomic snapshot of the current mempool contents.

        The snapshot is a frozen view — modifications to the mempool
        after the snapshot is taken do not affect it.

        Haskell reference:
            Ouroboros.Consensus.Mempool.API.getSnapshot
            Returns a MempoolSnapshot that is consistent with a particular
            ledger state.

        Returns:
            MempoolSnapshot with ordered tickets and metadata.
        """
        async with self._lock:
            return MempoolSnapshot(
                tickets=list(self._tickets),
                slot=self._current_slot,
                total_size_bytes=self._total_size,
                capacity_bytes=self._config.capacity_bytes,
            )

    async def sync_with_ledger(
        self,
        new_slot: int,
    ) -> list[bytes]:
        """Re-validate all mempool transactions against the current validator state.

        Called when the chain tip changes (new block applied or rollback).
        The caller must update the validator's ledger state before calling
        this method. Each transaction is re-validated in ticket order against
        the fresh ledger state. Transactions that fail re-validation are
        removed.

        Haskell reference:
            Ouroboros.Consensus.Mempool.Impl.Pure.pureSyncWithLedger
            Re-validates all txs against the new ticked ledger state,
            removing any that are now invalid (e.g., inputs already spent
            by a block, TTL expired, etc.)

        Args:
            new_slot: The slot number of the new ledger state.

        Returns:
            List of tx_ids that were removed during re-validation.
        """
        async with self._lock:
            self._current_slot = new_slot

            # Save the validator state (this is the fresh ledger state
            # from the chain tip, before any mempool txs are applied).
            base_state = self._validator.snapshot_state()

            # Re-validate each transaction in order.
            surviving_tickets: list[TxTicket] = []
            removed_ids: list[bytes] = []
            new_total_size = 0

            for ticket in self._tickets:
                vtx = ticket.validated_tx
                errors = self._validator.validate_tx(vtx.tx_cbor, new_slot)

                if errors:
                    # Transaction is now invalid — remove it.
                    del self._tx_index[vtx.tx_id]
                    removed_ids.append(vtx.tx_id)
                    logger.debug(
                        "Mempool: re-validation removed tx %s: %s",
                        vtx.tx_id.hex()[:16],
                        errors[0],
                    )
                else:
                    # Still valid — apply to the cached state and keep.
                    self._validator.apply_tx(vtx.tx_cbor, new_slot)
                    surviving_tickets.append(ticket)
                    new_total_size += vtx.tx_size

            self._tickets = surviving_tickets
            self._total_size = new_total_size

            if removed_ids:
                logger.info(
                    "Mempool: sync removed %d txs, remaining=%d",
                    len(removed_ids),
                    len(self._tickets),
                )

            return removed_ids

    async def get_txs_for_block(self, max_size: int) -> list[ValidatedTx]:
        """Select transactions for block forging.

        Returns the largest prefix of mempool transactions (in ticket
        order) that fits within max_size bytes. This is a greedy prefix
        selection — it stops at the first transaction that doesn't fit,
        matching the Haskell node's behavior.

        Haskell reference:
            Ouroboros.Consensus.Mempool.API.getSnapshotFor
            The block forger uses the mempool snapshot to select transactions.
            Selection is prefix-based: take transactions in order until the
            block body is full.

        Args:
            max_size: Maximum total size in CBOR bytes for the block body.

        Returns:
            List of ValidatedTx in ticket order, total size <= max_size.
        """
        async with self._lock:
            result: list[ValidatedTx] = []
            running_size = 0

            for ticket in self._tickets:
                vtx = ticket.validated_tx
                if running_size + vtx.tx_size > max_size:
                    break
                result.append(vtx)
                running_size += vtx.tx_size

            return result

    async def has_tx(self, tx_id: bytes) -> bool:
        """Check if a transaction is in the mempool.

        Args:
            tx_id: Transaction hash (32 bytes).

        Returns:
            True if the transaction is in the mempool.
        """
        async with self._lock:
            return tx_id in self._tx_index

    async def get_tx_ids_and_sizes(self) -> list[tuple[bytes, int]]:
        """Return all tx IDs and their sizes, in ticket order.

        Used by the tx-submission server to advertise mempool contents.

        Returns:
            List of (tx_id, size_bytes) pairs.
        """
        async with self._lock:
            return [
                (t.validated_tx.tx_id, t.validated_tx.tx_size)
                for t in self._tickets
            ]

    async def get_tx(self, tx_id: bytes) -> bytes | None:
        """Look up a transaction's CBOR bytes by its ID.

        Args:
            tx_id: Transaction hash (32 bytes).

        Returns:
            Raw CBOR bytes, or None if not in mempool.
        """
        async with self._lock:
            ticket = self._tx_index.get(tx_id)
            if ticket is None:
                return None
            return ticket.validated_tx.tx_cbor

    # -- Debug / inspection --------------------------------------------------

    def __len__(self) -> int:
        """Return the number of transactions in the mempool."""
        return len(self._tickets)

    def __repr__(self) -> str:
        return (
            f"Mempool(txs={len(self._tickets)}, "
            f"size={self._total_size}/{self._config.capacity_bytes})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_tx_id(tx_cbor: bytes) -> bytes:
    """Compute the transaction ID (Blake2b-256 of the tx body).

    In Cardano, the tx_id is the Blake2b-256 hash of the CBOR-encoded
    transaction body (not the full transaction). For mempool purposes
    we hash the full CBOR — the caller is expected to provide the tx
    body hash if they need the canonical ID.

    For now we hash the full tx CBOR as a unique identifier. When
    integrated with pycardano Transaction objects, we'll use the
    canonical tx body hash instead.

    Haskell reference:
        Cardano.Ledger.TxIn (TxId = SafeHash (TxBody era))
    """
    return hashlib.blake2b(tx_cbor, digest_size=32).digest()


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class MempoolError(Exception):
    """Base class for mempool errors."""

    pass


class MempoolValidationError(MempoolError):
    """Raised when a transaction fails mempool validation.

    Attributes:
        tx_id: The transaction hash.
        errors: List of validation error descriptions.
    """

    def __init__(self, tx_id: bytes, errors: list[str]) -> None:
        self.tx_id = tx_id
        self.errors = errors
        super().__init__(
            f"Transaction {tx_id.hex()[:16]}... failed validation: "
            f"{'; '.join(errors)}"
        )


class MempoolCapacityError(MempoolError):
    """Raised when adding a transaction would exceed mempool capacity.

    Attributes:
        needed: Bytes needed for the new transaction.
        available: Bytes currently available.
        capacity: Total mempool capacity.
    """

    def __init__(self, needed: int, available: int, capacity: int) -> None:
        self.needed = needed
        self.available = available
        self.capacity = capacity
        super().__init__(
            f"Mempool full: need {needed} bytes, "
            f"available={available}, capacity={capacity}"
        )


class MempoolDuplicateError(MempoolError):
    """Raised when a transaction is already in the mempool.

    Attributes:
        tx_id: The duplicate transaction hash.
    """

    def __init__(self, tx_id: bytes) -> None:
        self.tx_id = tx_id
        super().__init__(
            f"Duplicate transaction: {tx_id.hex()[:16]}..."
        )
