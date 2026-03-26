"""NodeKernel — Praos chain-dependent state and delegation tracking.

Holds the consensus-level state that evolves per-block: epoch nonces,
delegation state, stake distribution, and protocol parameters. ChainDB
is the source of truth for the selected chain and block serving;
NodeKernel only tracks the protocol state that depends on the chain.

Haskell reference:
    Ouroboros.Consensus.NodeKernel (initNodeKernel, NodeKernel)
    The Haskell NodeKernel holds ChainDB, Mempool, BlockFetchInterface, etc.
    Our NodeKernel holds a reference to ChainDB and owns the Praos state.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from vibe.cardano.consensus.nonce import (
    EpochNonce,
    stability_window,
)
from vibe.cardano.ledger.delegation import (
    DelegationState,
    apply_block_certs,
    compute_pool_stake_distribution,
)

logger = logging.getLogger(__name__)


class StakeDistribution:
    """Snapshot of stake distribution for VRF leader election."""

    def __init__(self, pool_stakes: dict[bytes, int], total_stake: int) -> None:
        self.pool_stakes = pool_stakes
        self.total_stake = total_stake

    def relative_stake(self, pool_id: bytes) -> float:
        if self.total_stake == 0:
            return 0.0
        return self.pool_stakes.get(pool_id, 0) / self.total_stake


class NodeKernel:
    """Praos chain-dependent state and delegation/stake tracking.

    ChainDB is the source of truth for the selected chain. NodeKernel
    holds only the protocol-level state that evolves per block:
    - Epoch nonces (5-nonce Praos model)
    - Delegation state
    - Stake distribution
    - Protocol parameters

    Haskell reference:
        Ouroboros.Consensus.NodeKernel — owns ChainDB and protocol state.
    """

    def __init__(self, chain_db: Any = None, lock: Any = None) -> None:
        self._chain_db = chain_db

        # Thread-safety: RWLock for concurrent nonce reads / exclusive writes
        if lock is None:
            from vibe.core.rwlock import RWLock

            lock = RWLock()
        self._lock = lock

        # Praos chain-dependent state — full 5-nonce model
        # Haskell ref: PraosState in Ouroboros.Consensus.Protocol.Praos
        self._epoch_nonce: EpochNonce = EpochNonce(value=b"\x00" * 32)

        # STM TVar for epoch nonce — used by forge loop for atomic reads
        from vibe.core.stm import TVar

        self.nonce_tvar: TVar = TVar(self._epoch_nonce.value)
        self.stake_tvar: TVar = TVar({})
        self._evolving_nonce: bytes = b"\x00" * 32
        self._candidate_nonce: bytes = b"\x00" * 32
        self._lab_nonce: bytes = b"\x00" * 32
        self._last_epoch_block_nonce: bytes = b"\x00" * 32
        self._current_epoch: int = 0
        self._epoch_length: int = 432000
        self._security_param: int = 2160
        self._active_slot_coeff: float = 0.05

        # Nonce state checkpoints: block_hash → snapshot of nonce state.
        # Used to rollback nonce state on fork switches.
        # Haskell ref: PraosState is part of the ledger state which gets
        # rolled back during fork switches in ChainSel.switchTo.
        self._nonce_checkpoints: dict[bytes, dict] = {}

        # Delegation state tracking
        self._delegation_state: DelegationState = DelegationState()

        # Protocol parameters
        self._protocol_params: dict[str, Any] = {}
        self._pending_param_updates: list[dict[str, Any]] = []

        # Per-pool stake distribution (pool_key_hash -> total lovelace)
        self._stake_distribution: dict[bytes, int] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def epoch_nonce(self) -> EpochNonce:
        return self._epoch_nonce

    @property
    def delegation_state(self) -> DelegationState:
        return self._delegation_state

    @property
    def stake_distribution(self) -> dict[bytes, int]:
        return self._stake_distribution

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    @property
    def epoch_length(self) -> int:
        return self._epoch_length

    @property
    def protocol_params(self) -> dict[str, Any]:
        return self._protocol_params

    # ------------------------------------------------------------------
    # Delegation and stake
    # ------------------------------------------------------------------

    def apply_delegation_certs(self, transactions: list[Any], current_epoch: int) -> None:
        """Apply delegation certificates from a block's transactions."""
        self._delegation_state = apply_block_certs(
            self._delegation_state,
            transactions,
            current_epoch,
        )

    def update_stake_distribution(
        self,
        utxo_stakes: dict[bytes, int],
        *,
        pool_stakes_direct: dict[bytes, int] | None = None,
    ) -> dict[bytes, int]:
        """Recompute the per-pool stake distribution.

        If pool_stakes_direct is provided (keyed by pool_id -> lovelace),
        use it directly instead of computing from delegation state + UTxO.
        This is used for genesis initialization where the delegation state
        is not yet populated but initial pool stakes are known.
        """
        if pool_stakes_direct is not None:
            self._stake_distribution = dict(pool_stakes_direct)
        else:
            self._stake_distribution = compute_pool_stake_distribution(
                self._delegation_state,
                utxo_stakes,
            )
        self.stake_tvar._write(dict(self._stake_distribution))
        total = sum(self._stake_distribution.values())
        logger.info(
            "Stake distribution updated: %d pools, total stake=%d",
            len(self._stake_distribution),
            total,
            extra={
                "event": "stake.updated",
                "pool_count": len(self._stake_distribution),
                "total_stake": total,
            },
        )
        return self._stake_distribution

    # ------------------------------------------------------------------
    # Protocol parameters
    # ------------------------------------------------------------------

    def init_protocol_params(self, params: dict[str, Any]) -> None:
        self._protocol_params = dict(params)

    def queue_param_update(self, update: dict[str, Any]) -> None:
        self._pending_param_updates.append(update)

    def apply_pending_updates(self) -> None:
        for update in self._pending_param_updates:
            self._protocol_params.update(update)
        count = len(self._pending_param_updates)
        self._pending_param_updates.clear()
        if count:
            logger.info(
                "Applied %d protocol parameter updates",
                count,
                extra={"event": "params.updated", "update_count": count},
            )

    # ------------------------------------------------------------------
    # Praos nonce state
    # ------------------------------------------------------------------

    def init_nonce(
        self,
        genesis_hash: bytes,
        epoch_length: int,
        security_param: int = 2160,
        active_slot_coeff: float = 0.05,
    ) -> None:
        """Seed the Praos chain-dependent state from the genesis hash.

        Haskell ref: translateChainDepStateByronToShelley
        """
        self._epoch_nonce = EpochNonce(value=genesis_hash)
        self.nonce_tvar._write(genesis_hash)
        self._evolving_nonce = genesis_hash
        self._candidate_nonce = genesis_hash
        self._lab_nonce = b"\x00" * 32
        self._last_epoch_block_nonce = b"\x00" * 32
        self._epoch_length = epoch_length
        self._security_param = security_param
        self._active_slot_coeff = active_slot_coeff
        logger.info(
            "Epoch nonce initialised (epoch_length=%d, k=%d, f=%.4f)",
            epoch_length,
            security_param,
            active_slot_coeff,
            extra={
                "event": "nonce.init",
                "nonce": genesis_hash.hex()[:16],
                "epoch_length": epoch_length,
            },
        )

    def _combine_nonces(self, a: bytes, b: bytes) -> bytes:
        """Combine two nonces with the ⭒ operator.

        Haskell ref: (⭒) in Cardano.Ledger.BaseTypes
        """
        neutral = b"\x00" * 32
        if a == neutral:
            return b
        if b == neutral:
            return a
        return hashlib.blake2b(a + b, digest_size=32).digest()

    def on_block(self, slot: int, prev_hash: bytes, vrf_output: bytes) -> None:
        """Update Praos chain-dependent state for a block.

        Haskell ref: reupdateChainDepState from Praos.hs
        """
        epoch_len = self._epoch_length
        if epoch_len <= 0:
            return

        from vibe.cardano.crypto.vrf import vrf_nonce_value

        vrf_nonce = vrf_nonce_value(vrf_output)

        self._evolving_nonce = self._combine_nonces(
            self._evolving_nonce,
            vrf_nonce,
        )

        block_epoch = slot // epoch_len
        first_slot_next_epoch = (block_epoch + 1) * epoch_len
        stab_window = stability_window(
            epoch_len,
            self._security_param,
            self._active_slot_coeff,
        )
        # When stab_window >= epoch_length (small devnet epochs), ALL blocks
        # contribute to the nonce. Otherwise, only blocks before the stability
        # cutoff contribute. Haskell ref: stabilityWindow caps at epoch_length,
        # so the condition below becomes trivially true for all blocks.
        if stab_window >= epoch_len or slot + stab_window < first_slot_next_epoch:
            self._candidate_nonce = self._evolving_nonce

        self._lab_nonce = prev_hash

    def on_epoch_boundary(self, new_epoch: int, extra_entropy: bytes | None = None) -> None:
        """Evolve the epoch nonce at an epoch transition.

        Haskell ref: tickChainDepState in Praos.hs
        """
        if new_epoch <= self._current_epoch:
            return

        new_nonce_bytes = self._combine_nonces(
            self._candidate_nonce,
            self._last_epoch_block_nonce,
        )
        if extra_entropy is not None:
            new_nonce_bytes = self._combine_nonces(
                new_nonce_bytes,
                extra_entropy,
            )

        old_epoch = self._current_epoch
        self._epoch_nonce = EpochNonce(value=new_nonce_bytes)
        self.nonce_tvar._write(new_nonce_bytes)
        self._last_epoch_block_nonce = self._lab_nonce
        self._current_epoch = new_epoch
        logger.info(
            "Epoch transition %d -> %d (nonce=%s)",
            old_epoch,
            new_epoch,
            new_nonce_bytes.hex()[:16],
            extra={
                "event": "epoch.transition",
                "from_epoch": old_epoch,
                "to_epoch": new_epoch,
            },
        )

    def _save_nonce_checkpoint(self, block_hash: bytes) -> None:
        """Save a snapshot of nonce state keyed by block hash.

        Haskell ref: PraosState is part of the ledger state, which is
        snapshotted per-block for rollback support.
        """
        self._nonce_checkpoints[block_hash] = {
            "epoch_nonce": self._epoch_nonce.value,
            "evolving_nonce": self._evolving_nonce,
            "candidate_nonce": self._candidate_nonce,
            "lab_nonce": self._lab_nonce,
            "last_epoch_block_nonce": self._last_epoch_block_nonce,
            "current_epoch": self._current_epoch,
        }
        # GC old checkpoints — keep at most 2*k
        max_checkpoints = max(20, self._security_param * 2)
        if len(self._nonce_checkpoints) > max_checkpoints:
            # Remove oldest (first inserted — Python 3.7+ dicts are ordered)
            excess = len(self._nonce_checkpoints) - max_checkpoints
            for _ in range(excess):
                oldest_key = next(iter(self._nonce_checkpoints))
                del self._nonce_checkpoints[oldest_key]

    def _restore_nonce_checkpoint(self, block_hash: bytes) -> bool:
        """Restore nonce state from a checkpoint.

        Returns True if checkpoint found and restored, False otherwise.
        """
        cp = self._nonce_checkpoints.get(block_hash)
        if cp is None:
            return False
        self._epoch_nonce = EpochNonce(value=cp["epoch_nonce"])
        self.nonce_tvar._write(cp["epoch_nonce"])
        self._evolving_nonce = cp["evolving_nonce"]
        self._candidate_nonce = cp["candidate_nonce"]
        self._lab_nonce = cp["lab_nonce"]
        self._last_epoch_block_nonce = cp["last_epoch_block_nonce"]
        self._current_epoch = cp["current_epoch"]
        return True

    def on_block_adopted(
        self,
        slot: int,
        block_hash: bytes,
        prev_hash: bytes,
        vrf_output: bytes | None,
    ) -> None:
        """Update Praos state after a block is adopted by ChainDB.

        Called by peer_manager and forge_loop after chain_db.add_block
        returns adopted=True. Handles epoch boundary ticking,
        per-block nonce updates, and checkpoint saving.

        Haskell ref: updateChainDepState + reupdateChainDepState
        """
        epoch_len = self._epoch_length
        if epoch_len <= 0:
            return
        block_epoch = slot // epoch_len
        if block_epoch > self._current_epoch:
            self.on_epoch_boundary(block_epoch)
        if vrf_output:
            self.on_block(slot, prev_hash, vrf_output)
        # Save checkpoint AFTER updating state
        self._save_nonce_checkpoint(block_hash)

    def on_fork_switch(
        self,
        intersection_hash: bytes | None,
        new_chain_blocks: list[tuple[int, bytes, bytes, bytes | None]],
    ) -> None:
        """Rollback and re-apply nonce state for a fork switch.

        When ChainDB switches to a fork, the nonce state must be rolled
        back to the intersection point and re-applied with the new
        chain's blocks.

        Haskell ref: switchTo in ChainSel.hs rolls back the ledger
        state (including PraosState) to the intersection and re-applies.

        Args:
            intersection_hash: Block hash of the fork point, or None.
            new_chain_blocks: List of (slot, block_hash, prev_hash, vrf_output)
                for each block on the new chain after the intersection,
                ordered oldest-first.
        """
        if intersection_hash is None:
            return

        # Restore to intersection checkpoint
        if not self._restore_nonce_checkpoint(intersection_hash):
            logger.warning(
                "No nonce checkpoint at intersection %s — nonce may drift",
                intersection_hash.hex()[:16],
            )
            return

        # Re-apply new chain blocks from intersection forward
        for slot, block_hash, prev_hash, vrf_output in new_chain_blocks:
            epoch_len = self._epoch_length
            if epoch_len > 0:
                block_epoch = slot // epoch_len
                if block_epoch > self._current_epoch:
                    self.on_epoch_boundary(block_epoch)
            if vrf_output:
                self.on_block(slot, prev_hash, vrf_output)
            self._save_nonce_checkpoint(block_hash)

        logger.debug(
            "Nonce state rolled back to %s and re-applied %d blocks",
            intersection_hash.hex()[:16],
            len(new_chain_blocks),
        )
