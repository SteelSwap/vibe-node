"""Epoch nonce evolution — VRF-based eta accumulation and nonce hashing.

The epoch nonce is the source of per-slot leader-election randomness in
Ouroboros Praos.  Each epoch's nonce is derived from:

1. The previous epoch's nonce (``eta_0`` at the start of the epoch).
2. The hash-accumulated VRF outputs (``eta_v``) from blocks produced in
   the **first 2/3** of the previous epoch (the "stability window").
3. An optional ``extra_entropy`` injected via protocol parameter updates.

The stability window ensures that by the time 2/3 of the epoch has
elapsed, the nonce for the *next* epoch is already determined, preventing
grinding attacks in the final 1/3 of the epoch.

Hash function: Blake2b-256 throughout, matching the Haskell node.

Spec references:
    * Shelley ledger formal spec, Section 11.1 (Evolving the nonce)
    * Ouroboros Praos paper, Section 7 (Nonce evolution)
    * ``cardano-ledger/eras/shelley/impl/src/Cardano/Ledger/Shelley/Rules/Tick.hs``

Haskell references:
    * ``Cardano.Protocol.TPraos.Rules.Overlay`` — nonce construction
    * ``Cardano.Ledger.BaseTypes.Nonce`` — Nonce type (NeutralNonce | Nonce Hash)
    * ``evolveNonce`` in ``Cardano.Protocol.TPraos.API``
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction

__all__ = [
    "NEUTRAL_NONCE",
    "STABILITY_WINDOW_FRACTION",
    "EpochNonce",
    "accumulate_vrf_output",
    "evolve_nonce",
    "is_in_stability_window",
    "mk_nonce",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STABILITY_WINDOW_FRACTION = Fraction(2, 3)
"""Fraction of the epoch from which VRF outputs are collected for nonce
evolution.  Only blocks in the first 2/3 of the epoch contribute to eta_v.

Spec ref: Ouroboros Praos paper, Section 7.
Haskell ref: ``stabilityWindow`` in ``Ouroboros.Consensus.Protocol.Praos``
"""


# ---------------------------------------------------------------------------
# EpochNonce dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpochNonce:
    """A 32-byte epoch nonce used as leader-election randomness.

    Corresponds to the ``Nonce`` type in the Haskell node, specifically
    the ``Nonce (Hash Blake2b_256)`` constructor.  The neutral nonce is
    represented by 32 zero bytes.

    Spec ref: Shelley ledger formal spec, Section 11.1.
    Haskell ref: ``Cardano.Ledger.BaseTypes.Nonce``
    """

    value: bytes
    """32-byte Blake2b-256 hash."""

    def __post_init__(self) -> None:
        if len(self.value) != 32:
            raise ValueError(f"EpochNonce must be exactly 32 bytes, got {len(self.value)}")

    def __repr__(self) -> str:
        return f"EpochNonce({self.value.hex()[:16]}...)"


NEUTRAL_NONCE = EpochNonce(b"\x00" * 32)
"""The neutral (identity) nonce — used before any VRF outputs are collected.

Haskell ref: ``NeutralNonce`` constructor of ``Nonce``.
"""


# ---------------------------------------------------------------------------
# Nonce construction helpers
# ---------------------------------------------------------------------------


def mk_nonce(data: bytes) -> EpochNonce:
    """Create a nonce by hashing arbitrary data with Blake2b-256.

    Haskell ref: ``mkNonceFromOutputVRF`` — hashes the VRF output to produce
    a ``Nonce``.
    """
    h = hashlib.blake2b(data, digest_size=32).digest()
    return EpochNonce(h)


# ---------------------------------------------------------------------------
# Stability window
# ---------------------------------------------------------------------------


def stability_window(
    epoch_length: int,
    security_param: int = 0,
    active_slot_coeff: float = 0.0,
) -> int:
    """Return the stability window size for the given parameters.

    Haskell ref: ``stabilityWindow`` in ``Ouroboros.Consensus.Protocol.Praos``
        stabilityWindow = 3 * k / f

    If security_param (k) and active_slot_coeff (f) are provided, uses the
    Haskell formula ``3 * k / f``, capped at epoch_length.  Otherwise falls
    back to the legacy 2/3 * epoch_length approximation.

    Args:
        epoch_length: Number of slots per epoch.
        security_param: Security parameter k (0 = use fallback).
        active_slot_coeff: Active slot coefficient f (0.0 = use fallback).

    Returns:
        Number of slots in the stability window.
    """
    if security_param > 0 and active_slot_coeff > 0.0:
        window = int(3 * security_param / active_slot_coeff)
        return min(window, epoch_length)
    # Fallback: 2/3 of epoch (approximate, correct for mainnet-like params)
    return (epoch_length * 2) // 3


def is_in_stability_window(
    slot: int,
    epoch_start_slot: int,
    epoch_length: int,
    security_param: int = 0,
    active_slot_coeff: float = 0.0,
) -> bool:
    """Return True if *slot* falls within the stability window of its epoch.

    Only VRF outputs from blocks in this window contribute to the next
    epoch's nonce.

    Spec ref: Ouroboros Praos, Section 7.
    Haskell ref: ``stabilityWindow`` in ``Ouroboros.Consensus.Protocol.Praos``

    Args:
        slot: The absolute slot number to check.
        epoch_start_slot: The first slot of the epoch containing *slot*.
        epoch_length: Number of slots per epoch.
        security_param: Security parameter k (0 = use 2/3 fallback).
        active_slot_coeff: Active slot coefficient f (0.0 = use fallback).

    Returns:
        True if the slot is in the stability window.
    """
    slot_in_epoch = slot - epoch_start_slot
    window = stability_window(epoch_length, security_param, active_slot_coeff)
    return slot_in_epoch < window


# ---------------------------------------------------------------------------
# VRF output accumulation
# ---------------------------------------------------------------------------


def accumulate_vrf_output(current_eta: bytes, vrf_output: bytes) -> bytes:
    """Accumulate a VRF output into the running hash (eta_v).

    Each block's VRF output is folded into the running accumulator:

        eta_v' = Blake2b-256(eta_v || vrf_output)

    This is called for every block in the stability window of an epoch.

    Spec ref: Shelley ledger formal spec, Section 11.1, ``hashHeaderNonce``.
    Haskell ref: The nonce is accumulated in ``tickChainDepState`` by hashing
        the VRF output into the evolving nonce.

    Args:
        current_eta: Current accumulator (32 bytes, or empty for initial).
        vrf_output: The VRF output from a block header.

    Returns:
        Updated 32-byte accumulator.
    """
    h = hashlib.blake2b(current_eta + vrf_output, digest_size=32)
    return h.digest()


# ---------------------------------------------------------------------------
# Epoch nonce evolution
# ---------------------------------------------------------------------------


def evolve_nonce(
    prev_nonce: EpochNonce,
    eta_v: bytes,
    extra_entropy: bytes | None = None,
) -> EpochNonce:
    """Evolve the epoch nonce at an epoch boundary.

    At the transition from epoch N to epoch N+1:

        eta_0(N+1) = Blake2b-256(eta_0(N) || eta_v(N))

    where eta_v(N) is the hash-accumulated VRF outputs from the first 2/3
    of epoch N.

    If an ``extra_entropy`` value is set via a protocol parameter update
    (used for hard-fork combinator nonce injection), it is mixed in:

        eta_0(N+1) = Blake2b-256(eta_0(N+1) || extra_entropy)

    Spec ref: Shelley ledger formal spec, Section 11.1, ``evolveNonce``.
    Haskell ref: ``evolveNonce`` in ``Cardano.Protocol.TPraos.API``

    Args:
        prev_nonce: The nonce from the previous epoch (eta_0(N)).
        eta_v: The accumulated VRF hash from the stability window (32 bytes).
        extra_entropy: Optional extra entropy from protocol param updates.

    Returns:
        The new epoch nonce for the next epoch.
    """
    # Step 1: Combine previous nonce with accumulated VRF outputs
    new_value = hashlib.blake2b(prev_nonce.value + eta_v, digest_size=32).digest()

    # Step 2: Mix in extra entropy if present
    if extra_entropy is not None:
        new_value = hashlib.blake2b(new_value + extra_entropy, digest_size=32).digest()

    return EpochNonce(new_value)
