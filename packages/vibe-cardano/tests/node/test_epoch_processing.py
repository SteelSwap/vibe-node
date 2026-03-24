"""Tests for epoch boundary processing during sync.

Verifies that NodeKernel correctly:
- Detects epoch boundary crossings
- Evolves the epoch nonce at boundaries using the 5-nonce Praos model
- Accumulates VRF nonce contributions via on_block()
- Updates candidate_nonce only within the stability window
- Handles skipped epochs gracefully

Spec references:
    * Shelley ledger formal spec, Section 11 (Epoch boundary rules)
    * Ouroboros Praos paper, Section 4.1 (Epoch nonce evolution)

Haskell references:
    * Cardano.Ledger.Shelley.Rules.Tick -- TICK transition
    * Ouroboros.Consensus.Protocol.Praos -- epoch nonce, PraosState
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.consensus.nonce import (
    EpochNonce,
    is_in_stability_window,
    stability_window,
)
from vibe.cardano.node.kernel import NodeKernel


EPOCH_LENGTH = 100  # Small epoch for testing (real mainnet: 432000)
# Use small security_param and active_slot_coeff so stability window
# is computable and smaller than epoch_length for testing.
# stability_window = 3 * k / f.  With k=2, f=0.05: 3*2/0.05 = 120 > 100
# => capped at epoch_length = 100, so ALL slots are in window.
# To get a meaningful window, use k=1, f=0.05: 3*1/0.05 = 60.
TEST_K = 1
TEST_F = 0.05


@pytest.fixture()
def kernel() -> NodeKernel:
    """Create a NodeKernel initialised with a known genesis nonce."""
    nk = NodeKernel()
    genesis_hash = hashlib.blake2b(b"test-genesis", digest_size=32).digest()
    nk.init_nonce(genesis_hash, EPOCH_LENGTH, security_param=TEST_K, active_slot_coeff=TEST_F)
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
        """Nonce changes after epoch boundary when blocks have been processed.

        The 5-nonce Praos model combines candidate_nonce and last_epoch_block_nonce.
        We need to process at least one block so lab_nonce is non-neutral.
        """
        original_nonce = kernel.epoch_nonce

        # Process a block so lab_nonce is no longer neutral
        kernel.on_block(10, b"\xab" * 32, b"\xcd" * 64)

        kernel.on_epoch_boundary(1)

        assert kernel.epoch_nonce != original_nonce
        assert kernel.epoch_nonce.value != original_nonce.value
        assert len(kernel.epoch_nonce.value) == 32

    def test_nonce_evolution_uses_candidate_and_lab(self, kernel: NodeKernel) -> None:
        """NodeKernel nonce evolution combines candidate_nonce and last_epoch_block_nonce.

        Haskell ref: tickChainDepState in Praos.hs
        new_nonce = combine(candidate_nonce, last_epoch_block_nonce)
        """
        # Process a block to set non-neutral lab_nonce
        kernel.on_block(10, b"\xab" * 32, b"\xcd" * 64)

        candidate_before = kernel._candidate_nonce
        lab_before = kernel._last_epoch_block_nonce

        # Compute expected: combine(candidate, lab)
        expected = kernel._combine_nonces(candidate_before, lab_before)

        kernel.on_epoch_boundary(1)

        assert kernel.epoch_nonce.value == expected

    def test_evolving_nonce_preserved_after_boundary(self, kernel: NodeKernel) -> None:
        """The evolving nonce is NOT reset after epoch boundary.

        In the 5-nonce Praos model, the evolving nonce continues accumulating
        across epoch boundaries. It is only used to update candidate_nonce
        within the stability window.
        """
        evolving_before = kernel._evolving_nonce

        kernel.on_epoch_boundary(1)

        # evolving_nonce should remain unchanged by epoch boundary
        assert kernel._evolving_nonce == evolving_before


class TestVRFAccumulation:
    """Test VRF output accumulation via on_block()."""

    def test_vrf_accumulated_via_on_block(self, kernel: NodeKernel) -> None:
        """on_block() updates the evolving nonce with VRF nonce contribution."""
        vrf_out = b"\xaa" * 64  # 64-byte VRF output
        evolving_before = kernel._evolving_nonce

        # Slot 10 is in the stability window (window = 60 for our params)
        kernel.on_block(10, b"\x00" * 32, vrf_out)

        assert kernel._evolving_nonce != evolving_before

    def test_candidate_updated_in_stability_window(self, kernel: NodeKernel) -> None:
        """Candidate nonce is updated when block is within stability window."""
        vrf_out = b"\xbb" * 64
        candidate_before = kernel._candidate_nonce

        # Slot 10 is well within stability window (window = 60)
        kernel.on_block(10, b"\x00" * 32, vrf_out)

        assert kernel._candidate_nonce != candidate_before
        # candidate should equal evolving nonce after update
        assert kernel._candidate_nonce == kernel._evolving_nonce

    def test_candidate_not_updated_outside_window(self, kernel: NodeKernel) -> None:
        """Candidate nonce is NOT updated when block is outside stability window."""
        vrf_out = b"\xcc" * 64

        # First put a block in-window to set a known candidate
        kernel.on_block(5, b"\x00" * 32, b"\x11" * 64)
        candidate_after_first = kernel._candidate_nonce

        # Slot 80 is outside stability window (window = 60 for our params)
        kernel.on_block(80, b"\x00" * 32, vrf_out)

        # candidate should NOT have changed
        assert kernel._candidate_nonce == candidate_after_first
        # But evolving nonce should have changed
        assert kernel._evolving_nonce != candidate_after_first

    def test_lab_nonce_updated_on_block(self, kernel: NodeKernel) -> None:
        """on_block() sets _lab_nonce to the prev_hash of the block."""
        prev_hash = b"\xdd" * 32
        kernel.on_block(10, prev_hash, b"\xee" * 64)
        assert kernel._lab_nonce == prev_hash

    def test_multiple_blocks_accumulate(self, kernel: NodeKernel) -> None:
        """Multiple on_block() calls chain the evolving nonce correctly."""
        evolving_0 = kernel._evolving_nonce

        kernel.on_block(5, b"\x00" * 32, b"\x01" * 64)
        evolving_1 = kernel._evolving_nonce
        assert evolving_1 != evolving_0

        kernel.on_block(10, b"\x00" * 32, b"\x02" * 64)
        evolving_2 = kernel._evolving_nonce
        assert evolving_2 != evolving_1

    def test_stability_window_boundary(self, kernel: NodeKernel) -> None:
        """Verify the stability window cutoff for candidate updates.

        With k=1, f=0.05: stability_window = 3*1/0.05 = 60.
        Slots 0-59 are in-window, slots 60+ are out-of-window.
        """
        window = stability_window(EPOCH_LENGTH, TEST_K, TEST_F)
        assert window == 60

        # Slot at window-1 should update candidate
        kernel.on_block(window - 1, b"\x00" * 32, b"\xaa" * 64)
        candidate_in = kernel._candidate_nonce

        # Slot at window should NOT update candidate
        kernel.on_block(window, b"\x00" * 32, b"\xbb" * 64)
        assert kernel._candidate_nonce == candidate_in


class TestMultipleEpochBoundaries:
    """Test handling of multiple epoch transitions, including skips."""

    def test_sequential_epochs(self, kernel: NodeKernel) -> None:
        """Process epochs 0->1->2->3 sequentially with blocks in each."""
        nonces = [kernel.epoch_nonce]

        for epoch in [1, 2, 3]:
            # Process a block in the current epoch to ensure non-trivial nonce evolution
            base_slot = (epoch - 1) * EPOCH_LENGTH + 5
            kernel.on_block(base_slot, bytes([epoch]) * 32, bytes([epoch + 10]) * 64)

            kernel.on_epoch_boundary(epoch)
            assert kernel.current_epoch == epoch
            nonces.append(kernel.epoch_nonce)

        # All nonces should be distinct (each epoch had a block contributing)
        nonce_values = [n.value for n in nonces]
        assert len(set(nonce_values)) == len(nonce_values), "All nonces should be unique"

    def test_skipped_epoch(self, kernel: NodeKernel) -> None:
        """Handle jumping from epoch 0 directly to epoch 3 (skipping 1, 2).

        This can happen if no blocks were produced in epochs 1 and 2.
        The NodeKernel should still process the jump. When a block was
        processed in epoch 0, the nonce should evolve.
        """
        # Process a block in epoch 0 so lab_nonce is non-neutral
        kernel.on_block(10, b"\xab" * 32, b"\xcd" * 64)
        original_nonce = kernel.epoch_nonce

        kernel.on_epoch_boundary(3)
        assert kernel.current_epoch == 3
        assert kernel.epoch_nonce != original_nonce

    def test_on_block_adopted_handles_epoch_boundary(self, kernel: NodeKernel) -> None:
        """on_block_adopted() triggers epoch boundary when needed."""
        assert kernel.current_epoch == 0

        # Process a block in epoch 0 first so nonce will change
        kernel.on_block(10, b"\x11" * 32, b"\x22" * 64)
        nonce_before = kernel.epoch_nonce

        # Block in epoch 1 should trigger epoch boundary
        kernel.on_block_adopted(
            slot=100,
            block_hash=b"\xaa" * 32,
            prev_hash=b"\xbb" * 32,
            vrf_output=b"\xcc" * 64,
        )

        assert kernel.current_epoch == 1
        assert kernel.epoch_nonce != nonce_before

    def test_on_block_adopted_accumulates_vrf(self, kernel: NodeKernel) -> None:
        """on_block_adopted() calls on_block() with VRF output."""
        evolving_before = kernel._evolving_nonce

        kernel.on_block_adopted(
            slot=10,
            block_hash=b"\xaa" * 32,
            prev_hash=b"\xbb" * 32,
            vrf_output=b"\xcc" * 64,
        )

        assert kernel._evolving_nonce != evolving_before

    def test_nonce_checkpoint_and_restore(self, kernel: NodeKernel) -> None:
        """Nonce checkpoints support fork switch rollback."""
        # Process a block to create a checkpoint
        kernel.on_block_adopted(
            slot=10,
            block_hash=b"\xaa" * 32,
            prev_hash=b"\xbb" * 32,
            vrf_output=b"\xcc" * 64,
        )
        evolving_after_first = kernel._evolving_nonce

        # Process another block
        kernel.on_block_adopted(
            slot=20,
            block_hash=b"\xdd" * 32,
            prev_hash=b"\xaa" * 32,
            vrf_output=b"\xee" * 64,
        )
        assert kernel._evolving_nonce != evolving_after_first

        # Rollback to first block's checkpoint
        ok = kernel._restore_nonce_checkpoint(b"\xaa" * 32)
        assert ok
        assert kernel._evolving_nonce == evolving_after_first
