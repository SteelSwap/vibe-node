"""Anchored PraosState checkpoint sequence — the nonce-tracking LedgerDB.

This is the Python equivalent of Haskell's ``LedgerSeq`` / ``AnchoredSeq``
from ``Ouroboros.Consensus.Storage.LedgerDB``.  It maintains an ordered
sequence of per-block ``PraosState`` snapshots with:

- **O(1) rollback** — drop the N newest checkpoints
- **O(1) extend** — append a new checkpoint (with automatic epoch tick)
- **GC** — trim checkpoints beyond ``max_rollback``, advancing the anchor
- **Hash-based lookup** — ``rollback_to_hash`` for chain selection

The sequence is *anchored*: there is always a base state (the anchor) that
represents the oldest retained state.  Checkpoints are stored oldest-first
in a plain list.  The data structure is immutable — all operations return
new ``LedgerSeq`` instances.

Haskell references:
    Ouroboros.Consensus.Storage.LedgerDB.LedgerSeq
    Ouroboros.Consensus.Ledger.Abstract (AnchoredSeq)
    Ouroboros.Consensus.Protocol.Praos (tickChainDepState, reupdateChainDepState)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from vibe.cardano.consensus.praos_state import (
    PraosState,
    reupdate_praos_state,
    tick_praos_state,
)

__all__ = ["LedgerSeq"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal checkpoint
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Checkpoint:
    """A single checkpoint: block hash + the PraosState after that block."""

    block_hash: bytes
    state: PraosState


# ---------------------------------------------------------------------------
# LedgerSeq
# ---------------------------------------------------------------------------


class LedgerSeq:
    """Anchored sequence of PraosState checkpoints.

    Immutable — all mutating operations return a new instance.

    Args:
        anchor_state: The PraosState at the anchor point.
        anchor_hash: The block hash at the anchor point.
        max_rollback: Maximum number of checkpoints to retain (security param k).
        checkpoints: Optional pre-existing list of checkpoints (oldest-first).
    """

    __slots__ = ("_anchor_state", "_anchor_hash", "_max_rollback", "_checkpoints")

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

    # -- Queries -----------------------------------------------------------

    def tip_state(self) -> PraosState:
        """State at current tip (last checkpoint or anchor)."""
        if self._checkpoints:
            return self._checkpoints[-1].state
        return self._anchor_state

    def tip_hash(self) -> bytes:
        """Hash at current tip (last checkpoint or anchor)."""
        if self._checkpoints:
            return self._checkpoints[-1].block_hash
        return self._anchor_hash

    def length(self) -> int:
        """Number of checkpoints (not counting anchor)."""
        return len(self._checkpoints)

    def find_hash(self, block_hash: bytes) -> int | None:
        """Index of hash in checkpoints, or None if not found.

        Note: the anchor hash is NOT searched — only checkpoints.
        """
        for i, cp in enumerate(self._checkpoints):
            if cp.block_hash == block_hash:
                return i
        return None

    # -- Extend ------------------------------------------------------------

    def extend(
        self,
        slot: int,
        block_hash: bytes,
        prev_hash: bytes,
        vrf_output: bytes,
    ) -> LedgerSeq:
        """Append a block, returning a new LedgerSeq.

        Handles epoch boundary ticks automatically: if the slot falls in a
        new epoch (``slot // epoch_length > state.current_epoch``), calls
        ``tick_praos_state`` before ``reupdate_praos_state``.

        After appending, GC trims if length exceeds ``max_rollback``.
        """
        current = self.tip_state()

        # Epoch boundary tick — must tick through EACH intermediate epoch.
        # When catching up across multiple epochs (e.g. 1254→1261), each
        # epoch boundary must be ticked individually because the nonce
        # evolution depends on the cumulative state at each boundary.
        new_epoch = slot // current.epoch_length
        if new_epoch > current.current_epoch:
            old_epoch = current.current_epoch
            for intermediate_epoch in range(old_epoch + 1, new_epoch + 1):
                logger.info(
                    "Epoch %d->%d cand=%s lab=%s lastEpochBlk=%s ev=%s",
                    current.current_epoch, intermediate_epoch,
                    current.candidate_nonce.hex(),
                    current.lab_nonce.hex(),
                    current.last_epoch_block_nonce.hex(),
                    current.evolving_nonce.hex(),
                )
                current = tick_praos_state(current, intermediate_epoch)
                logger.info(
                    "Epoch %d->%d result nonce=%s",
                    old_epoch, intermediate_epoch, current.epoch_nonce.hex(),
                )

        # Per-block nonce update
        new_state = reupdate_praos_state(current, slot, block_hash, prev_hash, vrf_output)

        # Build new checkpoint list
        new_cps = list(self._checkpoints)
        new_cps.append(_Checkpoint(block_hash=block_hash, state=new_state))

        # GC: trim oldest if beyond max_rollback
        anchor_state = self._anchor_state
        anchor_hash = self._anchor_hash

        while len(new_cps) > self._max_rollback:
            trimmed = new_cps.pop(0)
            anchor_state = trimmed.state
            anchor_hash = trimmed.block_hash

        return LedgerSeq(
            anchor_state=anchor_state,
            anchor_hash=anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=new_cps,
        )

    # -- Rollback ----------------------------------------------------------

    def rollback(self, n: int) -> LedgerSeq | None:
        """Drop n newest checkpoints.

        Returns None if n > length.  rollback(0) returns a copy.
        """
        if n > len(self._checkpoints):
            return None

        new_cps = self._checkpoints[: len(self._checkpoints) - n] if n > 0 else list(self._checkpoints)

        return LedgerSeq(
            anchor_state=self._anchor_state,
            anchor_hash=self._anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=new_cps,
        )

    def rollback_to_hash(self, block_hash: bytes) -> LedgerSeq | None:
        """Rollback to the checkpoint with the given hash.

        If ``block_hash`` is the anchor hash, returns an empty seq.
        Returns None if the hash is not found in checkpoints or anchor.
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

        # Keep checkpoints up to and including idx
        new_cps = self._checkpoints[: idx + 1]
        return LedgerSeq(
            anchor_state=self._anchor_state,
            anchor_hash=self._anchor_hash,
            max_rollback=self._max_rollback,
            checkpoints=new_cps,
        )
