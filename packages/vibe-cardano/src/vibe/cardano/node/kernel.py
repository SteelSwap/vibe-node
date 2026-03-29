"""NodeKernel -- delegation, stake, and protocol parameter tracking.

ChainDB is the source of truth for the selected chain and Praos nonce state
(via LedgerSeq). NodeKernel holds the remaining protocol-level state:
- Delegation state
- Stake distribution
- Protocol parameters

The epoch nonce TVar is wired to ChainDB.praos_nonce_tvar so that the forge
loop can read the nonce atomically via STM.

Haskell reference:
    Ouroboros.Consensus.NodeKernel (initNodeKernel, NodeKernel)
"""

from __future__ import annotations

import logging
from typing import Any

from vibe.cardano.consensus.nonce import EpochNonce
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
    """Delegation, stake, and protocol parameter tracking.

    ChainDB owns the Praos nonce state via LedgerSeq. NodeKernel holds:
    - nonce_tvar / stake_tvar (TVars read by the forge loop)
    - Delegation state
    - Stake distribution
    - Protocol parameters

    Haskell reference:
        Ouroboros.Consensus.NodeKernel -- owns ChainDB and protocol state.
    """

    def __init__(self, chain_db: Any = None, lock: Any = None) -> None:
        self._chain_db = chain_db

        # Thread-safety: RWLock for concurrent reads / exclusive writes
        if lock is None:
            from vibe.core.rwlock import RWLock

            lock = RWLock()
        self._lock = lock

        # STM TVars for forge loop reads
        from vibe.core.stm import TVar

        self.nonce_tvar: TVar = TVar(b"\x00" * 32)
        self.stake_tvar: TVar = TVar({})

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
        """Read the epoch nonce from the TVar (source of truth is ChainDB)."""
        val = self.nonce_tvar.value
        if val is None:
            val = b"\x00" * 32
        return EpochNonce(value=val)

    @property
    def delegation_state(self) -> DelegationState:
        return self._delegation_state

    @property
    def stake_distribution(self) -> dict[bytes, int]:
        return self._stake_distribution

    @property
    def protocol_params(self) -> dict[str, Any]:
        return self._protocol_params

    # ------------------------------------------------------------------
    # Nonce initialisation (wires TVar to ChainDB)
    # ------------------------------------------------------------------

    def init_nonce(
        self,
        genesis_hash: bytes | None = None,
        epoch_length: int = 0,
        security_param: int = 2160,
        active_slot_coeff: float = 0.05,
        *,
        chain_db: Any = None,
    ) -> None:
        """Wire nonce TVar to ChainDB's praos_nonce_tvar.

        Accepts legacy positional args for backward compatibility but
        the only meaningful parameter is chain_db. If chain_db is provided
        (and has praos_nonce_tvar), the kernel's nonce_tvar is pointed at it.
        Otherwise falls back to setting the TVar from genesis_hash.
        """
        if chain_db is not None and hasattr(chain_db, "praos_nonce_tvar"):
            self.nonce_tvar = chain_db.praos_nonce_tvar
            logger.info(
                "NodeKernel nonce TVar wired to ChainDB.praos_nonce_tvar",
            )
            return

        # Legacy fallback: seed TVar directly from genesis_hash
        if genesis_hash is not None:
            self.nonce_tvar._write(genesis_hash)
            logger.info(
                "Epoch nonce initialised from genesis_hash (legacy path)",
            )

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
