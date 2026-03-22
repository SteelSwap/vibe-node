"""Delegation state tracking — certs, pools, and stake distribution evolution.

This module provides the high-level interface for tracking delegation state
across the chain. It wraps the per-certificate processing from
shelley_delegation.py and adds:

1. Block-level certificate extraction and application
2. Per-pool stake distribution computation from delegations + UTxO balances
3. Integration hooks for the sync pipeline and epoch boundary processing

The core insight: during sync, every block may contain transactions with
delegation certificates (StakeRegistration, StakeDeregistration, StakeDelegation,
PoolRegistration, PoolRetirement). These must be tracked so that at each epoch
boundary we can compute the correct stake distribution for leader election.

Without this, stake distribution stays at genesis values forever, and leader
election is wrong after epoch 0.

Spec references:
    * Shelley ledger formal spec, Section 8 (Delegation)
    * Shelley ledger formal spec, Section 11 (Epoch boundary — SNAP rule)
    * Shelley ledger formal spec, Figure 46 (Stake snapshot)

Haskell references:
    * ``Cardano.Ledger.Shelley.LedgerState`` — DState, PState
    * ``Cardano.Ledger.Shelley.Rules.Delegs`` — certificate processing
    * ``stakeDistr`` in ``Cardano.Ledger.Shelley.LedgerState``
"""

from __future__ import annotations

import logging
from typing import Any

from pycardano.certificate import (
    PoolRegistration,
    PoolRetirement,
    StakeDelegation,
    StakeDeregistration,
    StakeRegistration,
)

from vibe.cardano.ledger.shelley_delegation import (
    DelegationState,
    _credential_hash,
    _pool_key_hash,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DelegationState",
    "apply_block_certs",
    "compute_pool_stake_distribution",
    "extract_certs_from_tx",
]


# ---------------------------------------------------------------------------
# Certificate extraction from transactions
# ---------------------------------------------------------------------------


def extract_certs_from_tx(tx: Any) -> list[Any]:
    """Extract delegation certificates from a decoded transaction.

    Works with both pycardano Transaction objects and our internal
    DecodedTx representation from the serialization layer.

    Args:
        tx: A transaction object. Must have either:
            - ``transaction_body.certificates`` (pycardano Transaction)
            - ``body.certificates`` (our DecodedTx)
            - ``certificates`` attribute directly

    Returns:
        List of certificate objects, or empty list if none found.
    """
    # pycardano Transaction
    body = getattr(tx, "transaction_body", None) or getattr(tx, "body", None)
    if body is not None:
        certs = getattr(body, "certificates", None)
        if certs:
            return list(certs)
    # Direct certificates attribute
    certs = getattr(tx, "certificates", None)
    if certs:
        return list(certs)
    return []


# ---------------------------------------------------------------------------
# Block-level certificate application
# ---------------------------------------------------------------------------


def apply_block_certs(
    state: DelegationState,
    transactions: list[Any],
    current_epoch: int,
) -> DelegationState:
    """Apply all delegation certificates from a block's transactions.

    Processes transactions in order, and within each transaction processes
    certificates in order. This matches the Haskell BBODY rule which folds
    ``applyTx`` over all transactions, with each ``applyTx`` folding
    ``shelleyDelegsTransition`` over the certificate list.

    Unlike the strict shelley_delegation.process_certificate which raises
    on validation errors, this function is lenient during sync — we log
    errors but continue processing. During sync from a trusted source
    (Mithril snapshot or Haskell peer), blocks have already been validated.

    Spec ref: Shelley spec, BBODY rule — sequential tx application.
    Haskell ref: ``applyTxsTransition`` in
        ``Cardano.Ledger.Shelley.LedgerState``

    Args:
        state: Current delegation state (not modified in place).
        transactions: List of transactions from the block.
        current_epoch: Current epoch number (for pool retirement validation).

    Returns:
        Updated DelegationState after applying all certificates.
    """
    for tx in transactions:
        # Skip invalid transactions (phase-2 failures)
        if hasattr(tx, "valid") and not tx.valid:
            continue

        certs = extract_certs_from_tx(tx)
        for cert in certs:
            try:
                state = _apply_cert_lenient(state, cert, current_epoch)
            except Exception as exc:
                logger.debug(
                    "Delegation cert error (continuing): %s", exc
                )

    return state


def _apply_cert_lenient(
    state: DelegationState,
    cert: Any,
    current_epoch: int,
) -> DelegationState:
    """Apply a single certificate to the delegation state leniently.

    During sync, we apply certificates without strict validation since
    the blocks have already been validated by the Haskell node. This
    means we skip precondition checks that would fail during replay
    (e.g., checking if a pool is already registered).

    For strict validation during our own block production, use
    ``shelley_delegation.process_certificate`` instead.

    Args:
        state: Current delegation state.
        cert: A delegation certificate.
        current_epoch: Current epoch number.

    Returns:
        Updated DelegationState.
    """
    if isinstance(cert, StakeRegistration):
        cred_hash = _credential_hash(cert.stake_credential)
        if cred_hash not in state.rewards:
            state.rewards[cred_hash] = 0
            logger.debug(
                "Registered stake key: %s", cred_hash.hex()[:16]
            )

    elif isinstance(cert, StakeDeregistration):
        cred_hash = _credential_hash(cert.stake_credential)
        state.rewards.pop(cred_hash, None)
        state.delegations.pop(cred_hash, None)
        logger.debug(
            "Deregistered stake key: %s", cred_hash.hex()[:16]
        )

    elif isinstance(cert, StakeDelegation):
        cred_hash = _credential_hash(cert.stake_credential)
        pool_hash = _pool_key_hash(cert.pool_keyhash)
        # Register the credential if not already (lenient mode)
        if cred_hash not in state.rewards:
            state.rewards[cred_hash] = 0
        state.delegations[cred_hash] = pool_hash
        logger.debug(
            "Delegated %s -> pool %s",
            cred_hash.hex()[:16], pool_hash.hex()[:16],
        )

    elif isinstance(cert, PoolRegistration):
        pool_hash = _pool_key_hash(cert.pool_params.operator)
        state.pools[pool_hash] = cert.pool_params
        # Cancel any pending retirement on re-registration
        state.retiring.pop(pool_hash, None)
        logger.debug(
            "Registered pool: %s", pool_hash.hex()[:16]
        )

    elif isinstance(cert, PoolRetirement):
        pool_hash = _pool_key_hash(cert.pool_keyhash)
        state.retiring[pool_hash] = cert.epoch
        logger.debug(
            "Pool %s retiring at epoch %d",
            pool_hash.hex()[:16], cert.epoch,
        )

    return state


# ---------------------------------------------------------------------------
# Stake distribution computation
# ---------------------------------------------------------------------------


def compute_pool_stake_distribution(
    state: DelegationState,
    utxo_stakes: dict[bytes, int],
) -> dict[bytes, int]:
    """Compute per-pool stake from delegations + UTxO balances + rewards.

    For each delegation (stake_credential -> pool_id):
        pool_stake += utxo_stake(credential) + reward_balance(credential)

    This is the core computation used at epoch boundaries to produce the
    stake snapshot for leader election (with a 2-epoch lag).

    Spec ref: Shelley spec Section 11, SNAP rule — ``stakeDistr``.
    Haskell ref: ``stakeDistr`` in ``Cardano.Ledger.Shelley.LedgerState``

    Args:
        state: Current delegation state with delegations, pools, rewards.
        utxo_stakes: Mapping from stake_credential_hash -> total lovelace
            in the UTxO set attributed to that credential.

    Returns:
        Mapping from pool_key_hash -> total delegated stake (lovelace).
        Only pools with at least one delegator appear. All registered pools
        are initialized with zero stake.
    """
    pool_stakes: dict[bytes, int] = {}

    # Initialize all registered pools with zero
    for pool_id in state.pools:
        pool_stakes[pool_id] = 0

    # Aggregate delegated stake
    for cred_hash, pool_id in state.delegations.items():
        # Only count delegations to currently registered pools
        if pool_id not in state.pools:
            continue

        utxo_balance = utxo_stakes.get(cred_hash, 0)
        reward_balance = state.rewards.get(cred_hash, 0)
        total = utxo_balance + reward_balance

        if total > 0:
            pool_stakes[pool_id] = pool_stakes.get(pool_id, 0) + total

    return pool_stakes
