"""Block forging loop -- VRF leader election and block production.

Runs as an OS thread (not async). Uses threading.Event for slot timing
and block arrival notification. Acquires RWLock on ChainDB and
NodeKernel for thread-safe access to shared state.

Haskell references:
    - Ouroboros.Consensus.Node (forgeBlock)
    - Ouroboros.Consensus.Shelley.Node.Forging (forgeShelleyBlock)
    - The Haskell forge thread blocks on blockProcessed TMVar.

Spec references:
    - Ouroboros Praos paper, Section 4 -- protocol execution
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from .config import NodeConfig

__all__ = ["forge_loop"]

logger = logging.getLogger(__name__)


def forge_loop(
    config: NodeConfig,
    slot_config: Any,
    shutdown_event: threading.Event,
    block_received_event: threading.Event,
    chain_db: Any = None,
    node_kernel: Any = None,
    mempool: Any = None,
    peer_tip_tvar: Any = None,
) -> None:
    """Slot-by-slot leader check and block forging loop.

    Runs as a regular OS thread function (NOT async). Wakes on either
    the next slot boundary or when a new block arrives from a peer.

    Haskell ref:
        ``Ouroboros.Consensus.Node.forgeBlock``
        The Haskell forge thread uses STM to block on blockProcessed.
        We use threading.Event.wait(timeout) for the same effect.
    """
    if config.pool_keys is None:
        return

    import hashlib

    import cbor2pure as cbor2
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from vibe.cardano.consensus.slot_arithmetic import (
        slot_to_wall_clock,
        wall_clock_to_slot,
    )
    from vibe.cardano.crypto.kes import (
        CARDANO_KES_DEPTH,
        kes_derive_vk,
        kes_keygen,
        kes_update,
    )
    from vibe.cardano.crypto.ocert import (
        OperationalCert,
        ocert_signed_payload,
        slot_to_kes_period,
    )
    from vibe.cardano.forge.block import forge_block
    from vibe.cardano.forge.leader import check_leadership

    pool_keys = config.pool_keys

    # --- Initialise forge credentials (same as before) ---
    if pool_keys.kes_sk:
        from vibe.cardano.crypto.kes_serialization import deserialize_kes_sk

        try:
            kes_sk = deserialize_kes_sk(pool_keys.kes_sk, CARDANO_KES_DEPTH)
            kes_vk = kes_derive_vk(kes_sk)
            logger.info("KES key loaded (%d bytes)", len(pool_keys.kes_sk))
        except Exception as exc:
            logger.warning("Failed to deserialize KES key (%s), generating fresh", exc)
            kes_sk = kes_keygen(CARDANO_KES_DEPTH)
            kes_vk = kes_derive_vk(kes_sk)
    else:
        kes_sk = kes_keygen(CARDANO_KES_DEPTH)
        kes_vk = kes_derive_vk(kes_sk)

    if pool_keys.ocert:
        import cbor2pure as _cbor2

        try:
            ocert_data = _cbor2.loads(pool_keys.ocert)
            inner = ocert_data[0] if isinstance(ocert_data, list) else ocert_data
            ocert = OperationalCert(
                kes_vk=bytes(inner[0]),
                cert_count=inner[1],
                kes_period_start=inner[2],
                cold_sig=bytes(inner[3]),
            )
            logger.info("Operational certificate loaded (cert_count=%d)", ocert.cert_count)
        except Exception as exc:
            logger.warning("Failed to parse opcert (%s), signing fresh", exc)
            ocert_payload = ocert_signed_payload(kes_vk, cert_count=0, kes_period_start=0)
            cold_sk_ed = Ed25519PrivateKey.from_private_bytes(pool_keys.cold_sk)
            cold_sig = cold_sk_ed.sign(ocert_payload)
            ocert = OperationalCert(
                kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig
            )
    elif pool_keys.cold_sk:
        ocert_payload = ocert_signed_payload(kes_vk, cert_count=0, kes_period_start=0)
        cold_sk_ed = Ed25519PrivateKey.from_private_bytes(pool_keys.cold_sk)
        cold_sig = cold_sk_ed.sign(ocert_payload)
        ocert = OperationalCert(kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig)
    else:
        logger.error("No opcert or cold signing key — cannot forge blocks")
        return

    # Initial nonce + stake from kernel
    epoch_nonce = (
        node_kernel.epoch_nonce.value
        if node_kernel is not None
        else hashlib.blake2b(config.network_magic.to_bytes(4, "big"), digest_size=32).digest()
    )

    pool_id = hashlib.blake2b(pool_keys.cold_vk, digest_size=28).digest()
    if node_kernel is not None and node_kernel.stake_distribution:
        pool_stake = node_kernel.stake_distribution.get(pool_id, 0)
        total_stake = sum(node_kernel.stake_distribution.values())
        relative_stake = pool_stake / total_stake if total_stake > 0 else 0.0
    else:
        relative_stake = 1.0 / 3.0

    # KES evolution
    slots_per_kes = config.slots_per_kes_period
    current_slot = wall_clock_to_slot(datetime.now(UTC), slot_config)
    current_kes_period = (
        slot_to_kes_period(
            current_slot,
            slots_per_kes_period=slots_per_kes,
        )
        - ocert.kes_period_start
    )

    if current_kes_period < 0:
        current_kes_period = 0
    if current_kes_period > 0:
        for p in range(current_kes_period):
            evolved = kes_update(kes_sk, p)
            if evolved is None:
                logger.error("KES key expired at period %d", p)
                return
            kes_sk = evolved

    _current_kes_period = current_kes_period

    # Read initial tip
    prev_block_number = 0
    prev_header_hash: bytes | None = None
    if chain_db is not None:
        with chain_db._lock.read():
            if chain_db._tip is not None:
                prev_header_hash = chain_db._tip.block_hash
                prev_block_number = chain_db._tip.block_number

    blocks_forged = 0
    last_checked_slot = -1  # Track last slot we checked to avoid duplicates

    logger.info(
        "Forge loop started (stake=%.2f%%, kes_period=%d)",
        relative_stake * 100,
        _current_kes_period,
        extra={
            "event": "forge.started",
            "vrf_vk": pool_keys.vrf_vk.hex()[:16],
            "kes_vk": kes_vk.hex()[:16],
            "relative_stake_pct": relative_stake * 100,
            "kes_period": _current_kes_period,
        },
    )

    # ---------------------------------------------------------------
    # Wait for initial peer sync before forging
    # ---------------------------------------------------------------
    # Haskell's forge loop blocks in an STM retry on CurrentSlotUnknown
    # until the node is synced. We approximate this by waiting for the
    # peer_tip_tvar to become non-zero, meaning at least one peer has
    # announced a chain tip via chain-sync. Without this gate, the
    # forge loop races ahead building a divergent chain before hearing
    # from any peers.
    if peer_tip_tvar is not None and chain_db is not None:
        logger.info("Forge loop waiting for initial peer sync...")
        while not shutdown_event.is_set():
            peer_bn = peer_tip_tvar.value
            our_tip = chain_db.tip_tvar.value
            our_bn = our_tip.block_number if our_tip is not None else 0
            if peer_bn > 0 and our_bn >= peer_bn:
                logger.info(
                    "Forge loop: synced with peers (our_bn=%d peer_bn=%d), starting",
                    our_bn, peer_bn,
                )
                break
            if peer_bn > 0 and our_bn < peer_bn:
                logger.debug(
                    "Forge loop: syncing (our_bn=%d peer_bn=%d)",
                    our_bn, peer_bn,
                )
            # Check every 200ms — block-fetch brings us up to speed
            block_received_event.wait(timeout=0.2)
            block_received_event.clear()

    # ---------------------------------------------------------------
    # Main forge loop — runs until shutdown
    # ---------------------------------------------------------------

    while not shutdown_event.is_set():
        # Wait for next slot OR new block arrival (whichever first).
        # This is the key difference from the async version: we wake
        # immediately when a block arrives, eliminating one-slot lag.
        next_slot = wall_clock_to_slot(datetime.now(UTC), slot_config) + 1
        next_slot_time = slot_to_wall_clock(next_slot, slot_config)
        timeout = max(0.0, (next_slot_time - datetime.now(UTC)).total_seconds())

        block_received_event.wait(timeout=timeout)
        block_received_event.clear()

        if shutdown_event.is_set():
            return

        slot = wall_clock_to_slot(datetime.now(UTC), slot_config)

        # Skip if we already checked this slot — prevents forging
        # duplicate blocks when block_received_event wakes us mid-slot.
        # Haskell's forge loop only checks each slot once.
        if slot <= last_checked_slot:
            continue
        last_checked_slot = slot

        # Evolve KES key if period has advanced
        new_kes_period = (
            slot_to_kes_period(
                slot,
                slots_per_kes_period=slots_per_kes,
            )
            - ocert.kes_period_start
        )
        if new_kes_period > _current_kes_period:
            for p in range(_current_kes_period, new_kes_period):
                evolved = kes_update(kes_sk, p)
                if evolved is None:
                    logger.error("KES key expired at period %d", p)
                    return
                kes_sk = evolved
            _current_kes_period = new_kes_period

        # --- STM transaction: read state + check + forge ---
        # Reads tip, nonce, stake via TVars. If any change between
        # read and commit (e.g., header processing on Thread 2),
        # the transaction retries automatically.
        # Haskell ref: the forge loop uses STM to read getCurrentChain
        # and tickChainDepState atomically.
        from vibe.core.stm import atomically

        def _forge_tx(tx):
            """STM transaction: read shared state, check leadership, forge."""
            # Read tip from ChainDB TVar
            tip_val = tx.read(chain_db.tip_tvar) if chain_db is not None else None
            if tip_val is not None:
                # Haskell uses 3k/f as the syncing threshold. With
                # activeSlotsCoeff=0.1 and k=10 that's 300 seconds.
                # Using ceil(3k/f) slots to match Haskell's maxRollbacks.
                max_behind = int(3 * config.security_param / config.active_slot_coeff)
                if slot - tip_val.slot > max_behind:
                    return None  # Still syncing
            elif slot > 10:
                return None

            # Read nonce + stake from NodeKernel TVars
            nonce_val = tx.read(chain_db.praos_nonce_tvar) if chain_db is not None else epoch_nonce
            stake_val = tx.read(node_kernel.stake_tvar) if node_kernel is not None else {}

            return {
                "tip": tip_val,
                "nonce": nonce_val,
                "stake": stake_val,
            }

        snapshot = atomically(_forge_tx)
        if snapshot is None:
            continue

        # Extract snapshot values
        tip_snap = snapshot["tip"]
        if tip_snap is not None:
            # Epoch boundary guard: if the forge slot is in a newer epoch
            # than the tip AND the nonce hasn't been updated yet, the
            # epoch boundary block is still queued. Skip this slot.
            # But if tip_epoch matches forge_epoch (nonce was updated
            # by a block in this epoch), proceed — don't lose the slot.
            tip_epoch = tip_snap.slot // config.epoch_length
            forge_epoch = slot // config.epoch_length
            if forge_epoch > tip_epoch + 1:
                # More than 1 epoch behind — definitely stale
                logger.debug(
                    "Forge.Loop.EpochBoundarySkip: slot=%d forge_epoch=%d tip_epoch=%d",
                    slot, forge_epoch, tip_epoch,
                )
                continue
            if forge_epoch == tip_epoch + 1:
                # Exactly 1 epoch ahead — the boundary block may not
                # have been processed yet. Only skip if no block from
                # the new epoch exists on our chain (tip is still in
                # the old epoch).
                logger.debug(
                    "Forge.Loop.EpochBoundaryWait: slot=%d forge_epoch=%d tip_epoch=%d",
                    slot, forge_epoch, tip_epoch,
                )
                continue

            prev_header_hash = tip_snap.block_hash
            prev_block_number = tip_snap.block_number

        epoch_nonce = snapshot["nonce"]
        stake_snap = snapshot["stake"]
        if stake_snap:
            pool_stake = stake_snap.get(pool_id, 0)
            total_stake = sum(stake_snap.values())
            relative_stake = pool_stake / total_stake if total_stake > 0 else relative_stake

        # --- VRF leader check (pure computation, no shared state) ---
        logger.debug(
            "Forge.Loop.VRFCheck: slot=%d nonce=%s nonce_len=%d",
            slot, epoch_nonce.hex(), len(epoch_nonce),
        )
        proof = check_leadership(
            slot=slot,
            vrf_sk=pool_keys.vrf_sk,
            pool_vrf_vk=pool_keys.vrf_vk,
            relative_stake=relative_stake,
            active_slot_coeff=config.active_slot_coeff,
            epoch_nonce=epoch_nonce,
        )

        if proof is None:
            continue

        # --- Check if behind peer tip — skip forge if clearly orphaned ---
        # Only skip if the peer is MORE than 1 block ahead. At the same
        # height (peer_bn == prev_block_number + 1), our block could win
        # via VRF tiebreak (lower VRF output wins in Praos comparePraos).
        if peer_tip_tvar is not None:
            peer_bn = peer_tip_tvar.value
            if peer_bn > prev_block_number + 1:
                logger.info(
                    "Skipping forge at slot %d — peer tip block_no %d > ours %d",
                    slot, peer_bn, prev_block_number,
                )
                continue

        # --- Forge block (pure computation, no shared state) ---
        t_forge_start = time.monotonic()
        try:
            forged = forge_block(
                leader_proof=proof,
                prev_block_number=prev_block_number,
                prev_header_hash=prev_header_hash,
                mempool_txs=[],
                kes_sk=kes_sk,
                kes_period=_current_kes_period,
                ocert=ocert,
                pool_vk=pool_keys.cold_vk,
                vrf_vk=pool_keys.vrf_vk,
            )

            t_forge_done = time.monotonic()

            blocks_forged += 1
            forged_predecessor = prev_header_hash or b"\x00" * 32

            # --- Store forged block ---
            if chain_db is not None:
                result = chain_db.add_block(
                    slot=forged.block.slot,
                    block_hash=forged.block.block_hash,
                    predecessor_hash=forged_predecessor,
                    block_number=forged.block.block_number,
                    cbor_bytes=forged.cbor,
                    header_cbor=[6, cbor2.CBORTag(24, forged.block.header_cbor)],
                    vrf_output=proof.vrf_output,
                )

                t_store_done = time.monotonic()
                logger.info(
                    "Forge.Loop.Timing: slot=%d forge=%.1fms store=%.1fms total=%.1fms",
                    forged.block.slot,
                    (t_forge_done - t_forge_start) * 1000,
                    (t_store_done - t_forge_done) * 1000,
                    (t_store_done - t_forge_start) * 1000,
                )

                if not result.adopted:
                    logger.info(
                        "Forged block #%d at slot %d orphaned (tip changed)",
                        forged.block.block_number,
                        forged.block.slot,
                    )
                    continue

            prev_block_number = forged.block.block_number
            prev_header_hash = forged.block.block_hash

            tx_count = (
                len(forged.block.transactions) if hasattr(forged.block, "transactions") else 0
            )
            logger.info(
                "Forged block #%d at slot %d (%d txs, %d bytes)",
                forged.block.block_number,
                forged.block.slot,
                tx_count,
                len(forged.cbor),
                extra={
                    "event": "forge.block",
                    "block_number": forged.block.block_number,
                    "slot": forged.block.slot,
                    "tx_count": tx_count,
                    "size_bytes": len(forged.cbor),
                    "hash": forged.block.block_hash.hex()[:16],
                    "blocks_forged": blocks_forged,
                },
            )
            # Haskell-matching forge event for log correlation
            logger.info(
                "Forge.Loop.ForgedBlock: slot=%d hash=%s block_no=%d vrf_out=%s nonce=%s",
                forged.block.slot,
                forged.block.block_hash.hex(),
                forged.block.block_number,
                proof.vrf_output.hex(),
                epoch_nonce.hex(),
            )
        except Exception as exc:
            logger.error("Failed to forge block at slot %d: %s", slot, exc)
