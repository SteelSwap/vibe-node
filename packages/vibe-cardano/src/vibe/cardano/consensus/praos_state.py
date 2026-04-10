"""Pure nonce-tracking state for Ouroboros Praos.

This module provides a **frozen dataclass** and **pure update functions**
for the per-epoch and per-block nonce evolution that Praos requires for
leader election randomness.

The key insight: all nonce state transitions are pure functions of the
form ``(PraosState, inputs) -> PraosState``.  No mutation, no side effects.
This makes nonce updates trivially atomic when stored inside ChainDB
alongside the chain state.

Nonce fields tracked:
    - ``epoch_nonce``            -- the current epoch's leader-election nonce
    - ``evolving_nonce``         -- running hash of ALL VRF outputs this epoch
    - ``candidate_nonce``        -- running hash of VRF outputs inside stability window only
    - ``lab_nonce``              -- latest applied block's prev_hash (neutral if genesis)
    - ``last_epoch_block_nonce`` -- the lab_nonce snapshot from the prior epoch boundary

Spec references:
    - Ouroboros Praos paper, Section 7 (Nonce evolution)
    - Shelley ledger formal spec, Section 11.1 (Evolving the nonce)
    - Haskell: ``Ouroboros.Consensus.Protocol.Praos`` (tickChainDepState, reupdateChainDepState)
    - Haskell: ``Cardano.Protocol.TPraos.Rules.Prtcl`` (PRTCL transition)
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from struct import pack

from vibe.cardano.crypto.vrf import vrf_nonce_value

__all__ = [
    "PraosState",
    "genesis_praos_state",
    "reupdate_praos_state",
    "tick_praos_state",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEUTRAL: bytes = b"\x00" * 32
"""The neutral (identity) nonce -- 32 zero bytes.

Haskell ref: ``NeutralNonce`` constructor of ``Nonce``.
"""


# ---------------------------------------------------------------------------
# Combine helper
# ---------------------------------------------------------------------------


def _combine(a: bytes, b: bytes) -> bytes:
    """Combine two 32-byte nonces per Praos spec.

    Rules:
        - If ``a`` is neutral, return ``b``.
        - If ``b`` is neutral, return ``a``.
        - Otherwise, return ``blake2b_256(a || b)``.

    This matches the Haskell ``Nonce`` monoid instance where NeutralNonce
    is the identity element.

    Haskell ref: ``Semigroup`` instance for ``Nonce`` in
        ``Cardano.Ledger.BaseTypes``
    """
    if a == NEUTRAL:
        return b
    if b == NEUTRAL:
        return a
    return hashlib.blake2b(a + b, digest_size=32).digest()


# ---------------------------------------------------------------------------
# PraosState dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PraosState:
    """Frozen nonce-tracking state for Ouroboros Praos.

    All fields are immutable.  State transitions produce new instances
    via ``reupdate_praos_state`` (per-block) and ``tick_praos_state``
    (epoch boundary).

    Haskell ref: ``PraosState`` fields in
        ``Ouroboros.Consensus.Protocol.Praos``
    """

    epoch_nonce: bytes
    """Current epoch nonce used for VRF leader election (32 bytes)."""

    evolving_nonce: bytes
    """Running hash of all VRF nonce outputs this epoch (32 bytes)."""

    candidate_nonce: bytes
    """Running hash of VRF nonce outputs within stability window (32 bytes)."""

    lab_nonce: bytes
    """Latest applied block's prev_hash; neutral if all-zeros (32 bytes)."""

    last_epoch_block_nonce: bytes
    """Snapshot of lab_nonce from the prior epoch boundary (32 bytes)."""

    current_epoch: int
    """Current epoch number."""

    epoch_length: int
    """Number of slots per epoch."""

    security_param: int
    """Security parameter k."""

    active_slot_coeff: float
    """Active slot coefficient f."""

    def save(self, path: "Path") -> None:
        """Persist praos state to a JSON file for restart recovery."""
        import json
        from pathlib import Path as _Path
        data = {
            "epoch_nonce": self.epoch_nonce.hex(),
            "evolving_nonce": self.evolving_nonce.hex(),
            "candidate_nonce": self.candidate_nonce.hex(),
            "lab_nonce": self.lab_nonce.hex(),
            "last_epoch_block_nonce": self.last_epoch_block_nonce.hex(),
            "current_epoch": self.current_epoch,
            "epoch_length": self.epoch_length,
            "security_param": self.security_param,
            "active_slot_coeff": self.active_slot_coeff,
        }
        _Path(path).write_text(json.dumps(data))

    @classmethod
    def load(cls, path: "Path") -> "PraosState":
        """Restore praos state from a JSON file."""
        import json
        from pathlib import Path as _Path
        data = json.loads(_Path(path).read_text())
        return cls(
            epoch_nonce=bytes.fromhex(data["epoch_nonce"]),
            evolving_nonce=bytes.fromhex(data["evolving_nonce"]),
            candidate_nonce=bytes.fromhex(data["candidate_nonce"]),
            lab_nonce=bytes.fromhex(data["lab_nonce"]),
            last_epoch_block_nonce=bytes.fromhex(data["last_epoch_block_nonce"]),
            current_epoch=data["current_epoch"],
            epoch_length=data["epoch_length"],
            security_param=data["security_param"],
            active_slot_coeff=data["active_slot_coeff"],
        )


# ---------------------------------------------------------------------------
# Stability window
# ---------------------------------------------------------------------------


def _stability_window(security_param: int, active_slot_coeff: float) -> int:
    """Compute the randomness stabilisation window: ceil(3k/f).

    Haskell uses two different window sizes depending on the era:
      - ``computeStabilityWindow``                = ceil(3k/f) — TPraos + Babbage
      - ``computeRandomnessStabilisationWindow``   = ceil(4k/f) — Conway+

    Babbage overrides to 3k/f for backward compatibility (erratum 17.3).
    See ``partialConsensusConfigBabbage`` in ``Ouroboros.Consensus.Cardano.Node``.

    We default to ceil(3k/f) since that covers all eras through Babbage.
    Conway's ceil(4k/f) must be handled by the caller when the era is known.

    Haskell ref: ``computeStabilityWindow`` in
        ``Cardano.Ledger.Shelley.StabilityWindow``
    """
    return math.ceil(3 * security_param / active_slot_coeff)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def genesis_praos_state(
    genesis_hash: bytes,
    epoch_length: int,
    security_param: int,
    active_slot_coeff: float,
) -> PraosState:
    """Create the initial PraosState from genesis parameters.

    - ``epoch_nonce``, ``evolving_nonce``, ``candidate_nonce`` = genesis_hash
    - ``lab_nonce`` = neutral (no block applied yet)
    - ``last_epoch_block_nonce`` = NeutralNonce
      (Haskell: ticknStatePrevHashNonce starts as NeutralNonce)

    Haskell ref: translateChainDepStateByronToShelley →
        TranslateProto TPraos Praos → initial PraosState
    """
    return PraosState(
        epoch_nonce=genesis_hash,
        evolving_nonce=genesis_hash,
        candidate_nonce=genesis_hash,
        lab_nonce=NEUTRAL,
        last_epoch_block_nonce=NEUTRAL,  # NeutralNonce — identity for ⭒
        current_epoch=0,
        epoch_length=epoch_length,
        security_param=security_param,
        active_slot_coeff=active_slot_coeff,
    )


# ---------------------------------------------------------------------------
# Per-block update (pure)
# ---------------------------------------------------------------------------


def reupdate_praos_state(
    state: PraosState,
    slot: int,
    block_hash: bytes,
    prev_hash: bytes,
    vrf_output: bytes,
) -> PraosState:
    """Pure per-block nonce update.

    Called for each validated block header.  Updates:
        - ``evolving_nonce`` = combine(old_evolving, vrf_nonce_value(vrf_output))
        - ``candidate_nonce`` = same update, but ONLY if slot is inside stability window
        - ``lab_nonce`` = prev_hash (or neutral if all-zeros)

    Does NOT touch ``epoch_nonce``, ``last_epoch_block_nonce``, or ``current_epoch``.

    Haskell ref: ``reupdateChainDepState`` in
        ``Ouroboros.Consensus.Protocol.Praos``

    Args:
        state: Current nonce state.
        slot: Absolute slot number of the block.
        block_hash: Block header hash (32 bytes).
        prev_hash: Previous block hash from the header (32 bytes).
        vrf_output: Raw VRF output from the block header.

    Returns:
        New PraosState with updated nonces.
    """
    nonce_val = vrf_nonce_value(vrf_output)

    new_evolving = _combine(state.evolving_nonce, nonce_val)

    # Candidate nonce: tracks evolving nonce only within the stability window.
    # Haskell: if slot + window < firstSlotNextEpoch then newEvolvingNonce
    #          else candidateNonce (frozen)
    # Note: candidate is SET TO newEvolvingNonce, not accumulated independently.
    window = _stability_window(state.security_param, state.active_slot_coeff)
    first_slot_next_epoch = (state.current_epoch + 1) * state.epoch_length

    if slot + window < first_slot_next_epoch:
        new_candidate = new_evolving
    else:
        new_candidate = state.candidate_nonce

    # lab_nonce = prev_hash, but neutral if all-zeros
    new_lab = NEUTRAL if prev_hash == NEUTRAL else prev_hash

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


# ---------------------------------------------------------------------------
# Epoch boundary tick (pure)
# ---------------------------------------------------------------------------


def tick_praos_state(
    state: PraosState,
    new_epoch: int,
    extra_entropy: bytes | None = None,
) -> PraosState:
    """Pure epoch boundary nonce evolution.

    Called at the transition from epoch N to epoch N+1.

    Epoch 0 -> 1:
        Retains genesis nonce (stabilization lag -- the first epoch doesn't
        have enough blocks to derive a new nonce).

    Epoch N -> N+1 (N > 0):
        epoch_nonce = combine(candidate_nonce, last_epoch_block_nonce)
        If extra_entropy is provided, further combined:
            epoch_nonce = combine(epoch_nonce, extra_entropy)

    In all cases:
        last_epoch_block_nonce = lab_nonce (from current state)
        evolving_nonce, candidate_nonce, lab_nonce carry over unchanged.

    Haskell ref: ``tickChainDepState`` in
        ``Ouroboros.Consensus.Protocol.Praos`` — only updates
        praosStateEpochNonce and praosStateLastEpochBlockNonce.

    Args:
        state: Current nonce state at end of previous epoch.
        new_epoch: The epoch number we are transitioning INTO.
        extra_entropy: Optional extra entropy from protocol parameter updates.

    Returns:
        New PraosState for the new epoch.
    """
    # Haskell ref: tickChainDepState applies the SAME formula for ALL epochs:
    #   epochNonce = candidateNonce ⭒ lastEpochBlockNonce
    # There is no special case for epoch 0->1. When lastEpochBlockNonce
    # is NeutralNonce (initial value), the ⭒ identity makes:
    #   epochNonce = candidateNonce ⭒ NeutralNonce = candidateNonce
    new_epoch_nonce = _combine(state.candidate_nonce, state.last_epoch_block_nonce)
    if extra_entropy is not None:
        new_epoch_nonce = _combine(new_epoch_nonce, extra_entropy)

    return PraosState(
        epoch_nonce=new_epoch_nonce,
        evolving_nonce=state.evolving_nonce,      # carries over
        candidate_nonce=state.candidate_nonce,    # carries over
        lab_nonce=state.lab_nonce,                # carries over
        last_epoch_block_nonce=state.lab_nonce,
        current_epoch=new_epoch,
        epoch_length=state.epoch_length,
        security_param=state.security_param,
        active_slot_coeff=state.active_slot_coeff,
    )
