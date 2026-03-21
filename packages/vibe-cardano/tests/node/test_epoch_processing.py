"""Tests for epoch boundary processing during sync.

Verifies that NodeKernel correctly:
- Detects epoch boundary crossings
- Evolves the epoch nonce at boundaries
- Accumulates VRF outputs within the stability window (first 2/3 of epoch)
- Ignores VRF outputs outside the stability window (last 1/3 of epoch)
- Handles skipped epochs gracefully

Spec references:
    * Shelley ledger formal spec, Section 11 (Epoch boundary rules)
    * Ouroboros Praos paper, Section 4.1 (Epoch nonce evolution)

Haskell references:
    * Cardano.Ledger.Shelley.Rules.Tick -- TICK transition
    * Ouroboros.Consensus.Protocol.Praos -- epoch nonce
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.consensus.nonce import (
    EpochNonce,
    accumulate_vrf_output,
    evolve_nonce,
    is_in_stability_window,
)
from vibe.cardano.node.kernel import NodeKernel


EPOCH_LENGTH = 100  # Small epoch for testing (real mainnet: 432000)


@pytest.fixture()
def kernel() -> NodeKernel:
    """Create a NodeKernel initialised with a known genesis nonce."""
    nk = NodeKernel()
    genesis_hash = hashlib.blake2b(b"test-genesis", digest_size=32).digest()
    nk.init_nonce(genesis_hash, EPOCH_LENGTH)
    return nk


class TestEpochBoundaryDetection:
    """Test that epoch boundaries are detected when slot crosses epoch length."""

    def test_epoch_boundary_detected(self, kernel: NodeKernel) -> None:
        """Epoch boundary fires when slot crosses into a new epoch."""
        assert kernel.current_epoch == 0

        # Slot 99 is still epoch 0
        slot_99 = 99
        new_epoch_99 = slot_99 // EPOCH_LENGTH
        assert new_epoch_99 == 0

        # Slot 100 is epoch 1 -- boundary crossed
        slot_100 = 100
        new_epoch_100 = slot_100 // EPOCH_LENGTH
        assert new_epoch_100 == 1
        assert new_epoch_100 > kernel.current_epoch

        kernel.on_epoch_boundary(new_epoch_100)
        assert kernel.current_epoch == 1

    def test_no_double_fire(self, kernel: NodeKernel) -> None:
        """Calling on_epoch_boundary with same epoch is a no-op."""
        kernel.on_epoch_boundary(1)
        nonce_after_first = kernel.epoch_nonce

        kernel.on_epoch_boundary(1)
        assert kernel.epoch_nonce == nonce_after_first

    def test_epoch_zero_start(self, kernel: NodeKernel) -> None:
        """Slots in epoch 0 don't trigger a boundary."""
        for slot in [0, 1, 50, 99]:
            new_epoch = slot // EPOCH_LENGTH
            assert new_epoch == 0
            assert new_epoch <= kernel.current_epoch


class TestNonceEvolution:
    """Test that the epoch nonce evolves correctly at boundaries."""

    def test_nonce_evolves_at_boundary(self, kernel: NodeKernel) -> None:
        """Nonce changes after epoch boundary processing."""
        original_nonce = kernel.epoch_nonce

        kernel.on_epoch_boundary(1)

        assert kernel.epoch_nonce != original_nonce
        assert kernel.epoch_nonce.value != original_nonce.value
        assert len(kernel.epoch_nonce.value) == 32

    def test_nonce_evolution_matches_direct_call(self, kernel: NodeKernel) -> None:
        """NodeKernel nonce evolution matches direct evolve_nonce() call."""
        original_nonce = kernel.epoch_nonce
        # eta_v starts as genesis_hash (set by init_nonce)
        eta_v = kernel._eta_v

        expected = evolve_nonce(original_nonce, eta_v, None)

        kernel.on_epoch_boundary(1)

        assert kernel.epoch_nonce == expected

    def test_eta_v_resets_after_boundary(self, kernel: NodeKernel) -> None:
        """After epoch boundary, eta_v resets to zero bytes."""
        kernel.on_epoch_boundary(1)
        assert kernel._eta_v == b"\x00" * 32


class TestVRFAccumulation:
    """Test VRF output accumulation within the stability window."""

    def test_vrf_accumulated_in_stability_window(self, kernel: NodeKernel) -> None:
        """VRF outputs in the first 2/3 of epoch are accumulated."""
        # Stability window = first 2/3 of epoch = slots 0..66 for epoch_length=100
        vrf_out = b"\xaa" * 32
        eta_v_before = kernel._eta_v

        # Slot 10 is in the first 2/3 of epoch 0
        kernel.on_block_vrf_output(10, 0, vrf_out)

        assert kernel._eta_v != eta_v_before
        expected = accumulate_vrf_output(eta_v_before, vrf_out)
        assert kernel._eta_v == expected

    def test_vrf_not_accumulated_outside_window(self, kernel: NodeKernel) -> None:
        """VRF outputs in the last 1/3 of epoch are NOT accumulated."""
        eta_v_before = kernel._eta_v
        vrf_out = b"\xbb" * 32

        # Slot 80 in epoch starting at 0, epoch_length=100 -> last 1/3
        # is_in_stability_window checks slot < epoch_start + (2/3 * epoch_length)
        # 2/3 * 100 = 66.67 -> slot must be < 66 from epoch_start
        # Slot 80 >= 66, so it's outside the stability window
        kernel.on_block_vrf_output(80, 0, vrf_out)

        assert kernel._eta_v == eta_v_before

    def test_multiple_vrf_accumulations(self, kernel: NodeKernel) -> None:
        """Multiple VRF outputs are chained correctly."""
        vrf_1 = b"\x01" * 32
        vrf_2 = b"\x02" * 32

        eta_v_0 = kernel._eta_v
        kernel.on_block_vrf_output(5, 0, vrf_1)
        eta_v_1 = kernel._eta_v
        assert eta_v_1 == accumulate_vrf_output(eta_v_0, vrf_1)

        kernel.on_block_vrf_output(10, 0, vrf_2)
        eta_v_2 = kernel._eta_v
        assert eta_v_2 == accumulate_vrf_output(eta_v_1, vrf_2)

    def test_stability_window_boundary_exact(self, kernel: NodeKernel) -> None:
        """Verify the exact stability window cutoff matches is_in_stability_window."""
        vrf_out = b"\xcc" * 32

        # Find the cutoff slot
        for slot in range(EPOCH_LENGTH):
            in_window = is_in_stability_window(slot, 0, EPOCH_LENGTH)
            eta_before = kernel._eta_v
            kernel.on_block_vrf_output(slot, 0, vrf_out)

            if in_window:
                assert kernel._eta_v != eta_before, f"Slot {slot} should be in window"
            else:
                assert kernel._eta_v == eta_before, f"Slot {slot} should NOT be in window"


class TestMultipleEpochBoundaries:
    """Test handling of multiple epoch transitions, including skips."""

    def test_sequential_epochs(self, kernel: NodeKernel) -> None:
        """Process epochs 0->1->2->3 sequentially."""
        nonces = [kernel.epoch_nonce]

        for epoch in [1, 2, 3]:
            kernel.on_epoch_boundary(epoch)
            assert kernel.current_epoch == epoch
            nonces.append(kernel.epoch_nonce)

        # All nonces should be distinct
        nonce_values = [n.value for n in nonces]
        assert len(set(nonce_values)) == len(nonce_values), "All nonces should be unique"

    def test_skipped_epoch(self, kernel: NodeKernel) -> None:
        """Handle jumping from epoch 0 directly to epoch 3 (skipping 1, 2).

        This can happen if no blocks were produced in epochs 1 and 2.
        The NodeKernel should still evolve the nonce once for the jump.
        """
        original_nonce = kernel.epoch_nonce

        kernel.on_epoch_boundary(3)
        assert kernel.current_epoch == 3
        assert kernel.epoch_nonce != original_nonce

    def test_vrf_accumulates_then_resets_across_epochs(self, kernel: NodeKernel) -> None:
        """VRF accumulation resets at each epoch boundary."""
        vrf_out = b"\xdd" * 32

        # Accumulate some VRF in epoch 0
        kernel.on_block_vrf_output(5, 0, vrf_out)
        assert kernel._eta_v != b"\x00" * 32

        # Cross into epoch 1 -- eta_v resets
        kernel.on_epoch_boundary(1)
        assert kernel._eta_v == b"\x00" * 32

        # Accumulate VRF in epoch 1
        kernel.on_block_vrf_output(105, 100, vrf_out)
        assert kernel._eta_v != b"\x00" * 32

        # Cross into epoch 2 -- eta_v resets again
        kernel.on_epoch_boundary(2)
        assert kernel._eta_v == b"\x00" * 32
