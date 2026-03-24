"""Tests for LedgerTxValidator — full era-aware mempool tx validation.

Tests cover:
    - Valid CBOR transaction accepted (well-formed pycardano Transaction)
    - Invalid CBOR rejected (garbage bytes)
    - Malformed CBOR rejected (valid CBOR but not a transaction structure)
    - Validator with protocol_params passes them through
    - Validator without ledger_db still works (graceful degradation)
    - Era property is settable and used

Haskell ref:
    Ouroboros.Consensus.Ledger.SupportsMempool (applyTx tests)
"""

from __future__ import annotations

from vibe.cardano.mempool.validator import LedgerTxValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_tx_cbor() -> bytes:
    """Build a minimal well-formed Cardano transaction in CBOR.

    Uses pycardano to construct a transaction with a dummy input and output,
    then serializes it. This ensures the CBOR is structurally valid even
    though the tx itself won't pass UTxO validation (no real inputs).
    """
    from pycardano import (
        Transaction,
        TransactionBody,
        TransactionInput,
        TransactionOutput,
        TransactionWitnessSet,
    )
    from pycardano.hash import TransactionId

    tx_body = TransactionBody(
        inputs=[
            TransactionInput(
                TransactionId(b"\x00" * 32),
                0,
            )
        ],
        outputs=[
            TransactionOutput.from_primitive(
                [
                    # A minimal Shelley-era enterprise address (testnet)
                    bytes.fromhex("60" + "00" * 28),
                    1_500_000,
                ]
            )
        ],
        fee=200_000,
    )
    tx = Transaction(tx_body, TransactionWitnessSet())
    return tx.to_cbor()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLedgerTxValidator:
    """Tests for the LedgerTxValidator class."""

    def test_valid_cbor_tx_accepted(self) -> None:
        """A well-formed pycardano Transaction passes CBOR decode.

        The tx will fail UTxO validation (inputs don't exist in the
        empty ledger), but it should NOT fail at the CBOR decode stage.
        The errors returned should be ledger-rule errors, not decode errors.
        """
        tx_cbor = _make_minimal_tx_cbor()
        validator = LedgerTxValidator(ledger_db=None)
        errors = validator.validate_tx(tx_cbor, current_slot=1000)

        # Should not contain CBOR decode errors
        for err in errors:
            assert "CBOR decode error" not in err, (
                f"Well-formed tx should not produce CBOR decode errors, got: {err}"
            )

    def test_invalid_cbor_rejected(self) -> None:
        """Garbage bytes are rejected with a CBOR decode error."""
        garbage = b"\xde\xad\xbe\xef"
        validator = LedgerTxValidator(ledger_db=None)
        errors = validator.validate_tx(garbage, current_slot=0)

        assert len(errors) > 0, "Garbage bytes should produce errors"
        assert any("CBOR decode error" in e or "Validation error" in e for e in errors), (
            f"Expected CBOR/validation error, got: {errors}"
        )

    def test_malformed_tx_rejected(self) -> None:
        """Valid CBOR but not a transaction structure is rejected."""
        import cbor2

        # Encode a plain integer — valid CBOR but not a tx
        bad_cbor = cbor2.dumps(42)
        validator = LedgerTxValidator(ledger_db=None)
        errors = validator.validate_tx(bad_cbor, current_slot=0)

        assert len(errors) > 0, "Non-transaction CBOR should produce errors"

    def test_validator_with_protocol_params(self) -> None:
        """Protocol params are stored and accessible."""
        sentinel = {"min_fee_a": 44, "min_fee_b": 155381}
        validator = LedgerTxValidator(
            ledger_db=None,
            protocol_params=sentinel,
        )
        assert validator.protocol_params is sentinel

        # Validation still works (params are passed through to validate_block)
        tx_cbor = _make_minimal_tx_cbor()
        errors = validator.validate_tx(tx_cbor, current_slot=0)
        # Should get ledger errors (missing inputs), not crashes
        assert isinstance(errors, list)

    def test_validator_without_ledger_still_works(self) -> None:
        """Passing ledger_db=None doesn't crash — graceful degradation.

        When the ledger DB is None, era validators may report missing
        inputs or other errors, but the validator should not raise
        unhandled exceptions.
        """
        tx_cbor = _make_minimal_tx_cbor()
        validator = LedgerTxValidator(ledger_db=None)
        errors = validator.validate_tx(tx_cbor, current_slot=500)

        # Must return a list (possibly with errors, but no crash)
        assert isinstance(errors, list)

    def test_era_property_settable(self) -> None:
        """The current_era property can be set and read back."""
        from vibe.cardano.consensus.hfc import Era

        validator = LedgerTxValidator(ledger_db=None)
        assert validator.current_era is None  # default

        validator.current_era = Era.BABBAGE
        assert validator.current_era == Era.BABBAGE

        validator.current_era = Era.CONWAY
        assert validator.current_era == Era.CONWAY

    def test_protocol_params_property_settable(self) -> None:
        """The protocol_params property can be updated after construction."""
        validator = LedgerTxValidator(ledger_db=None)
        assert validator.protocol_params is None

        new_params = {"min_fee_a": 44}
        validator.protocol_params = new_params
        assert validator.protocol_params is new_params

    def test_apply_tx_noop(self) -> None:
        """apply_tx is a no-op and doesn't raise."""
        validator = LedgerTxValidator(ledger_db=None)
        tx_cbor = _make_minimal_tx_cbor()
        # Should not raise
        validator.apply_tx(tx_cbor, current_slot=0)

    def test_snapshot_restore_noop(self) -> None:
        """snapshot_state/restore_state are no-ops."""
        validator = LedgerTxValidator(ledger_db=None)
        state = validator.snapshot_state()
        assert state is None
        # Should not raise
        validator.restore_state(state)

    def test_empty_bytes_rejected(self) -> None:
        """Empty bytes are rejected."""
        validator = LedgerTxValidator(ledger_db=None)
        errors = validator.validate_tx(b"", current_slot=0)
        assert len(errors) > 0, "Empty bytes should produce errors"
