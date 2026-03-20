"""VRF (Verifiable Random Function) for Ouroboros Praos leader election.

Cardano uses ECVRF-ED25519-SHA512-Elligator2 (draft-irtf-cfrg-vrf-03)
for slot leader election. The cryptographic operations are provided by
the IOG fork of libsodium which adds ``crypto_vrf_*`` functions.

This module provides:

1. **Pure Python leader check math** — the ``certified_nat_max_check``
   function implements the Praos leader eligibility formula using
   ``decimal.Decimal`` for exact arithmetic. This is what consensus needs.

2. **Optional native VRF operations** — if the ``_vrf_native`` pybind11
   extension is built (wrapping the IOG libsodium fork), ``vrf_verify``,
   ``vrf_prove``, ``vrf_proof_to_hash``, and ``vrf_keypair`` delegate
   to the C library. Otherwise they raise ``NotImplementedError``.

   The pybind11 extension replaces the previous ctypes-based approach
   for better type safety, error handling, and build reproducibility.

Spec references:
    - Ouroboros Praos paper, Section 4 (leader election)
    - Cardano Shelley formal spec, Section 16.1 (VRF verification)
    - draft-irtf-cfrg-vrf-03 (ECVRF construction)
    - Haskell: Cardano.Protocol.TPraos.Rules.Overlay (certifiedVRF)
"""

from __future__ import annotations

import logging
from decimal import Decimal, getcontext
from typing import Final

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VRF_PROOF_SIZE: Final[int] = 80
"""Size of a VRF proof in bytes (Gamma || c || s)."""

VRF_OUTPUT_SIZE: Final[int] = 64
"""Size of a VRF output (hash) in bytes — SHA-512 of the proof."""

VRF_PK_SIZE: Final[int] = 32
"""Size of a VRF public key in bytes (Ed25519 point)."""

VRF_SK_SIZE: Final[int] = 64
"""Size of a VRF secret key in bytes (Ed25519 scalar + public key)."""

# The maximum value of a 512-bit unsigned integer, used as the denominator
# when converting a VRF output to a rational number in [0, 1).
_2_POW_512: Final[int] = 2**512

# ---------------------------------------------------------------------------
# Native VRF bindings via pybind11 (optional)
# ---------------------------------------------------------------------------

HAS_VRF_NATIVE: bool = False
"""True if the _vrf_native pybind11 extension is available."""

try:
    from vibe.cardano.crypto._vrf_native import (
        vrf_keypair as _native_keypair,
        vrf_prove as _native_prove,
        vrf_proof_to_hash as _native_proof_to_hash,
        vrf_verify as _native_verify,
    )

    HAS_VRF_NATIVE = True
    logger.info("_vrf_native pybind11 extension loaded — native VRF available")
except ImportError:
    _native_keypair = None
    _native_prove = None
    _native_proof_to_hash = None
    _native_verify = None
    logger.debug(
        "_vrf_native extension not available — VRF operations "
        "will raise NotImplementedError. Build with CMake to enable."
    )


# ---------------------------------------------------------------------------
# VRF operations
# ---------------------------------------------------------------------------


def vrf_keypair() -> tuple[bytes, bytes]:
    """Generate a VRF keypair.

    Returns a tuple ``(public_key, secret_key)`` where:
      - ``public_key`` is 32 bytes (Ed25519 point)
      - ``secret_key`` is 64 bytes (Ed25519 scalar + public key)

    Uses the ECVRF-ED25519-SHA512-Elligator2 (draft-03) construction
    from the IOG libsodium fork.

    Raises
    ------
    NotImplementedError
        If the native VRF extension is not available.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF keypair generation requires the _vrf_native extension. "
            "Build with CMake to enable native VRF support."
        )
    return _native_keypair()


def vrf_prove(sk: bytes, alpha: bytes) -> bytes:
    """Generate a VRF proof for the given alpha string.

    Parameters
    ----------
    sk:
        VRF secret key (64 bytes).
    alpha:
        Input message / alpha string (arbitrary length). Typically
        the encoded slot number or epoch nonce.

    Returns
    -------
    bytes
        The 80-byte VRF proof.

    Raises
    ------
    NotImplementedError
        If the native VRF extension is not available.
    ValueError
        If ``sk`` has incorrect size.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF prove requires the _vrf_native extension. "
            "Build with CMake to enable native VRF support."
        )

    if len(sk) != VRF_SK_SIZE:
        msg = f"VRF secret key must be {VRF_SK_SIZE} bytes, got {len(sk)}"
        raise ValueError(msg)

    return _native_prove(sk, alpha)


def vrf_verify(pk: bytes, proof: bytes, alpha: bytes) -> bytes | None:
    """Verify a VRF proof and return the output hash, or None on failure.

    Parameters
    ----------
    pk:
        VRF public key (32 bytes).
    proof:
        VRF proof (80 bytes).
    alpha:
        Input message (the VRF "alpha string" — typically the encoded
        slot number or nonce).

    Returns
    -------
    bytes | None
        The 64-byte VRF output if verification succeeds, or ``None``
        if the proof is invalid.

    Raises
    ------
    NotImplementedError
        If the native VRF extension is not available.
    ValueError
        If ``pk`` or ``proof`` have incorrect sizes.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF verification requires the _vrf_native extension. "
            "Build with CMake to enable native VRF support."
        )

    if len(pk) != VRF_PK_SIZE:
        msg = f"VRF public key must be {VRF_PK_SIZE} bytes, got {len(pk)}"
        raise ValueError(msg)
    if len(proof) != VRF_PROOF_SIZE:
        msg = f"VRF proof must be {VRF_PROOF_SIZE} bytes, got {len(proof)}"
        raise ValueError(msg)

    try:
        return _native_verify(pk, proof, alpha)
    except RuntimeError:
        # Verification failed — invalid proof. Return None per our API.
        return None


def vrf_proof_to_hash(proof: bytes) -> bytes:
    """Extract the 64-byte VRF output from a proof without verification.

    This converts a valid VRF proof into its corresponding output hash.
    It does NOT verify the proof — the caller must ensure the proof has
    already been verified via ``vrf_verify``.

    Parameters
    ----------
    proof:
        VRF proof (80 bytes).

    Returns
    -------
    bytes
        The 64-byte VRF output hash.

    Raises
    ------
    NotImplementedError
        If the native VRF extension is not available.
    ValueError
        If ``proof`` has incorrect size or conversion fails.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF proof_to_hash requires the _vrf_native extension. "
            "Build with CMake to enable native VRF support."
        )

    if len(proof) != VRF_PROOF_SIZE:
        msg = f"VRF proof must be {VRF_PROOF_SIZE} bytes, got {len(proof)}"
        raise ValueError(msg)

    return _native_proof_to_hash(proof)


# ---------------------------------------------------------------------------
# Praos leader election math (pure Python — no native dependency)
# ---------------------------------------------------------------------------


def certified_nat_max_check(
    vrf_output: bytes,
    sigma: float,
    f: float,
) -> bool:
    """Check whether a VRF output wins the Praos leader lottery.

    The Ouroboros Praos leader check determines if a stake pool is
    elected to produce a block in a given slot. The check is:

        natural_number(vrf_output) / 2^512 < 1 - (1 - f)^sigma

    where:
        - ``vrf_output`` is the 64-byte VRF output (interpreted as a
          big-endian 512-bit unsigned integer)
        - ``sigma`` is the pool's relative stake (proportion of total
          active stake, in [0.0, 1.0])
        - ``f`` is the active slot coefficient (fraction of slots that
          should have blocks, typically 0.05 on mainnet)

    We use ``decimal.Decimal`` with 40 digits of precision for the
    threshold calculation to avoid floating-point rounding errors that
    could cause leader schedule disagreements with the Haskell node.

    Spec reference:
        Ouroboros Praos, Section 4, Definition 6 (slot leader election)
        Shelley formal spec, Section 16.1, Figure 62

    Haskell reference:
        Cardano.Protocol.TPraos.Rules.Overlay.checkVRFValue

    Parameters
    ----------
    vrf_output:
        The 64-byte VRF output hash.
    sigma:
        Relative stake of the pool (0.0 to 1.0 inclusive).
    f:
        Active slot coefficient (0.0 to 1.0 exclusive).

    Returns
    -------
    bool
        True if the pool is elected as slot leader, False otherwise.

    Raises
    ------
    ValueError
        If ``vrf_output`` is not 64 bytes, or ``sigma``/``f`` are
        out of range.
    """
    if len(vrf_output) != VRF_OUTPUT_SIZE:
        msg = (
            f"VRF output must be {VRF_OUTPUT_SIZE} bytes, "
            f"got {len(vrf_output)}"
        )
        raise ValueError(msg)

    if not (0.0 <= sigma <= 1.0):
        msg = f"sigma must be in [0.0, 1.0], got {sigma}"
        raise ValueError(msg)

    if not (0.0 < f < 1.0):
        msg = f"f must be in (0.0, 1.0), got {f}"
        raise ValueError(msg)

    # Edge cases: sigma=0 => never elected, sigma=1 => always elected
    # (when f > 0, which we've already validated).
    if sigma == 0.0:
        return False

    # Interpret the VRF output as a big-endian unsigned 512-bit integer.
    vrf_nat = int.from_bytes(vrf_output, byteorder="big")

    # Compute threshold q = 1 - (1 - f)^sigma using Decimal for precision.
    # We need enough precision to avoid disagreements with the Haskell node,
    # which uses rational arithmetic. 40 digits is more than sufficient for
    # the 512-bit comparison.
    ctx = getcontext()
    old_prec = ctx.prec
    try:
        ctx.prec = 40

        d_sigma = Decimal(str(sigma))
        d_f = Decimal(str(f))

        # q = 1 - (1 - f)^sigma
        # For sigma=1.0 this simplifies to q = f, which is always > 0.
        one = Decimal(1)
        complement = one - d_f  # (1 - f)
        # (1 - f)^sigma using ln/exp for non-integer exponents.
        # Decimal doesn't have a native power-with-float, so we use
        # the identity: x^y = exp(y * ln(x))
        if d_sigma == one:
            threshold = d_f
        elif d_sigma == Decimal(0):
            # Already handled above, but be defensive.
            return False
        else:
            # Use Python's float pow for the exponentiation, then convert
            # back to Decimal. The Haskell node uses a Taylor expansion
            # (approx via rational arithmetic). Our approach:
            # compute (1-f)^sigma as a high-precision Decimal.
            #
            # For the comparison to work correctly, we need the threshold
            # as a fraction of 2^512. We compute:
            #   threshold_nat = floor(q * 2^512)
            # and compare vrf_nat < threshold_nat.
            #
            # Using Decimal for the full computation:
            # ln(1-f) * sigma, then exp
            ln_complement = complement.ln()
            power = (ln_complement * d_sigma).exp()
            threshold = one - power

        # Convert to the integer domain: is vrf_nat / 2^512 < threshold?
        # Equivalently: vrf_nat < threshold * 2^512
        # We use integer multiplication to avoid any floating point.
        threshold_nat = int(threshold * Decimal(_2_POW_512))

        return vrf_nat < threshold_nat

    finally:
        ctx.prec = old_prec
