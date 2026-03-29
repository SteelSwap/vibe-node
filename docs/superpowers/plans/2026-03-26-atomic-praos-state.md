# Atomic PraosState in ChainDB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed PraosState (epoch nonces) inside ChainDB's per-block checkpoints so that chain selection and nonce updates are atomic — eliminating the fork-induced nonce drift that causes VRFKeyBadProof rejections from Haskell peers.

**Architecture:** Move nonce state ownership from `NodeKernel` into `ChainDB` as part of per-block `ExtLedgerState` checkpoints. Chain selection computes the new nonce state during `add_block()` itself — rollback drops checkpoints (restoring old nonce), re-apply recomputes nonces via `reupdateChainDepState`. The forge loop reads the tip nonce from a TVar that ChainDB updates atomically with the chain fragment. No separate nonce checkpoint dict, no races between threads.

**Tech Stack:** Python 3.14, existing vibe-node storage and consensus modules, STM TVars for cross-thread reads.

**Haskell reference:**
- `Ouroboros.Consensus.Storage.ChainDB.Impl.ChainSel.switchTo` — atomic commit of chain + ledger
- `Ouroboros.Consensus.Ledger.Extended.ExtLedgerState` — ledger + ChainDepState bundled
- `Ouroboros.Consensus.Storage.LedgerDB` — `AnchoredSeq` of `ExtLedgerState` with pure rollback
- `Ouroboros.Consensus.Protocol.Praos.reupdateChainDepState` — pure per-block nonce update

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `packages/vibe-cardano/src/vibe/cardano/consensus/praos_state.py` | **Create** | PraosState dataclass + pure `reupdate` and `tick` functions |
| `packages/vibe-cardano/src/vibe/cardano/storage/ledger_seq.py` | **Create** | `LedgerSeq` — anchored sequence of per-block PraosState checkpoints with pure rollback/extend |
| `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py` | **Modify** | Own a `LedgerSeq`, update it atomically inside `add_block()`, expose tip nonce via TVar |
| `packages/vibe-cardano/src/vibe/cardano/node/kernel.py` | **Modify** | Remove nonce checkpoint dict, read nonce from ChainDB's TVar instead of maintaining own state |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` | **Modify** | Remove `on_block_adopted` / `on_fork_switch` calls after `add_block()` — ChainDB handles it now |
| `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py` | **Modify** | Read nonce from ChainDB's TVar (already does via `node_kernel.nonce_tvar`) — update the source |
| `packages/vibe-cardano/tests/consensus/test_praos_state.py` | **Create** | Unit tests for pure PraosState functions |
| `packages/vibe-cardano/tests/storage/test_ledger_seq.py` | **Create** | Unit tests for LedgerSeq rollback/extend |
| `packages/vibe-cardano/tests/storage/test_chaindb_nonce.py` | **Create** | Integration tests: add_block atomically updates nonce, fork switches roll back correctly |

---

### Task 1: PraosState dataclass and pure update functions

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/consensus/praos_state.py`
- Test: `packages/vibe-cardano/tests/consensus/test_praos_state.py`

This task extracts the nonce math from `NodeKernel` into pure functions that take a `PraosState` and return a new `PraosState`. No mutation, no side effects — exactly matching Haskell's `reupdateChainDepState` and `tickChainDepState`.

- [ ] **Step 1: Write failing tests for PraosState**

```python
# tests/consensus/test_praos_state.py
"""Tests for pure PraosState update functions.

Haskell ref: Ouroboros.Consensus.Protocol.Praos (PraosState, tickChainDepState, reupdateChainDepState)
"""
from __future__ import annotations

import hashlib
import struct

import pytest

from vibe.cardano.consensus.praos_state import (
    PraosState,
    genesis_praos_state,
    reupdate_praos_state,
    tick_praos_state,
)


def _combine(a: bytes, b: bytes) -> bytes:
    """Reference implementation of the nonce ⭒ operator."""
    neutral = b"\x00" * 32
    if a == neutral:
        return b
    if b == neutral:
        return a
    return hashlib.blake2b(a + b, digest_size=32).digest()


def _vrf_nonce(vrf_output: bytes) -> bytes:
    """Reference vrf_nonce_value: double hash with N prefix."""
    inner = hashlib.blake2b(b"N" + vrf_output, digest_size=32).digest()
    return hashlib.blake2b(inner, digest_size=32).digest()


EPOCH_LENGTH = 100
K = 10
F = 0.1
GENESIS_HASH = hashlib.blake2b(b"test-genesis", digest_size=32).digest()


class TestGenesisState:
    def test_genesis_state_has_genesis_nonce(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        assert state.epoch_nonce == GENESIS_HASH
        assert state.evolving_nonce == GENESIS_HASH
        assert state.candidate_nonce == GENESIS_HASH

    def test_genesis_state_epoch_zero(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        assert state.current_epoch == 0

    def test_genesis_last_epoch_block_nonce_is_mkNonceFromNumber_0(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        expected = hashlib.blake2b(struct.pack(">Q", 0), digest_size=32).digest()
        assert state.last_epoch_block_nonce == expected


class TestReupdatePraosState:
    def test_evolving_nonce_accumulates_vrf(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        vrf_out = b"\xaa" * 64
        new_state = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=b"\x00" * 32, vrf_output=vrf_out,
        )
        expected_ev = _combine(state.evolving_nonce, _vrf_nonce(vrf_out))
        assert new_state.evolving_nonce == expected_ev

    def test_lab_nonce_set_to_prev_hash(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        prev_hash = b"\xdd" * 32
        new_state = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=prev_hash, vrf_output=b"\xaa" * 64,
        )
        assert new_state.lab_nonce == prev_hash

    def test_candidate_nonce_updated_in_stability_window(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        new_state = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=b"\x00" * 32, vrf_output=b"\xbb" * 64,
        )
        assert new_state.candidate_nonce == new_state.evolving_nonce

    def test_reupdate_is_pure(self):
        """Calling reupdate does not mutate the original state."""
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        orig_ev = state.evolving_nonce
        _ = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=b"\x00" * 32, vrf_output=b"\xaa" * 64,
        )
        assert state.evolving_nonce == orig_ev


class TestTickPraosState:
    def test_epoch_0_to_1_retains_genesis_nonce(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        state2 = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=b"\x00" * 32, vrf_output=b"\xaa" * 64,
        )
        ticked = tick_praos_state(state2, new_epoch=1)
        assert ticked.epoch_nonce == GENESIS_HASH  # Retained
        assert ticked.current_epoch == 1

    def test_epoch_1_to_2_evolves_nonce(self):
        state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
        state = reupdate_praos_state(
            state, slot=10, block_hash=b"\x01" * 32,
            prev_hash=b"\x00" * 32, vrf_output=b"\xaa" * 64,
        )
        state = tick_praos_state(state, new_epoch=1)
        state = reupdate_praos_state(
            state, slot=110, block_hash=b"\x02" * 32,
            prev_hash=b"\x01" * 32, vrf_output=b"\xbb" * 64,
        )
        ticked = tick_praos_state(state, new_epoch=2)
        expected = _combine(state.candidate_nonce, state.last_epoch_block_nonce)
        assert ticked.epoch_nonce == expected
        assert ticked.current_epoch == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/consensus/test_praos_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vibe.cardano.consensus.praos_state'`

- [ ] **Step 3: Implement PraosState**

```python
# packages/vibe-cardano/src/vibe/cardano/consensus/praos_state.py
"""Pure PraosState — the Praos chain-dependent nonce state.

All functions are pure: they take a PraosState and return a new one.
No mutation, no I/O, no shared state. This matches Haskell's approach
where PraosState is part of the immutable ExtLedgerState stored in
LedgerDB checkpoints.

Haskell ref:
    Ouroboros.Consensus.Protocol.Praos (PraosState)
    reupdateChainDepState — per-block nonce update
    tickChainDepState — epoch boundary nonce evolution
"""
from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass

from vibe.cardano.crypto.vrf import vrf_nonce_value

__all__ = [
    "PraosState",
    "genesis_praos_state",
    "reupdate_praos_state",
    "tick_praos_state",
]


@dataclass(frozen=True, slots=True)
class PraosState:
    """Immutable snapshot of Praos chain-dependent nonce state.

    Haskell ref: PraosState in Ouroboros.Consensus.Protocol.Praos
    """
    epoch_nonce: bytes          # 32 bytes — the active epoch nonce for VRF
    evolving_nonce: bytes       # 32 bytes — accumulates every block's VRF
    candidate_nonce: bytes      # 32 bytes — freezes at stability window
    lab_nonce: bytes            # 32 bytes — prevHashToNonce(block.prevHash)
    last_epoch_block_nonce: bytes  # 32 bytes — lab_nonce snapshot at epoch boundary
    current_epoch: int
    epoch_length: int
    security_param: int
    active_slot_coeff: float


def _combine(a: bytes, b: bytes) -> bytes:
    """Nonce combination operator (⭒).

    Haskell ref: (⭒) in Cardano.Ledger.BaseTypes
    """
    neutral = b"\x00" * 32
    if a == neutral:
        return b
    if b == neutral:
        return a
    return hashlib.blake2b(a + b, digest_size=32).digest()


def _randomness_stabilisation_window(epoch_length: int, k: int, f: float) -> int:
    """Praos randomness stabilisation window: ceil(4k/f), capped at epoch_length.

    Haskell ref: computeRandomnessStabilisationWindow
    """
    if k > 0 and f > 0.0:
        return min(math.ceil(4 * k / f), epoch_length)
    return (epoch_length * 2) // 3


def genesis_praos_state(
    genesis_hash: bytes,
    epoch_length: int,
    security_param: int,
    active_slot_coeff: float,
) -> PraosState:
    """Create the initial PraosState from genesis.

    Haskell ref: translateChainDepStateByronToShelley
    """
    return PraosState(
        epoch_nonce=genesis_hash,
        evolving_nonce=genesis_hash,
        candidate_nonce=genesis_hash,
        lab_nonce=b"\x00" * 32,
        last_epoch_block_nonce=hashlib.blake2b(
            struct.pack(">Q", 0), digest_size=32,
        ).digest(),
        current_epoch=0,
        epoch_length=epoch_length,
        security_param=security_param,
        active_slot_coeff=active_slot_coeff,
    )


def reupdate_praos_state(
    state: PraosState,
    slot: int,
    block_hash: bytes,
    prev_hash: bytes,
    vrf_output: bytes,
) -> PraosState:
    """Apply a block's VRF contribution to the nonce state (pure).

    Haskell ref: reupdateChainDepState in Praos.hs
    """
    vrf_nonce = vrf_nonce_value(vrf_output)
    new_evolving = _combine(state.evolving_nonce, vrf_nonce)

    epoch_len = state.epoch_length
    block_epoch = slot // epoch_len
    first_slot_next_epoch = (block_epoch + 1) * epoch_len
    stab_window = _randomness_stabilisation_window(
        epoch_len, state.security_param, state.active_slot_coeff,
    )

    if stab_window >= epoch_len or slot + stab_window < first_slot_next_epoch:
        new_candidate = new_evolving
    else:
        new_candidate = state.candidate_nonce

    # labNonce = prevHashToNonce(block.prevHash)
    new_lab = b"\x00" * 32 if prev_hash == b"\x00" * 32 else prev_hash

    return PraosState(
        epoch_nonce=state.epoch_nonce,
        evolving_nonce=new_evolving,
        candidate_nonce=new_candidate,
        lab_nonce=new_lab,
        last_epoch_block_nonce=state.last_epoch_block_nonce,
        current_epoch=state.current_epoch,
        epoch_length=state.epoch_length,
        security_param=state.security_param,
        active_slot_coeff=state.active_slot_coeff,
    )


def tick_praos_state(
    state: PraosState,
    new_epoch: int,
    extra_entropy: bytes | None = None,
) -> PraosState:
    """Evolve the epoch nonce at an epoch boundary (pure).

    Haskell ref: tickChainDepState in Praos.hs
    """
    if new_epoch <= state.current_epoch:
        return state

    # Epoch 0->1: retain genesis nonce (stabilization lag)
    if state.current_epoch == 0:
        return PraosState(
            epoch_nonce=state.epoch_nonce,  # Retained
            evolving_nonce=state.evolving_nonce,
            candidate_nonce=state.candidate_nonce,
            lab_nonce=state.lab_nonce,
            last_epoch_block_nonce=state.lab_nonce,
            current_epoch=new_epoch,
            epoch_length=state.epoch_length,
            security_param=state.security_param,
            active_slot_coeff=state.active_slot_coeff,
        )

    new_nonce = _combine(state.candidate_nonce, state.last_epoch_block_nonce)
    if extra_entropy is not None:
        new_nonce = _combine(new_nonce, extra_entropy)

    return PraosState(
        epoch_nonce=new_nonce,
        evolving_nonce=state.evolving_nonce,
        candidate_nonce=state.candidate_nonce,
        lab_nonce=state.lab_nonce,
        last_epoch_block_nonce=state.lab_nonce,
        current_epoch=new_epoch,
        epoch_length=state.epoch_length,
        security_param=state.security_param,
        active_slot_coeff=state.active_slot_coeff,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/consensus/test_praos_state.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/consensus/praos_state.py packages/vibe-cardano/tests/consensus/test_praos_state.py
git commit -m "feat: pure PraosState dataclass with reupdate and tick functions

Extract nonce math from NodeKernel into pure, immutable functions
matching Haskell's reupdateChainDepState and tickChainDepState.
No mutation, no side effects — foundation for atomic nonce updates
inside ChainDB chain selection.

Prompt: Implement PraosState as a frozen dataclass with pure
reupdate_praos_state and tick_praos_state functions to replace
NodeKernel's mutable nonce state.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: LedgerSeq — anchored sequence of PraosState checkpoints

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/storage/ledger_seq.py`
- Test: `packages/vibe-cardano/tests/storage/test_ledger_seq.py`

This is the equivalent of Haskell's `LedgerDB` — a sequence of per-block PraosState snapshots with O(1) rollback (drop N newest) and O(n) extend (append new checkpoints).

- [ ] **Step 1: Write failing tests for LedgerSeq**

```python
# tests/storage/test_ledger_seq.py
"""Tests for LedgerSeq — anchored PraosState checkpoint sequence.

Haskell ref: Ouroboros.Consensus.Storage.LedgerDB (LedgerDB, rollback, ledgerDbPush)
"""
from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.consensus.praos_state import (
    PraosState,
    genesis_praos_state,
    reupdate_praos_state,
)
from vibe.cardano.storage.ledger_seq import LedgerSeq

EPOCH_LENGTH = 100
K = 10
F = 0.1
GENESIS_HASH = hashlib.blake2b(b"test-genesis", digest_size=32).digest()


def _make_genesis_seq() -> LedgerSeq:
    state = genesis_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
    return LedgerSeq(anchor_state=state, anchor_hash=b"\x00" * 32, max_rollback=K)


def _apply_block(seq: LedgerSeq, slot: int, block_hash: bytes, prev_hash: bytes, vrf: bytes) -> LedgerSeq:
    return seq.extend(slot=slot, block_hash=block_hash, prev_hash=prev_hash, vrf_output=vrf)


class TestLedgerSeqBasics:
    def test_empty_seq_tip_is_anchor(self):
        seq = _make_genesis_seq()
        assert seq.tip_state().epoch_nonce == GENESIS_HASH

    def test_extend_changes_tip(self):
        seq = _make_genesis_seq()
        seq2 = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        assert seq2.tip_state() != seq.tip_state()
        assert seq2.length() == 1

    def test_extend_is_pure(self):
        """Original seq is not mutated."""
        seq = _make_genesis_seq()
        orig_tip = seq.tip_state()
        _ = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        assert seq.tip_state() == orig_tip


class TestLedgerSeqRollback:
    def test_rollback_one(self):
        seq = _make_genesis_seq()
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        seq = _apply_block(seq, 20, b"\x02" * 32, b"\x01" * 32, b"\xbb" * 64)
        tip_before_rollback = seq.tip_state()

        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.length() == 1
        assert rolled.tip_state() != tip_before_rollback

    def test_rollback_all(self):
        seq = _make_genesis_seq()
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.length() == 0
        assert rolled.tip_state().epoch_nonce == GENESIS_HASH

    def test_rollback_too_many_returns_none(self):
        seq = _make_genesis_seq()
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        assert seq.rollback(2) is None

    def test_rollback_then_extend_different_fork(self):
        seq = _make_genesis_seq()
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        seq = _apply_block(seq, 20, b"\x02" * 32, b"\x01" * 32, b"\xbb" * 64)

        # Roll back 1 block, extend with different block at same slot
        rolled = seq.rollback(1)
        assert rolled is not None
        forked = _apply_block(rolled, 20, b"\x03" * 32, b"\x01" * 32, b"\xcc" * 64)

        # Different VRF → different nonce
        assert forked.tip_state().evolving_nonce != seq.tip_state().evolving_nonce


class TestLedgerSeqGC:
    def test_gc_trims_beyond_max_rollback(self):
        seq = _make_genesis_seq()
        for i in range(K + 5):
            seq = _apply_block(
                seq, i * 10, bytes([i + 1]) * 32,
                bytes([i]) * 32, bytes([i + 50]) * 64,
            )
        # Should have at most K checkpoints (older ones GC'd)
        assert seq.length() <= K

    def test_gc_preserves_rollback_within_k(self):
        seq = _make_genesis_seq()
        for i in range(K + 5):
            seq = _apply_block(
                seq, i * 10, bytes([i + 1]) * 32,
                bytes([i]) * 32, bytes([i + 50]) * 64,
            )
        # Can still roll back K blocks
        rolled = seq.rollback(K)
        assert rolled is not None


class TestLedgerSeqEpochBoundary:
    def test_extend_across_epoch_boundary_ticks(self):
        seq = _make_genesis_seq()
        # Block in epoch 0
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        # Block in epoch 1 — should tick epoch 0→1
        seq = _apply_block(seq, 100, b"\x02" * 32, b"\x01" * 32, b"\xbb" * 64)
        assert seq.tip_state().current_epoch == 1

    def test_rollback_across_epoch_restores_epoch(self):
        seq = _make_genesis_seq()
        seq = _apply_block(seq, 10, b"\x01" * 32, b"\x00" * 32, b"\xaa" * 64)
        seq = _apply_block(seq, 100, b"\x02" * 32, b"\x01" * 32, b"\xbb" * 64)
        assert seq.tip_state().current_epoch == 1

        rolled = seq.rollback(1)
        assert rolled is not None
        assert rolled.tip_state().current_epoch == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/storage/test_ledger_seq.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vibe.cardano.storage.ledger_seq'`

- [ ] **Step 3: Implement LedgerSeq**

```python
# packages/vibe-cardano/src/vibe/cardano/storage/ledger_seq.py
"""LedgerSeq — anchored sequence of per-block PraosState checkpoints.

Provides O(1) rollback (drop newest N) and O(1) extend (append).
The anchor holds the state at the immutable tip; the sequence holds
states for volatile blocks. GC trims the sequence to max_rollback.

Haskell ref:
    Ouroboros.Consensus.Storage.LedgerDB (LedgerDB, ledgerDbPush, rollback)
    Data.Anchorable.AnchoredSeq
"""
from __future__ import annotations

from dataclasses import dataclass

from vibe.cardano.consensus.praos_state import (
    PraosState,
    reupdate_praos_state,
    tick_praos_state,
)

__all__ = ["LedgerSeq"]


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    block_hash: bytes
    state: PraosState


class LedgerSeq:
    """Anchored sequence of PraosState checkpoints with pure rollback.

    Internally mutable (append/trim) but rollback returns a new LedgerSeq
    that shares the prefix, matching Haskell's persistent data structure
    semantics.
    """

    def __init__(
        self,
        anchor_state: PraosState,
        anchor_hash: bytes,
        max_rollback: int,
        checkpoints: list[_Checkpoint] | None = None,
    ) -> None:
        self._anchor_state = anchor_state
        self._anchor_hash = anchor_hash
        self._max_rollback = max_rollback
        self._checkpoints: list[_Checkpoint] = list(checkpoints) if checkpoints else []

    def tip_state(self) -> PraosState:
        """Return the PraosState at the current tip."""
        if self._checkpoints:
            return self._checkpoints[-1].state
        return self._anchor_state

    def tip_hash(self) -> bytes:
        """Return the block hash at the current tip."""
        if self._checkpoints:
            return self._checkpoints[-1].block_hash
        return self._anchor_hash

    def length(self) -> int:
        """Number of checkpoints (not counting anchor)."""
        return len(self._checkpoints)

    def extend(
        self,
        slot: int,
        block_hash: bytes,
        prev_hash: bytes,
        vrf_output: bytes,
    ) -> LedgerSeq:
        """Append a block, returning a new LedgerSeq with the updated state.

        Handles epoch boundary ticks automatically.
        """
        current = self.tip_state()

        # Tick epoch if needed
        epoch_len = current.epoch_length
        if epoch_len > 0:
            block_epoch = slot // epoch_len
            if block_epoch > current.current_epoch:
                current = tick_praos_state(current, block_epoch)

        # Apply block
        new_state = reupdate_praos_state(
            current, slot=slot, block_hash=block_hash,
            prev_hash=prev_hash, vrf_output=vrf_output,
        )

        new_cps = list(self._checkpoints)
        new_cps.append(_Checkpoint(block_hash=block_hash, state=new_state))

        # GC: trim oldest beyond max_rollback
        if len(new_cps) > self._max_rollback:
            excess = len(new_cps) - self._max_rollback
            new_anchor = new_cps[excess - 1]
            new_cps = new_cps[excess:]
            return LedgerSeq(
                anchor_state=new_anchor.state,
                anchor_hash=new_anchor.block_hash,
                max_rollback=self._max_rollback,
                checkpoints=new_cps,
            )

        return LedgerSeq(
            anchor_state=self._anchor_state,
            anchor_hash=self._anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=new_cps,
        )

    def rollback(self, n: int) -> LedgerSeq | None:
        """Roll back n checkpoints. Returns None if n > length.

        Haskell ref: rollback in LedgerDB — pure, drops newest N.
        """
        if n > len(self._checkpoints):
            return None
        remaining = self._checkpoints[: len(self._checkpoints) - n]
        return LedgerSeq(
            anchor_state=self._anchor_state,
            anchor_hash=self._anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=list(remaining),
        )

    def find_hash(self, block_hash: bytes) -> int | None:
        """Return the index of the checkpoint with the given hash, or None."""
        for i, cp in enumerate(self._checkpoints):
            if cp.block_hash == block_hash:
                return i
        return None

    def rollback_to_hash(self, block_hash: bytes) -> LedgerSeq | None:
        """Roll back to the checkpoint at the given block hash.

        Returns None if the hash is not found in checkpoints.
        If hash is the anchor, returns an empty seq.
        """
        if block_hash == self._anchor_hash:
            return LedgerSeq(
                anchor_state=self._anchor_state,
                anchor_hash=self._anchor_hash,
                max_rollback=self._max_rollback,
            )
        idx = self.find_hash(block_hash)
        if idx is None:
            return None
        remaining = self._checkpoints[: idx + 1]
        return LedgerSeq(
            anchor_state=self._anchor_state,
            anchor_hash=self._anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=list(remaining),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/storage/test_ledger_seq.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/ledger_seq.py packages/vibe-cardano/tests/storage/test_ledger_seq.py
git commit -m "feat: LedgerSeq — anchored PraosState checkpoint sequence

Pure rollback/extend matching Haskell's LedgerDB pattern. Rolling
back N checkpoints restores the PraosState from N blocks ago. Epoch
boundary ticks happen automatically on extend. GC keeps at most k
checkpoints.

Prompt: Implement LedgerSeq as an anchored sequence of PraosState
checkpoints with pure rollback and automatic epoch ticks, matching
Haskell's LedgerDB.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Integrate LedgerSeq into ChainDB for atomic nonce updates

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py`
- Test: `packages/vibe-cardano/tests/storage/test_chaindb_nonce.py`

This is the core integration: `ChainDB.add_block()` now updates the `LedgerSeq` atomically during chain selection. The nonce TVar is written in the same code path as the chain fragment update — no external call needed.

- [ ] **Step 1: Write failing integration tests**

```python
# tests/storage/test_chaindb_nonce.py
"""Integration tests: ChainDB atomically updates nonce during add_block.

Verifies that:
1. Simple extension updates the nonce
2. Fork switch rolls back and recomputes the nonce
3. The nonce TVar is consistent with chain tip
"""
from __future__ import annotations

import hashlib

import pytest

from vibe.cardano.consensus.praos_state import PraosState, genesis_praos_state
from vibe.cardano.storage.chaindb import ChainDB
from vibe.cardano.storage.immutable import ImmutableDB
from vibe.cardano.storage.ledger import LedgerDB
from vibe.cardano.storage.volatile import VolatileDB

EPOCH_LENGTH = 100
K = 10
F = 0.1
GENESIS_HASH = hashlib.blake2b(b"test-genesis", digest_size=32).digest()


@pytest.fixture()
def chain_db(tmp_path):
    idb = ImmutableDB(str(tmp_path / "immutable"))
    vdb = VolatileDB(str(tmp_path / "volatile"))
    ldb = LedgerDB()
    db = ChainDB(idb, vdb, ldb, k=K)
    db.init_praos_state(GENESIS_HASH, EPOCH_LENGTH, K, F)
    return db


class TestAtomicNonceUpdate:
    @pytest.mark.asyncio
    async def test_simple_extension_updates_nonce(self, chain_db):
        nonce_before = chain_db.praos_nonce_tvar.value
        result = await chain_db.add_block(
            slot=10, block_hash=b"\x01" * 32,
            predecessor_hash=b"\x00" * 32, block_number=0,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xaa" * 64,
        )
        assert result.adopted
        nonce_after = chain_db.praos_nonce_tvar.value
        assert nonce_after != nonce_before

    @pytest.mark.asyncio
    async def test_fork_switch_rolls_back_nonce(self, chain_db):
        # Build chain A: genesis → A1 → A2
        await chain_db.add_block(
            slot=10, block_hash=b"\x01" * 32,
            predecessor_hash=b"\x00" * 32, block_number=0,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xaa" * 64,
        )
        await chain_db.add_block(
            slot=20, block_hash=b"\x02" * 32,
            predecessor_hash=b"\x01" * 32, block_number=1,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xbb" * 64,
        )
        nonce_chain_a = chain_db.praos_nonce_tvar.value

        # Build chain B: genesis → B1 → B2 → B3 (longer, wins)
        await chain_db.add_block(
            slot=11, block_hash=b"\x11" * 32,
            predecessor_hash=b"\x00" * 32, block_number=0,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xcc" * 64,
        )
        await chain_db.add_block(
            slot=21, block_hash=b"\x12" * 32,
            predecessor_hash=b"\x11" * 32, block_number=1,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xdd" * 64,
        )
        result = await chain_db.add_block(
            slot=31, block_hash=b"\x13" * 32,
            predecessor_hash=b"\x12" * 32, block_number=2,
            cbor_bytes=b"\x00" * 100, vrf_output=b"\xee" * 64,
        )
        assert result.adopted
        assert result.rollback_depth > 0

        # Nonce should reflect chain B, NOT chain A
        nonce_chain_b = chain_db.praos_nonce_tvar.value
        assert nonce_chain_b != nonce_chain_a
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/storage/test_chaindb_nonce.py -v`
Expected: FAIL — `AttributeError: 'ChainDB' object has no attribute 'init_praos_state'`

- [ ] **Step 3: Add LedgerSeq to ChainDB**

In `chaindb.py`, add these changes:

1. Add `init_praos_state()` method that creates the `LedgerSeq` and the nonce TVar
2. In `add_block()`, after chain selection decides to switch, update `LedgerSeq`:
   - Simple extension: `self._ledger_seq = self._ledger_seq.extend(...)`
   - Fork switch: `self._ledger_seq = self._ledger_seq.rollback_to_hash(intersection).extend(...)` for each new block
3. Write the tip nonce to `self.praos_nonce_tvar` atomically with `self.tip_tvar`

The key code to add inside `add_block()` after `should_switch` is determined and before the return:

```python
# --- Update PraosState atomically with chain selection ---
if self._ledger_seq is not None:
    if rollback_depth > 0 and intersection_hash is not None:
        # Fork switch: rollback to intersection, re-apply new chain
        rolled = self._ledger_seq.rollback_to_hash(intersection_hash)
        if rolled is not None:
            new_chain_blocks = self._walk_chain(intersection_hash, candidate_hash)
            for blk_slot, blk_hash, blk_prev, blk_vrf in new_chain_blocks:
                rolled = rolled.extend(
                    slot=blk_slot, block_hash=blk_hash,
                    prev_hash=blk_prev, vrf_output=blk_vrf or b"\x00" * 64,
                )
            self._ledger_seq = rolled
        else:
            logger.warning("LedgerSeq: no checkpoint at intersection %s", intersection_hash.hex()[:16])
    else:
        # Simple extension
        self._ledger_seq = self._ledger_seq.extend(
            slot=slot, block_hash=candidate_hash,
            prev_hash=predecessor_hash, vrf_output=vrf_output or b"\x00" * 64,
        )
    # Atomic TVar write — forge loop reads this
    self.praos_nonce_tvar._write(self._ledger_seq.tip_state().epoch_nonce)
```

Note: `_walk_chain` is the same logic as `_get_new_chain_blocks` in peer_manager.py — walk backward from candidate to intersection, collecting (slot, hash, prev_hash, vrf_output) tuples, reverse to oldest-first.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/storage/test_chaindb_nonce.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing ChainDB tests for regressions**

Run: `uv run pytest packages/vibe-cardano/tests/storage/test_chaindb.py -v`
Expected: All PASS (LedgerSeq is additive — existing behavior unchanged)

- [ ] **Step 6: Commit**

```bash
git add packages/vibe-cardano/src/vibe/cardano/storage/chaindb.py packages/vibe-cardano/tests/storage/test_chaindb_nonce.py
git commit -m "feat: atomic PraosState updates inside ChainDB.add_block

ChainDB now owns a LedgerSeq and updates the nonce state atomically
during chain selection. Fork switches rollback the LedgerSeq to the
intersection and re-apply new chain blocks — all before add_block
returns. The praos_nonce_tvar is written in the same code path as
the chain fragment, eliminating the race between threads.

Prompt: Integrate LedgerSeq into ChainDB so that add_block atomically
updates the nonce during chain selection, matching Haskell's switchTo
pattern where ExtLedgerState is committed in a single STM transaction.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Remove nonce state from NodeKernel and peer_manager

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/kernel.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/forge_loop.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/run.py`
- Modify: `packages/vibe-cardano/tests/node/test_epoch_processing.py`

Now that ChainDB owns the nonce, remove the old mutable nonce state from NodeKernel and the `on_block_adopted` / `on_fork_switch` calls from peer_manager.

- [ ] **Step 1: Remove nonce update calls from peer_manager.py**

In `_process_block_inline()` (lines ~791-803) and `_shared_block_processor()` (lines ~1008-1027), remove the entire block:
```python
# DELETE THIS BLOCK from both methods:
if result.adopted and self._node_kernel is not None:
    if result.rollback_depth > 0 and result.intersection_hash is not None:
        new_blocks = _get_new_chain_blocks(...)
        self._node_kernel.on_fork_switch(...)
    else:
        self._node_kernel.on_block_adopted(...)
```

Also remove the `_get_new_chain_blocks()` helper function (lines 39-68) — it's no longer needed.

- [ ] **Step 2: Remove nonce update from forge_loop.py**

In the store transaction section (lines ~339-345), remove:
```python
# DELETE:
if node_kernel is not None:
    node_kernel.on_block_adopted(
        forged.block.slot,
        forged.block.block_hash,
        forged_predecessor,
        proof.vrf_output,
    )
```

The forge loop already reads nonce from `node_kernel.nonce_tvar`. Change it to read from `chain_db.praos_nonce_tvar` instead:

```python
# In _forge_tx STM transaction, change:
nonce_val = tx.read(node_kernel.nonce_tvar) if node_kernel is not None else epoch_nonce
# To:
nonce_val = tx.read(chain_db.praos_nonce_tvar) if chain_db is not None else epoch_nonce
```

- [ ] **Step 3: Remove nonce checkpoint system from NodeKernel**

In `kernel.py`, remove:
- `_nonce_checkpoints` dict and all methods: `_save_nonce_checkpoint`, `_restore_nonce_checkpoint`
- `on_block()`, `on_block_adopted()`, `on_fork_switch()`
- `on_epoch_boundary()`
- `_combine_nonces()`
- `_evolving_nonce`, `_candidate_nonce`, `_lab_nonce`, `_last_epoch_block_nonce`, `_current_epoch`
- `init_nonce()` — replace with a pass-through that calls `chain_db.init_praos_state()`

Keep: `nonce_tvar` (but point it at `chain_db.praos_nonce_tvar`), `stake_tvar`, delegation, protocol params.

- [ ] **Step 4: Update run.py init sequence**

In `_async_init()`, call `chain_db.init_praos_state(genesis_hash, epoch_length, k, f)` instead of `node_kernel.init_nonce(...)`.

Wire `node_kernel.nonce_tvar` to point at `chain_db.praos_nonce_tvar`.

- [ ] **Step 5: Update test_epoch_processing.py**

The existing epoch processing tests tested `NodeKernel.on_block()` directly. These should be replaced by tests that go through `ChainDB.add_block()` (Task 3's tests). Remove or rewrite `test_epoch_processing.py` to test through `ChainDB`:

- Tests that called `kernel.on_block()` → call `chain_db.add_block()` instead
- Tests that checked `kernel._evolving_nonce` → check `chain_db._ledger_seq.tip_state().evolving_nonce`
- Tests that checked `kernel.epoch_nonce` → check `chain_db.praos_nonce_tvar.value`

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest packages/vibe-cardano/tests/ -v --timeout=60`
Expected: All PASS (with updated tests)

- [ ] **Step 7: Commit**

```bash
git add -u
git commit -m "refactor: remove mutable nonce state from NodeKernel

NodeKernel no longer owns nonce checkpoints or on_block_adopted/
on_fork_switch methods. ChainDB.add_block() handles all nonce updates
atomically. peer_manager no longer calls nonce update functions after
add_block. Forge loop reads nonce from chain_db.praos_nonce_tvar.

This eliminates the race condition where forge thread and receive
thread could interleave nonce updates, causing fork-induced nonce
drift and VRFKeyBadProof rejections from Haskell peers.

Prompt: Remove mutable nonce state from NodeKernel now that ChainDB
owns the nonce via LedgerSeq. Remove on_block_adopted/on_fork_switch
calls from peer_manager and forge_loop.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Devnet verification

**Files:**
- No code changes — verification only

- [ ] **Step 1: Rebuild and run devnet at 0.2s slots for 5 minutes**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml build vibe-node
docker compose -f infra/devnet/docker-compose.devnet.yml up -d
sleep 330  # 30s warmup + 300s test
docker compose -f infra/devnet/docker-compose.devnet.yml logs --no-color > /tmp/devnet-atomic-nonce.txt 2>&1
```

- [ ] **Step 2: Verify metrics**

```bash
# Expected: 0 VRFKeyBadProof, 0 ExceededTimeLimit
# Vibe forge share: ~30-36% (close to expected 33%)
grep -c "VRFKeyBadProof" /tmp/devnet-atomic-nonce.txt  # Should be 0
grep -c "ExceededTimeLimit" /tmp/devnet-atomic-nonce.txt  # Should be 0
```

- [ ] **Step 3: Run at 0.1s slots for 3 minutes (stress test)**

```bash
# Temporarily set slotLength to 0.1 in shelley-genesis.json
# Rebuild, restart, collect 3 min of logs
# VRFKeyBadProof should be 0 or near-0
```

- [ ] **Step 4: Stop devnet and restore genesis**

```bash
docker compose -f infra/devnet/docker-compose.devnet.yml down -v
# Restore slotLength to 0.2 in shelley-genesis.json
```

---

## Architecture Notes for Implementer

**Key invariant:** After `add_block()` returns, `chain_db.praos_nonce_tvar` ALWAYS reflects the correct epoch nonce for the selected chain tip. The forge loop can read it at any time via STM and get a consistent value.

**Thread safety:** `add_block()` runs on Thread 2 (receive). `add_block_sync()` runs on Thread 1 (forge). Both call the same `add_block()` code. The `LedgerSeq` is updated inside `add_block()` before it returns, so the nonce TVar is always consistent. The forge loop's STM nonce check (`if current_nonce != epoch_nonce: return "nonce_changed"`) still works — it detects if the nonce changed between VRF check and block storage.

**What about blocks that are stored but NOT adopted?** No problem — `LedgerSeq` only extends when the block becomes the new tip. Non-adopted blocks go into VolatileDB but don't affect the nonce.

**What about `_walk_chain`?** This is the same logic as `_get_new_chain_blocks` in peer_manager.py. Move it into ChainDB as a private method since it accesses `volatile_db._block_info`. It walks backward from the new tip to the intersection, gathering block info for re-application.
