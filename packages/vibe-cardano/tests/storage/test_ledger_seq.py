"""LedgerSeq tests — anchored PraosState checkpoint sequence.

Covers:
- Empty seq tip is anchor state
- extend changes tip, is pure (doesn't mutate original)
- rollback 1, rollback all, rollback too many (None)
- rollback then extend on different fork -> different nonce
- GC trims beyond max_rollback, preserves rollback within k
- extend across epoch boundary ticks epoch
- rollback across epoch restores epoch
- rollback_to_hash for anchor, for checkpoint, for missing hash

Haskell references:
    Ouroboros.Consensus.Storage.LedgerDB.LedgerSeq
    Test.Ouroboros.Storage.LedgerDB

Antithesis compatibility:
    All tests use deterministic data and can be replayed.
"""

from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.consensus.praos_state import genesis_praos_state
from vibe.cardano.storage.ledger_seq import LedgerSeq

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GENESIS_HASH = b"\xaa" * 32
EPOCH_LENGTH = 100
SECURITY_PARAM = 10
ACTIVE_SLOT_COEFF = 0.05


def _anchor() -> tuple:
    """Return (genesis_state, genesis_hash) for tests."""
    state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, SECURITY_PARAM, ACTIVE_SLOT_COEFF)
    return state, GENESIS_HASH


def _block_hash(n: int) -> bytes:
    """Deterministic block hash from integer."""
    return hashlib.blake2b(n.to_bytes(8, "big"), digest_size=32).digest()


def _vrf_output(n: int) -> bytes:
    """Deterministic VRF output from integer."""
    return hashlib.blake2b(b"vrf" + n.to_bytes(8, "big"), digest_size=32).digest()


def _make_seq(max_rollback: int = 5) -> LedgerSeq:
    """Create an empty LedgerSeq with genesis anchor."""
    state, ghash = _anchor()
    return LedgerSeq(anchor_state=state, anchor_hash=ghash, max_rollback=max_rollback)


def _extend_n(seq: LedgerSeq, start_slot: int, count: int) -> LedgerSeq:
    """Extend seq with `count` blocks starting at `start_slot`."""
    for i in range(count):
        slot = start_slot + i
        bh = _block_hash(slot)
        prev = seq.tip_hash()
        vrf = _vrf_output(slot)
        seq = seq.extend(slot=slot, block_hash=bh, prev_hash=prev, vrf_output=vrf)
    return seq


# ---------------------------------------------------------------------------
# Tests: basic properties
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_tip_is_anchor_state(self):
        state, ghash = _anchor()
        seq = LedgerSeq(anchor_state=state, anchor_hash=ghash, max_rollback=5)
        assert seq.tip_state() is state
        assert seq.tip_hash() == ghash

    def test_length_is_zero(self):
        seq = _make_seq()
        assert seq.length() == 0


class TestExtend:
    def test_extend_changes_tip(self):
        seq = _make_seq()
        bh = _block_hash(1)
        new_seq = seq.extend(slot=1, block_hash=bh, prev_hash=seq.tip_hash(), vrf_output=_vrf_output(1))
        assert new_seq.tip_hash() == bh
        assert new_seq.length() == 1

    def test_extend_is_pure(self):
        """Original seq is not mutated by extend."""
        seq = _make_seq()
        original_tip = seq.tip_hash()
        _ = seq.extend(slot=1, block_hash=_block_hash(1), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(1))
        assert seq.tip_hash() == original_tip
        assert seq.length() == 0

    def test_extend_updates_praos_state(self):
        """After extend, the tip state should differ from anchor."""
        state, _ = _anchor()
        seq = _make_seq()
        new_seq = seq.extend(slot=1, block_hash=_block_hash(1), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(1))
        assert new_seq.tip_state() != state


# ---------------------------------------------------------------------------
# Tests: rollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_one(self):
        seq = _extend_n(_make_seq(), 1, 3)
        assert seq.length() == 3
        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.length() == 2

    def test_rollback_all(self):
        seq = _extend_n(_make_seq(), 1, 3)
        rolled = seq.rollback(3)
        assert rolled is not None
        assert rolled.length() == 0
        # Tip should be anchor
        state, ghash = _anchor()
        assert rolled.tip_hash() == ghash

    def test_rollback_too_many_returns_none(self):
        seq = _extend_n(_make_seq(), 1, 3)
        assert seq.rollback(4) is None

    def test_rollback_zero(self):
        seq = _extend_n(_make_seq(), 1, 3)
        rolled = seq.rollback(0)
        assert rolled is not None
        assert rolled.length() == 3
        assert rolled.tip_hash() == seq.tip_hash()

    def test_rollback_restores_state(self):
        """Rolling back should restore the nonce state to that checkpoint."""
        seq = _extend_n(_make_seq(), 1, 3)
        after_2 = _extend_n(_make_seq(), 1, 2)
        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.tip_state() == after_2.tip_state()


class TestRollbackThenExtendFork:
    def test_fork_produces_different_nonce(self):
        """Rollback then extend with different VRF -> different nonce."""
        seq = _extend_n(_make_seq(), 1, 3)
        rolled = seq.rollback(1)
        assert rolled is not None

        # Extend on a fork with a different VRF output
        fork_vrf = _vrf_output(999)
        fork_hash = _block_hash(999)
        forked = rolled.extend(slot=3, block_hash=fork_hash, prev_hash=rolled.tip_hash(), vrf_output=fork_vrf)

        # The nonce state should differ from the original chain
        assert forked.tip_state().evolving_nonce != seq.tip_state().evolving_nonce


# ---------------------------------------------------------------------------
# Tests: GC
# ---------------------------------------------------------------------------


class TestGC:
    def test_gc_trims_beyond_max_rollback(self):
        seq = _make_seq(max_rollback=3)
        seq = _extend_n(seq, 1, 6)
        # After 6 extends with max_rollback=3, length should be 3
        assert seq.length() == 3

    def test_gc_preserves_rollback_within_k(self):
        seq = _make_seq(max_rollback=3)
        seq = _extend_n(seq, 1, 6)
        # Can still rollback up to 3
        rolled = seq.rollback(3)
        assert rolled is not None
        assert rolled.length() == 0

    def test_gc_advances_anchor(self):
        """After GC, the anchor should have advanced from genesis."""
        state, ghash = _anchor()
        seq = _make_seq(max_rollback=2)
        seq = _extend_n(seq, 1, 5)
        # Anchor should no longer be genesis
        assert seq.tip_hash() != ghash
        # Rolling back max should give non-genesis anchor
        rolled = seq.rollback(2)
        assert rolled is not None
        assert rolled.tip_hash() != ghash


# ---------------------------------------------------------------------------
# Tests: epoch boundary
# ---------------------------------------------------------------------------


class TestEpochBoundary:
    def test_extend_across_epoch_ticks(self):
        """Extending into a new epoch should tick the epoch."""
        seq = _make_seq()
        # Fill epoch 0 with a block near the end
        seq = seq.extend(slot=99, block_hash=_block_hash(99), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(99))
        assert seq.tip_state().current_epoch == 0

        # Block in epoch 1
        seq = seq.extend(slot=100, block_hash=_block_hash(100), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(100))
        assert seq.tip_state().current_epoch == 1

    def test_rollback_across_epoch_restores_epoch(self):
        """Rolling back across an epoch boundary restores the previous epoch."""
        seq = _make_seq()
        seq = seq.extend(slot=99, block_hash=_block_hash(99), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(99))
        seq = seq.extend(slot=100, block_hash=_block_hash(100), prev_hash=seq.tip_hash(), vrf_output=_vrf_output(100))
        assert seq.tip_state().current_epoch == 1

        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.tip_state().current_epoch == 0


# ---------------------------------------------------------------------------
# Tests: rollback_to_hash
# ---------------------------------------------------------------------------


class TestRollbackToHash:
    def test_rollback_to_anchor_hash(self):
        _, ghash = _anchor()
        seq = _extend_n(_make_seq(), 1, 3)
        rolled = seq.rollback_to_hash(ghash)
        assert rolled is not None
        assert rolled.length() == 0
        assert rolled.tip_hash() == ghash

    def test_rollback_to_checkpoint_hash(self):
        seq = _make_seq()
        # Extend 3 blocks
        hashes = []
        for i in range(1, 4):
            bh = _block_hash(i)
            hashes.append(bh)
            seq = seq.extend(slot=i, block_hash=bh, prev_hash=seq.tip_hash(), vrf_output=_vrf_output(i))

        # Rollback to 2nd block
        rolled = seq.rollback_to_hash(hashes[1])
        assert rolled is not None
        assert rolled.length() == 2
        assert rolled.tip_hash() == hashes[1]

    def test_rollback_to_missing_hash_returns_none(self):
        seq = _extend_n(_make_seq(), 1, 3)
        assert seq.rollback_to_hash(b"\xff" * 32) is None


# ---------------------------------------------------------------------------
# Tests: find_hash
# ---------------------------------------------------------------------------


class TestFindHash:
    def test_find_existing(self):
        seq = _make_seq()
        hashes = []
        for i in range(1, 4):
            bh = _block_hash(i)
            hashes.append(bh)
            seq = seq.extend(slot=i, block_hash=bh, prev_hash=seq.tip_hash(), vrf_output=_vrf_output(i))

        assert seq.find_hash(hashes[0]) == 0
        assert seq.find_hash(hashes[1]) == 1
        assert seq.find_hash(hashes[2]) == 2

    def test_find_missing(self):
        seq = _extend_n(_make_seq(), 1, 3)
        assert seq.find_hash(b"\xff" * 32) is None

    def test_find_anchor_hash_not_in_checkpoints(self):
        """Anchor hash is not a checkpoint, so find_hash should not find it."""
        _, ghash = _anchor()
        seq = _extend_n(_make_seq(), 1, 2)
        assert seq.find_hash(ghash) is None
