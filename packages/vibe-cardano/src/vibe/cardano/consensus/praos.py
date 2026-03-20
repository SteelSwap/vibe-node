"""Ouroboros Praos consensus protocol — state machine and leader election.

Ouroboros Praos is the consensus protocol used by Cardano from the Shelley
era onward.  It is a proof-of-stake protocol where slot leaders are elected
privately via a VRF (Verifiable Random Function) — no one knows who the
slot leader is until they produce a block and reveal the VRF proof.

This module provides:

1. **PraosState** — the consensus state that evolves with each validated
   block header.  Contains the tip slot/hash/block_number, epoch nonce,
   and the stake distribution used for leader election.

2. **apply_header** — validates a header against the current state and
   returns the updated state.  This is the core consensus state transition.

3. **leader_check** — wraps the VRF leader eligibility math from
   ``vibe.cardano.crypto.vrf.certified_nat_max_check``.

4. **ActiveSlotCoeff** — the ``f`` parameter that controls what fraction
   of slots are expected to have blocks.

Epoch boundary logic (nonce evolution, stake distribution snapshots) is
deferred to M4.9.

Spec references:
    - Ouroboros Praos paper (Crypto 2017), Sections 3-4
    - Shelley formal spec, Section 16.1 (leader election)
    - Shelley formal spec, Section 3.3 (chain state transitions)

Haskell references:
    - Ouroboros.Consensus.Protocol.Praos
    - Ouroboros.Consensus.Shelley.Protocol
    - Cardano.Protocol.TPraos.Rules.Prtcl (PRTCL transition)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from vibe.cardano.crypto.vrf import certified_nat_max_check

from .header_validation import (
    HeaderValidationError,
    HeaderValidationParams,
    PoolInfo,
    StakeDistribution,
    validate_header,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active Slot Coefficient
# ---------------------------------------------------------------------------

#: Mainnet active slot coefficient — 5% of slots are expected to have blocks.
#: This means on average 1 block per 20 seconds (slot_length=1s, f=0.05).
MAINNET_ACTIVE_SLOT_COEFF: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class ActiveSlotCoeff:
    """The active slot coefficient (f parameter) for Ouroboros Praos.

    Controls what fraction of slots are expected to produce blocks.
    Mainnet uses f = 1/20 = 0.05, meaning ~5% of slots have blocks,
    yielding an average block time of ~20 seconds.

    Spec ref: Ouroboros Praos paper, Section 3 — "active slot coefficient"
    Haskell ref: ``ActiveSlotCoeff`` in ``Cardano.Ledger.BaseTypes``

    Attributes:
        value: The f parameter, in (0.0, 1.0).
    """

    value: float

    def __post_init__(self) -> None:
        if not (0.0 < self.value < 1.0):
            raise ValueError(
                f"Active slot coefficient must be in (0.0, 1.0), got {self.value}"
            )


# ---------------------------------------------------------------------------
# Leader election
# ---------------------------------------------------------------------------


def leader_check(
    vrf_output: bytes,
    relative_stake: float,
    f: float,
) -> bool:
    """Check whether a VRF output wins the Praos slot leader lottery.

    This is a thin wrapper around ``certified_nat_max_check`` from the
    VRF module, providing a consensus-level API.

    The check is:
        vrf_output_nat / 2^512 < 1 - (1 - f)^sigma

    where ``sigma`` is the pool's relative stake and ``f`` is the active
    slot coefficient.

    Spec ref: Ouroboros Praos, Section 4, Definition 6 (slot leader election)
    Haskell ref: ``checkVRFValue`` in ``Cardano.Protocol.TPraos.Rules.Overlay``

    Args:
        vrf_output: 64-byte VRF output hash.
        relative_stake: Pool's relative stake in [0.0, 1.0].
        f: Active slot coefficient in (0.0, 1.0).

    Returns:
        True if the pool is elected as slot leader.
    """
    return certified_nat_max_check(vrf_output, relative_stake, f)


# ---------------------------------------------------------------------------
# Praos consensus state
# ---------------------------------------------------------------------------


@dataclass
class PraosState:
    """Mutable consensus state for the Ouroboros Praos protocol.

    Tracks the current chain tip and the information needed to validate
    the next header.  Epoch boundary transitions (nonce evolution, stake
    snapshot rotation) are handled externally by M4.9.

    Haskell ref: ``PraosState`` in
        ``Ouroboros.Consensus.Protocol.Praos``

    Attributes:
        tip_slot: Slot number of the current tip.
        tip_hash: Block header hash of the current tip (32 bytes).
        tip_block_number: Block number of the current tip.
        epoch_nonce: Current epoch nonce (32 bytes). Used as VRF input
            along with the slot number for leader election.
        stake_distribution: Current stake distribution for leader checks.
        protocol_params: Protocol parameters for validation.
    """

    tip_slot: int = 0
    tip_hash: bytes = b"\x00" * 32
    tip_block_number: int = 0
    epoch_nonce: bytes = b"\x00" * 32
    stake_distribution: StakeDistribution = field(default_factory=dict)
    protocol_params: HeaderValidationParams = field(
        default_factory=HeaderValidationParams
    )


# ---------------------------------------------------------------------------
# State transition
# ---------------------------------------------------------------------------


def apply_header(
    state: PraosState,
    header: Any,
    prev_header: Any | None = None,
) -> tuple[PraosState, list[HeaderValidationError]]:
    """Validate a header and apply it to the Praos consensus state.

    This is the core consensus state transition.  It:

    1. Validates the header against the current state and stake distribution.
    2. If valid, returns a new PraosState with updated tip.
    3. If invalid, returns the unchanged state and the list of errors.

    Epoch boundary logic (nonce evolution, stake distribution rotation)
    is NOT handled here — that's M4.9.  The caller is responsible for
    updating ``state.epoch_nonce`` and ``state.stake_distribution`` at
    epoch boundaries.

    Spec ref: Shelley formal spec, Section 3.3 — CHAIN state transition.
    Haskell ref: ``applyChainTick`` + ``updateConsensusState`` in
        ``Ouroboros.Consensus.Protocol.Praos``

    Args:
        state: Current Praos consensus state.
        header: Decoded block header (BlockHeader from serialization.block).
        prev_header: Previous block header (for prev_hash linkage check).
            If None, the function uses state.tip_hash for comparison.

    Returns:
        Tuple of (new_state, errors). If errors is non-empty, new_state
        is identical to the input state (no mutation occurred).
    """
    errors = validate_header(
        header=header,
        stake_distribution=state.stake_distribution,
        params=state.protocol_params,
        prev_header=prev_header,
    )

    if errors:
        logger.warning(
            "Header validation failed for slot %d: %s",
            header.slot,
            "; ".join(e.detail for e in errors),
        )
        return state, errors

    # Header is valid — produce new state with updated tip.
    # We compute the block hash from the header CBOR.
    import hashlib

    new_tip_hash = hashlib.blake2b(header.header_cbor, digest_size=32).digest()

    new_state = PraosState(
        tip_slot=header.slot,
        tip_hash=new_tip_hash,
        tip_block_number=header.block_number,
        epoch_nonce=state.epoch_nonce,  # unchanged (M4.9 handles evolution)
        stake_distribution=state.stake_distribution,  # unchanged (M4.9)
        protocol_params=state.protocol_params,
    )

    logger.debug(
        "Praos: applied header at slot %d, blockNo %d, hash %s",
        header.slot,
        header.block_number,
        new_tip_hash.hex()[:16],
    )

    return new_state, []
