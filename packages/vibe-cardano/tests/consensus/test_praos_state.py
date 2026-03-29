"""Tests for PraosState dataclass and pure update functions.

TDD tests for the pure nonce-tracking state machine that will be
integrated into ChainDB for atomic nonce updates.

Spec references:
    - Ouroboros Praos paper, Section 7 (Nonce evolution)
    - Shelley ledger formal spec, Section 11.1
    - Haskell: Ouroboros.Consensus.Protocol.Praos (tickChainDepState, reupdateChainDepState)
"""

from __future__ import annotations

import hashlib
import math
from struct import pack

import pytest

from vibe.cardano.consensus.praos_state import (
    PraosState,
    _combine,
    genesis_praos_state,
    reupdate_praos_state,
    tick_praos_state,
)
from vibe.cardano.crypto.vrf import vrf_nonce_value


# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------

NEUTRAL = b"\x00" * 32
GENESIS_HASH = hashlib.blake2b(b"genesis", digest_size=32).digest()
EPOCH_LENGTH = 100
SECURITY_PARAM = 1
ACTIVE_SLOT_COEFF = 0.5  # stability window = ceil(4*1/0.5) = 8
# Haskell formula: slot + 8 < 100 → slots 0-91 inside, 92+ outside


# ---------------------------------------------------------------------------
# _combine tests
# ---------------------------------------------------------------------------


class TestCombine:
    """Tests for the _combine(a, b) helper."""

    def test_neutral_left_returns_b(self):
        b = hashlib.blake2b(b"some_value", digest_size=32).digest()
        assert _combine(NEUTRAL, b) == b

    def test_neutral_right_returns_a(self):
        a = hashlib.blake2b(b"some_value", digest_size=32).digest()
        assert _combine(a, NEUTRAL) == a

    def test_both_neutral_returns_neutral(self):
        # neutral + neutral: a is neutral -> return b (neutral)
        assert _combine(NEUTRAL, NEUTRAL) == NEUTRAL

    def test_both_non_neutral_hashes(self):
        a = hashlib.blake2b(b"a", digest_size=32).digest()
        b = hashlib.blake2b(b"b", digest_size=32).digest()
        expected = hashlib.blake2b(a + b, digest_size=32).digest()
        assert _combine(a, b) == expected

    def test_not_commutative(self):
        a = hashlib.blake2b(b"a", digest_size=32).digest()
        b = hashlib.blake2b(b"b", digest_size=32).digest()
        assert _combine(a, b) != _combine(b, a)


# ---------------------------------------------------------------------------
# genesis_praos_state tests
# ---------------------------------------------------------------------------


class TestGenesisPraosState:
    """Tests for genesis_praos_state factory."""

    def test_initial_nonces_set_to_genesis_hash(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert state.epoch_nonce == GENESIS_HASH
        assert state.evolving_nonce == GENESIS_HASH
        assert state.candidate_nonce == GENESIS_HASH

    def test_lab_nonce_is_neutral(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert state.lab_nonce == NEUTRAL

    def test_last_epoch_block_nonce_is_neutral(self):
        """Haskell: ticknStatePrevHashNonce starts as NeutralNonce."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert state.last_epoch_block_nonce == NEUTRAL

    def test_current_epoch_is_zero(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert state.current_epoch == 0

    def test_params_stored(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert state.epoch_length == EPOCH_LENGTH
        assert state.security_param == SECURITY_PARAM
        assert state.active_slot_coeff == ACTIVE_SLOT_COEFF

    def test_frozen_immutable(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        with pytest.raises(AttributeError):
            state.epoch_nonce = b"\xff" * 32  # type: ignore[misc]


# ---------------------------------------------------------------------------
# reupdate_praos_state tests
# ---------------------------------------------------------------------------


class TestReupdatePraosState:
    """Tests for reupdate_praos_state (per-block nonce update)."""

    def _make_vrf_output(self, seed: bytes) -> bytes:
        """Create a fake 64-byte VRF output."""
        return hashlib.blake2b(seed, digest_size=64).digest()

    def test_evolving_nonce_updated(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"block1")
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)

        nonce_val = vrf_nonce_value(vrf_out)
        expected_evolving = _combine(state.evolving_nonce, nonce_val)
        assert new_state.evolving_nonce == expected_evolving

    def test_candidate_nonce_updated_inside_stability_window(self):
        """Slot inside stability window -> candidate_nonce is updated."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"block1")
        # stability window = min(ceil(4*10/0.5), 100) = min(80, 100) = 80
        # slot 5 is inside window (slot_in_epoch=5 < 80)
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)

        nonce_val = vrf_nonce_value(vrf_out)
        expected_candidate = _combine(state.candidate_nonce, nonce_val)
        assert new_state.candidate_nonce == expected_candidate

    def test_candidate_nonce_not_updated_outside_stability_window(self):
        """Slot outside stability window -> candidate_nonce unchanged.

        window=8, firstSlotNextEpoch=100: slot 95 + 8 = 103 >= 100 → outside.
        """
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"block_late")
        new_state = reupdate_praos_state(state, slot=95, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)

        # candidate should be unchanged
        assert new_state.candidate_nonce == state.candidate_nonce
        # but evolving should still be updated
        assert new_state.evolving_nonce != state.evolving_nonce

    def test_lab_nonce_set_to_prev_hash(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        prev_hash = hashlib.blake2b(b"prev_block", digest_size=32).digest()
        vrf_out = self._make_vrf_output(b"block1")
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=prev_hash, vrf_output=vrf_out)
        assert new_state.lab_nonce == prev_hash

    def test_lab_nonce_neutral_when_prev_hash_all_zeros(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"block1")
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=NEUTRAL, vrf_output=vrf_out)
        assert new_state.lab_nonce == NEUTRAL

    def test_returns_new_state_not_mutated(self):
        """Verify pure function -- original state not mutated."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        original_evolving = state.evolving_nonce
        vrf_out = self._make_vrf_output(b"block1")
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)

        assert state.evolving_nonce == original_evolving  # original unchanged
        assert new_state is not state
        assert new_state.evolving_nonce != state.evolving_nonce

    def test_epoch_nonce_unchanged(self):
        """Per-block update should NOT touch epoch_nonce."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"block1")
        new_state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert new_state.epoch_nonce == state.epoch_nonce

    def test_stability_window_boundary_exact(self):
        """Slot at boundary is OUTSIDE the window.

        Haskell: slot + window < firstSlotNextEpoch
        window=8, firstSlot=100: slot 92 + 8 = 100, NOT < 100 → outside.
        """
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"boundary")
        new_state = reupdate_praos_state(state, slot=92, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert new_state.candidate_nonce == state.candidate_nonce

    def test_stability_window_one_before_boundary(self):
        """Slot one before boundary is INSIDE the window.

        slot 91 + 8 = 99 < 100 → inside.
        """
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        vrf_out = self._make_vrf_output(b"just_inside")
        new_state = reupdate_praos_state(state, slot=91, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert new_state.candidate_nonce != state.candidate_nonce


# ---------------------------------------------------------------------------
# tick_praos_state tests
# ---------------------------------------------------------------------------


class TestTickPraosState:
    """Tests for tick_praos_state (epoch boundary nonce evolution)."""

    def test_epoch0_to_epoch1_retains_genesis_nonce(self):
        """Epoch 0->1 transition: epoch_nonce stays as genesis nonce."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        new_state = tick_praos_state(state, new_epoch=1)

        assert new_state.epoch_nonce == state.epoch_nonce  # retained
        assert new_state.current_epoch == 1

    def test_epoch1_to_epoch2_evolves_nonce(self):
        """Epoch 1->2: epoch_nonce = combine(candidate_nonce, last_epoch_block_nonce)."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        # Simulate epoch 1
        state1 = tick_praos_state(state, new_epoch=1)

        # Now tick to epoch 2
        state2 = tick_praos_state(state1, new_epoch=2)

        expected_nonce = _combine(state1.candidate_nonce, state1.last_epoch_block_nonce)
        assert state2.epoch_nonce == expected_nonce

    def test_last_epoch_block_nonce_set_to_lab_nonce(self):
        """At tick: last_epoch_block_nonce = lab_nonce from previous state."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        new_state = tick_praos_state(state, new_epoch=1)
        assert new_state.last_epoch_block_nonce == state.lab_nonce

    def test_evolving_and_candidate_reset_to_new_epoch_nonce(self):
        """At tick: evolving_nonce and candidate_nonce reset to new epoch_nonce."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        state1 = tick_praos_state(state, new_epoch=1)

        assert state1.evolving_nonce == state1.epoch_nonce
        assert state1.candidate_nonce == state1.epoch_nonce

    def test_lab_nonce_carries_over(self):
        """At tick: lab_nonce carries over (Haskell doesn't reset it)."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        # Add a block to set lab_nonce to something non-neutral
        vrf_out = hashlib.blake2b(b"blk", digest_size=64).digest()
        state = reupdate_praos_state(state, slot=5, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert state.lab_nonce != NEUTRAL

        new_state = tick_praos_state(state, new_epoch=1)
        assert new_state.lab_nonce == state.lab_nonce  # Carries over

    def test_extra_entropy_mixed_in(self):
        """Extra entropy should be mixed into epoch_nonce for N>0 transitions."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        state1 = tick_praos_state(state, new_epoch=1)

        extra = hashlib.blake2b(b"extra", digest_size=32).digest()
        state2_with = tick_praos_state(state1, new_epoch=2, extra_entropy=extra)
        state2_without = tick_praos_state(state1, new_epoch=2)

        assert state2_with.epoch_nonce != state2_without.epoch_nonce

    def test_pure_no_mutation(self):
        """tick should return new state, not mutate the old one."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        original_epoch = state.current_epoch
        new_state = tick_praos_state(state, new_epoch=1)

        assert state.current_epoch == original_epoch
        assert new_state.current_epoch == 1

    def test_params_preserved(self):
        """Epoch/security/active_slot params should carry through tick."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        new_state = tick_praos_state(state, new_epoch=1)
        assert new_state.epoch_length == EPOCH_LENGTH
        assert new_state.security_param == SECURITY_PARAM
        assert new_state.active_slot_coeff == ACTIVE_SLOT_COEFF


# ---------------------------------------------------------------------------
# Integration: multi-block, multi-epoch sequence
# ---------------------------------------------------------------------------


class TestMultiEpochSequence:
    """End-to-end test: genesis -> blocks in epoch 0 -> tick to epoch 1 -> blocks -> tick to epoch 2."""

    def test_full_sequence(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)

        # Process 3 blocks in epoch 0 (all inside stability window)
        for i in range(3):
            vrf_out = hashlib.blake2b(f"epoch0_block{i}".encode(), digest_size=64).digest()
            prev = b"\x00" * 32 if i == 0 else hashlib.blake2b(f"hash{i-1}".encode(), digest_size=32).digest()
            blk_hash = hashlib.blake2b(f"hash{i}".encode(), digest_size=32).digest()
            state = reupdate_praos_state(state, slot=i * 10, block_hash=blk_hash, prev_hash=prev, vrf_output=vrf_out)

        # Verify evolving nonce has been updated from genesis
        assert state.evolving_nonce != GENESIS_HASH
        # candidate also updated (slots 0, 10, 20 all < 80)
        assert state.candidate_nonce != GENESIS_HASH

        # Tick to epoch 1 — same formula as all epochs:
        # epoch_nonce = candidate ⭒ lastEpochBlockNonce
        # lastEpochBlockNonce is NeutralNonce (initial), so:
        # epoch_nonce = candidate ⭒ NeutralNonce = candidate
        epoch0_state = state
        state = tick_praos_state(state, new_epoch=1)
        assert state.epoch_nonce == epoch0_state.candidate_nonce
        assert state.current_epoch == 1
        # last_epoch_block_nonce now set from lab_nonce of epoch 0
        assert state.last_epoch_block_nonce == epoch0_state.lab_nonce

        # Process 2 blocks in epoch 1
        for i in range(2):
            vrf_out = hashlib.blake2b(f"epoch1_block{i}".encode(), digest_size=64).digest()
            prev = hashlib.blake2b(f"prev_e1_{i}".encode(), digest_size=32).digest()
            blk_hash = hashlib.blake2b(f"hash_e1_{i}".encode(), digest_size=32).digest()
            state = reupdate_praos_state(state, slot=100 + i * 10, block_hash=blk_hash, prev_hash=prev, vrf_output=vrf_out)

        # Tick to epoch 2 -- NOW nonce evolves
        epoch1_state = state
        state = tick_praos_state(state, new_epoch=2)
        expected = _combine(epoch1_state.candidate_nonce, epoch1_state.last_epoch_block_nonce)
        assert state.epoch_nonce == expected
        assert state.current_epoch == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_stability_window_exceeds_epoch_no_candidate_update(self):
        """When ceil(4k/f) > epoch_length, candidate nonce never updates.

        Haskell: slot + window < firstSlotNextEpoch is never true when
        window > epoch_length. The candidate nonce stays frozen at genesis.
        """
        # k=100, f=0.1 -> window = ceil(4*100/0.1) = 4000, epoch_length=50
        # slot + 4000 < 50 is never true
        state = genesis_praos_state(GENESIS_HASH, epoch_length=50, security_param=100, active_slot_coeff=0.1)
        vrf_out = hashlib.blake2b(b"last_slot", digest_size=64).digest()
        new_state = reupdate_praos_state(state, slot=49, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert new_state.candidate_nonce == state.candidate_nonce  # NOT updated

    def test_stability_window_uses_math_ceil(self):
        """Verify ceil is used, not floor or round.

        Haskell: slot + window < firstSlotNextEpoch
        k=10, f=0.3 -> window = ceil(4*10/0.3) = ceil(133.33) = 134
        epoch_length=200, firstSlotNextEpoch=200
        Boundary: slot + 134 < 200 → slot < 66
        """
        state = genesis_praos_state(GENESIS_HASH, epoch_length=200, security_param=10, active_slot_coeff=0.3)
        vrf_out = hashlib.blake2b(b"at_65", digest_size=64).digest()

        # slot 65: 65 + 134 = 199 < 200 → inside
        s65 = reupdate_praos_state(state, slot=65, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert s65.candidate_nonce != state.candidate_nonce

        # slot 66: 66 + 134 = 200, NOT < 200 → outside
        s66 = reupdate_praos_state(state, slot=66, block_hash=b"\x01" * 32, prev_hash=b"\x02" * 32, vrf_output=vrf_out)
        assert s66.candidate_nonce == state.candidate_nonce

    def test_32_byte_fields(self):
        """All nonce fields should be 32 bytes."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
        assert len(state.epoch_nonce) == 32
        assert len(state.evolving_nonce) == 32
        assert len(state.candidate_nonce) == 32
        assert len(state.lab_nonce) == 32
        assert len(state.last_epoch_block_nonce) == 32
