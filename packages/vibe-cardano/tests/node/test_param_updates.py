"""Tests for protocol parameter update pipeline (M5.33).

Validates that NodeKernel can:
- Initialize protocol params from genesis config
- Queue parameter updates from governance proposals
- Apply queued updates at epoch boundaries
- Handle multiple updates with correct merge semantics
- Behave correctly when no updates are queued
"""

from __future__ import annotations

import pytest

from vibe.cardano.node.kernel import NodeKernel


class TestInitProtocolParams:
    """Test seeding protocol parameters at node startup."""

    def test_init_protocol_params(self) -> None:
        kernel = NodeKernel()
        assert kernel.protocol_params == {}

        params = {
            "max_block_body_size": 90112,
            "max_tx_size": 16384,
            "min_fee_coefficient": 44,
            "min_fee_constant": 155381,
        }
        kernel.init_protocol_params(params)
        assert kernel.protocol_params == params

    def test_init_protocol_params_copies(self) -> None:
        """Ensure init_protocol_params makes a copy, not a reference."""
        kernel = NodeKernel()
        params = {"max_block_body_size": 90112}
        kernel.init_protocol_params(params)
        params["max_block_body_size"] = 999999
        assert kernel.protocol_params["max_block_body_size"] == 90112


class TestQueueAndApplyUpdates:
    """Test queuing and applying protocol parameter updates."""

    def test_queue_and_apply_updates(self) -> None:
        kernel = NodeKernel()
        kernel.init_protocol_params({"max_tx_size": 16384, "min_fee_constant": 155381})

        kernel.queue_param_update({"max_tx_size": 32768})
        # Params should not change until apply
        assert kernel.protocol_params["max_tx_size"] == 16384

        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 32768
        # Unchanged params are preserved
        assert kernel.protocol_params["min_fee_constant"] == 155381

    def test_apply_clears_queue(self) -> None:
        kernel = NodeKernel()
        kernel.init_protocol_params({"max_tx_size": 16384})

        kernel.queue_param_update({"max_tx_size": 32768})
        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 32768

        # Second apply should be a no-op (queue was cleared)
        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 32768

    def test_multiple_updates_merge(self) -> None:
        """Multiple updates are applied in order; later updates win."""
        kernel = NodeKernel()
        kernel.init_protocol_params({
            "max_tx_size": 16384,
            "min_fee_constant": 155381,
            "max_block_body_size": 90112,
        })

        # Two updates queued in order
        kernel.queue_param_update({"max_tx_size": 32768, "min_fee_constant": 200000})
        kernel.queue_param_update({"max_tx_size": 65536, "max_block_body_size": 131072})

        kernel.apply_pending_updates()

        # max_tx_size: second update wins (65536)
        assert kernel.protocol_params["max_tx_size"] == 65536
        # min_fee_constant: first update applies (200000), second doesn't touch it
        assert kernel.protocol_params["min_fee_constant"] == 200000
        # max_block_body_size: second update applies (131072)
        assert kernel.protocol_params["max_block_body_size"] == 131072

    def test_empty_queue_apply_is_noop(self) -> None:
        kernel = NodeKernel()
        kernel.init_protocol_params({"max_tx_size": 16384})

        # Apply with nothing queued
        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 16384

    def test_new_params_added(self) -> None:
        """Updates can introduce entirely new parameters."""
        kernel = NodeKernel()
        kernel.init_protocol_params({"max_tx_size": 16384})

        kernel.queue_param_update({"collateral_percentage": 150})
        kernel.apply_pending_updates()

        assert kernel.protocol_params["max_tx_size"] == 16384
        assert kernel.protocol_params["collateral_percentage"] == 150


class TestParamsAtEpochBoundary:
    """Test that params are applied correctly around epoch boundaries."""

    def test_params_available_after_epoch_boundary(self) -> None:
        """Simulate epoch boundary: queue update, then apply via epoch transition."""
        kernel = NodeKernel()
        kernel.init_nonce(b"\x00" * 32, epoch_length=100)
        kernel.init_protocol_params({"max_tx_size": 16384})

        # Queue an update (as if a governance action was enacted)
        kernel.queue_param_update({"max_tx_size": 32768})

        # Simulate epoch boundary
        kernel.on_epoch_boundary(1)
        kernel.apply_pending_updates()

        assert kernel.protocol_params["max_tx_size"] == 32768
        assert kernel._current_epoch == 1

    def test_no_update_without_epoch_boundary(self) -> None:
        """Queued updates should not affect params until epoch boundary."""
        kernel = NodeKernel()
        kernel.init_protocol_params({"max_tx_size": 16384})

        kernel.queue_param_update({"max_tx_size": 32768})

        # No epoch boundary call — params unchanged
        assert kernel.protocol_params["max_tx_size"] == 16384

    def test_multiple_epochs_accumulate(self) -> None:
        """Updates across multiple epochs apply independently."""
        kernel = NodeKernel()
        kernel.init_nonce(b"\x00" * 32, epoch_length=100)
        kernel.init_protocol_params({"max_tx_size": 16384, "min_fee_constant": 155381})

        # Epoch 1: update max_tx_size
        kernel.queue_param_update({"max_tx_size": 32768})
        kernel.on_epoch_boundary(1)
        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 32768
        assert kernel.protocol_params["min_fee_constant"] == 155381

        # Epoch 2: update min_fee_constant
        kernel.queue_param_update({"min_fee_constant": 200000})
        kernel.on_epoch_boundary(2)
        kernel.apply_pending_updates()
        assert kernel.protocol_params["max_tx_size"] == 32768
        assert kernel.protocol_params["min_fee_constant"] == 200000
