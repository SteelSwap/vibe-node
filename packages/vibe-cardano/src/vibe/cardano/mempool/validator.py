"""Concrete TxValidator backed by the ledger validation pipeline.

Implements the TxValidator protocol required by the Mempool, using
the era-aware validate_block() dispatch from the HFC module and
pycardano Transaction deserialization.

The validator decodes raw CBOR bytes into a pycardano Transaction,
then dispatches to the correct era-specific validation rules via
the HFC validate_block() function. This gives the mempool the same
validation rigor as block-level validation.

Haskell reference:
    Ouroboros.Consensus.Ledger.SupportsMempool (applyTx, reapplyTx)
    Ouroboros.Consensus.Mempool.Impl.Pure (pureValidateAndApplyTx)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LedgerTxValidator:
    """Transaction validator backed by the ledger UTxO state.

    Validates raw CBOR transactions against the current ledger state
    using era-aware validation rules. Satisfies the TxValidator protocol
    expected by the Mempool.

    The validation pipeline:
        1. Decode CBOR bytes into a pycardano Transaction object
        2. Determine the current era (from constructor or default to Conway)
        3. Dispatch to era-specific ledger rules via HFC validate_block()

    Args:
        ledger_db: The LedgerDB instance (UTxO state).
        protocol_params: Era-specific protocol parameters for validation.
            If None, era validators will use their defaults.
        current_era: The current ledger era. If None, defaults to Conway
            (the current mainnet era).

    Haskell ref:
        Ouroboros.Consensus.Ledger.SupportsMempool.txForgetValidated
        Ouroboros.Consensus.Mempool.Impl.Pure.pureValidateAndApplyTx
    """

    __slots__ = ("_ledger_db", "_protocol_params", "_current_era")

    def __init__(
        self,
        ledger_db: Any,
        protocol_params: Any = None,
        current_era: Any = None,
    ) -> None:
        self._ledger_db = ledger_db
        self._protocol_params = protocol_params
        self._current_era = current_era

    @property
    def current_era(self) -> Any:
        """The era used for validation dispatch."""
        return self._current_era

    @current_era.setter
    def current_era(self, era: Any) -> None:
        """Update the current era (e.g., after an era transition)."""
        self._current_era = era

    @property
    def protocol_params(self) -> Any:
        """The protocol parameters used for validation."""
        return self._protocol_params

    @protocol_params.setter
    def protocol_params(self, params: Any) -> None:
        """Update protocol parameters (e.g., after an epoch boundary)."""
        self._protocol_params = params

    def validate_tx(self, tx_cbor: bytes, current_slot: int) -> list[str]:
        """Validate a CBOR-encoded transaction using full era-aware rules.

        Decodes the transaction via pycardano, then dispatches to the
        appropriate era validator through the HFC validate_block() function.
        Returns a list of error strings (empty = valid).

        This gives mempool transactions the same validation as block
        transactions, catching issues like:
        - Missing or invalid witnesses
        - Insufficient fees
        - Expired TTL
        - Missing UTxO inputs
        - Value not conserved
        - Script validation failures (Alonzo+)
        - Collateral issues (Alonzo+)

        Haskell ref:
            Ouroboros.Consensus.Ledger.SupportsMempool.applyTx
            This is analogous to applyTx which validates and applies
            a transaction against the current ledger state.

        Args:
            tx_cbor: Raw CBOR-encoded transaction bytes.
            current_slot: Current slot number for TTL/validity checks.

        Returns:
            List of validation error strings. Empty list means valid.
        """
        errors: list[str] = []

        try:
            # Step 1: Decode the transaction from CBOR via pycardano.
            # pycardano's Transaction.from_cbor handles all era formats.
            from pycardano import Transaction

            tx = Transaction.from_cbor(tx_cbor)

        except Exception as exc:
            errors.append(f"CBOR decode error: {exc}")
            return errors

        try:
            # Step 2: Determine the era for validation dispatch.
            from vibe.cardano.consensus.hfc import Era, validate_block

            era = self._current_era if self._current_era is not None else Era.CONWAY

            # Step 3: Dispatch to era-specific validation via HFC.
            # validate_block expects a list of Transaction objects and
            # returns a list of error strings. We wrap our single tx
            # in a list to reuse the same dispatch infrastructure.
            tx_errors = validate_block(
                era=era,
                block=[tx],
                ledger_state=self._ledger_db,
                protocol_params=self._protocol_params,
                current_slot=current_slot,
            )
            errors.extend(tx_errors)

        except Exception as exc:
            errors.append(f"Validation error: {exc}")

        return errors

    def apply_tx(self, tx_cbor: bytes, current_slot: int) -> None:
        """Apply a validated transaction to the cached ledger state.

        For the mempool, this is a no-op -- we don't speculatively
        update the UTxO set. The real application happens when the
        block containing this transaction is added to ChainDB.

        Haskell ref:
            Ouroboros.Consensus.Ledger.SupportsMempool.reapplyTx
            In the Haskell node, applyTx updates a ticked ledger state.
            We defer that to block application for now.
        """
        pass

    def snapshot_state(self) -> Any:
        """Return current state snapshot (unused for now).

        When speculative UTxO tracking is implemented, this will
        capture the cached ledger state for rollback during
        re-validation.
        """
        return None

    def restore_state(self, state: Any) -> None:
        """Restore state from snapshot (unused for now)."""
        pass
