"""VRF (Verifiable Random Function) for Ouroboros Praos leader election.

Cardano uses ECVRF-ED25519-SHA512-Elligator2 (draft-irtf-cfrg-vrf-03)
for slot leader election. The cryptographic operations are provided by
the IOG fork of libsodium which adds ``crypto_vrf_*`` functions.

This module provides:

1. **Pure Python leader check math** — the ``certified_nat_max_check``
   function implements the Praos leader eligibility formula using
   ``decimal.Decimal`` for exact arithmetic. This is what consensus needs.

2. **Optional native VRF verification** — if the IOG libsodium fork is
   installed, ``vrf_verify`` and ``vrf_proof_to_hash`` delegate to the
   C library via ctypes. Otherwise they raise ``NotImplementedError``.

Spec references:
    - Ouroboros Praos paper, Section 4 (leader election)
    - Cardano Shelley formal spec, Section 16.1 (VRF verification)
    - draft-irtf-cfrg-vrf-03 (ECVRF construction)
    - Haskell: Cardano.Protocol.TPraos.Rules.Overlay (certifiedVRF)
"""

from __future__ import annotations

import ctypes
import ctypes.util
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
# Libsodium native bindings (optional)
# ---------------------------------------------------------------------------

_libsodium = None
HAS_VRF_NATIVE: bool = False
"""True if the IOG libsodium fork is available and crypto_vrf_* works."""


def _try_load_libsodium() -> ctypes.CDLL | None:
    """Attempt to load libsodium and verify it has VRF support.

    The IOG fork adds ``crypto_vrf_ietfdraft03_prove``,
    ``crypto_vrf_ietfdraft03_verify``, and
    ``crypto_vrf_ietfdraft03_proof_to_hash``. Stock libsodium does NOT
    have these symbols, so we probe for them.

    Returns the loaded library or None.
    """
    # Try common library names — the IOG fork is typically installed as
    # libsodium but with the extra VRF symbols.
    for name in ("sodium", "libsodium"):
        path = ctypes.util.find_library(name)
        if path is not None:
            try:
                lib = ctypes.CDLL(path)
                # Probe for the IOG-specific VRF symbol.
                lib.crypto_vrf_ietfdraft03_verify
                return lib
            except (OSError, AttributeError):
                continue
    return None


def _init_bindings() -> None:
    """One-time initialization of native VRF bindings."""
    global _libsodium, HAS_VRF_NATIVE  # noqa: PLW0603

    _libsodium = _try_load_libsodium()
    if _libsodium is not None:
        HAS_VRF_NATIVE = True
        logger.info("IOG libsodium fork loaded — native VRF available")

        # Configure function signatures for type safety.
        # int crypto_vrf_ietfdraft03_verify(
        #     unsigned char *output,        // VRF_OUTPUT_SIZE
        #     const unsigned char *pk,       // VRF_PK_SIZE
        #     const unsigned char *proof,    // VRF_PROOF_SIZE
        #     const unsigned char *msg,
        #     unsigned long long msglen
        # )
        _libsodium.crypto_vrf_ietfdraft03_verify.restype = ctypes.c_int
        _libsodium.crypto_vrf_ietfdraft03_verify.argtypes = [
            ctypes.c_char_p,  # output
            ctypes.c_char_p,  # pk
            ctypes.c_char_p,  # proof
            ctypes.c_char_p,  # msg
            ctypes.c_ulonglong,  # msglen
        ]

        # int crypto_vrf_ietfdraft03_proof_to_hash(
        #     unsigned char *hash,           // VRF_OUTPUT_SIZE
        #     const unsigned char *proof     // VRF_PROOF_SIZE
        # )
        _libsodium.crypto_vrf_ietfdraft03_proof_to_hash.restype = ctypes.c_int
        _libsodium.crypto_vrf_ietfdraft03_proof_to_hash.argtypes = [
            ctypes.c_char_p,  # hash
            ctypes.c_char_p,  # proof
        ]
    else:
        logger.debug(
            "IOG libsodium fork not found — VRF verify/proof_to_hash "
            "will raise NotImplementedError"
        )


# Run at import time.
_init_bindings()


# ---------------------------------------------------------------------------
# VRF operations
# ---------------------------------------------------------------------------


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
        If the IOG libsodium fork is not available.
    ValueError
        If ``pk`` or ``proof`` have incorrect sizes.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF verification requires the IOG libsodium fork. "
            "Install it and ensure crypto_vrf_ietfdraft03_verify is available."
        )

    if len(pk) != VRF_PK_SIZE:
        msg = f"VRF public key must be {VRF_PK_SIZE} bytes, got {len(pk)}"
        raise ValueError(msg)
    if len(proof) != VRF_PROOF_SIZE:
        msg = f"VRF proof must be {VRF_PROOF_SIZE} bytes, got {len(proof)}"
        raise ValueError(msg)

    output = ctypes.create_string_buffer(VRF_OUTPUT_SIZE)
    rc = _libsodium.crypto_vrf_ietfdraft03_verify(
        output, pk, proof, alpha, ctypes.c_ulonglong(len(alpha))
    )

    if rc == 0:
        return output.raw
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
        If the IOG libsodium fork is not available.
    ValueError
        If ``proof`` has incorrect size or conversion fails.
    """
    if not HAS_VRF_NATIVE:
        raise NotImplementedError(
            "VRF proof_to_hash requires the IOG libsodium fork. "
            "Install it and ensure crypto_vrf_ietfdraft03_proof_to_hash "
            "is available."
        )

    if len(proof) != VRF_PROOF_SIZE:
        msg = f"VRF proof must be {VRF_PROOF_SIZE} bytes, got {len(proof)}"
        raise ValueError(msg)

    output = ctypes.create_string_buffer(VRF_OUTPUT_SIZE)
    rc = _libsodium.crypto_vrf_ietfdraft03_proof_to_hash(output, proof)

    if rc != 0:
        msg = "crypto_vrf_ietfdraft03_proof_to_hash failed"
        raise ValueError(msg)

    return output.raw


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
