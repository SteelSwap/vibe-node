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
from datetime import datetime, timezone
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

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import cbor2pure as cbor2

    from vibe.cardano.consensus.slot_arithmetic import (
        SlotConfig,
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
            ocert = OperationalCert(kes_vk=kes_vk, cert_count=0, kes_period_start=0, cold_sig=cold_sig)
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
    current_slot = wall_clock_to_slot(datetime.now(timezone.utc), slot_config)
    current_kes_period = slot_to_kes_period(
        current_slot, slots_per_kes_period=slots_per_kes,
    ) - ocert.kes_period_start

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

    logger.info(
        "Forge loop started (stake=%.2f%%, kes_period=%d)",
        relative_stake * 100, _current_kes_period,
        extra={
            "event": "forge.started",
            "vrf_vk": pool_keys.vrf_vk.hex()[:16],
            "kes_vk": kes_vk.hex()[:16],
            "relative_stake_pct": relative_stake * 100,
            "kes_period": _current_kes_period,
        },
    )

    # ---------------------------------------------------------------
    # Main forge loop — runs until shutdown
    # ---------------------------------------------------------------

    while not shutdown_event.is_set():
        # Wait for next slot OR new block arrival (whichever first).
        # This is the key difference from the async version: we wake
        # immediately when a block arrives, eliminating one-slot lag.
        next_slot = wall_clock_to_slot(datetime.now(timezone.utc), slot_config) + 1
        next_slot_time = slot_to_wall_clock(next_slot, slot_config)
        timeout = max(0.0, (next_slot_time - datetime.now(timezone.utc)).total_seconds())

        block_received_event.wait(timeout=timeout)
        block_received_event.clear()

        if shutdown_event.is_set():
            return

        slot = wall_clock_to_slot(datetime.now(timezone.utc), slot_config)

        # Evolve KES key if period has advanced
        new_kes_period = slot_to_kes_period(
            slot, slots_per_kes_period=slots_per_kes,
        ) - ocert.kes_period_start
        if new_kes_period > _current_kes_period:
            for p in range(_current_kes_period, new_kes_period):
                evolved = kes_update(kes_sk, p)
                if evolved is None:
                    logger.error("KES key expired at period %d", p)
                    return
                kes_sk = evolved
            _current_kes_period = new_kes_period

        # --- Read current chain state (read lock) ---
        if chain_db is not None:
            with chain_db._lock.read():
                tip = chain_db._tip
                if tip is not None:
                    if slot - tip.slot > 10:
                        # Still syncing — too far behind
                        continue
                    prev_header_hash = tip.block_hash
                    prev_block_number = tip.block_number
                elif slot > 10:
                    continue

        # --- Tick epoch + read nonce (kernel lock) ---
        if node_kernel is not None:
            with node_kernel._lock.write():
                current_epoch = slot // config.epoch_length if config.epoch_length > 0 else 0
                if current_epoch > node_kernel.current_epoch:
                    node_kernel.on_epoch_boundary(current_epoch)
            with node_kernel._lock.read():
                epoch_nonce = node_kernel.epoch_nonce.value
                if node_kernel.stake_distribution:
                    pool_stake = node_kernel.stake_distribution.get(pool_id, 0)
                    total_stake = sum(node_kernel.stake_distribution.values())
                    relative_stake = pool_stake / total_stake if total_stake > 0 else relative_stake

        # --- VRF leader check (no lock — pure computation) ---
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

        # --- Forge block (no lock — pure computation) ---
        try:
            forged = forge_block(
                leader_proof=proof,
                prev_block_number=prev_block_number,
                prev_header_hash=prev_header_hash,
                mempool_txs=[],  # TODO: sync mempool access
                kes_sk=kes_sk,
                kes_period=_current_kes_period,
                ocert=ocert,
                pool_vk=pool_keys.cold_vk,
                vrf_vk=pool_keys.vrf_vk,
            )

            blocks_forged += 1
            forged_predecessor = prev_header_hash or b"\x00" * 32

            # --- Store in ChainDB (write lock) ---
            if chain_db is not None:
                with chain_db._lock.write():
                    result = chain_db.add_block_sync(
                        slot=forged.block.slot,
                        block_hash=forged.block.block_hash,
                        predecessor_hash=forged_predecessor,
                        block_number=forged.block.block_number,
                        cbor_bytes=forged.cbor,
                        header_cbor=[6, cbor2.CBORTag(24, forged.block.header_cbor)],
                        vrf_output=proof.vrf_output,
                    )
                if not result.adopted:
                    logger.info(
                        "Forged block #%d at slot %d orphaned (tip changed)",
                        forged.block.block_number, forged.block.slot,
                    )
                    continue

                # Nonce update (kernel write lock)
                if node_kernel is not None:
                    with node_kernel._lock.write():
                        node_kernel.on_block_adopted(
                            forged.block.slot, forged.block.block_hash,
                            forged_predecessor, proof.vrf_output,
                        )

            prev_block_number = forged.block.block_number
            prev_header_hash = forged.block.block_hash

            tx_count = len(forged.block.transactions) if hasattr(forged.block, "transactions") else 0
            logger.info(
                "Forged block #%d at slot %d (%d txs, %d bytes)",
                forged.block.block_number, forged.block.slot,
                tx_count, len(forged.cbor),
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
        except Exception as exc:
            logger.error("Failed to forge block at slot %d: %s", slot, exc)
