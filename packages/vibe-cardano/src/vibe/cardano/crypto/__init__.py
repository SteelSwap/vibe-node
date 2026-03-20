"""vibe.cardano.crypto — Cryptographic primitives for Cardano consensus.

This package provides VRF (Verifiable Random Function) verification,
KES (Key Evolving Signature) verification, and related cryptographic
operations required by Ouroboros Praos.

The VRF implementation uses ECVRF-ED25519-SHA512-Elligator2
(draft-irtf-cfrg-vrf-03) as specified by Cardano's use of the IOG
libsodium fork.
"""

from vibe.cardano.crypto.vrf import (
    HAS_VRF_NATIVE,
    VRF_OUTPUT_SIZE,
    VRF_PK_SIZE,
    VRF_PROOF_SIZE,
    VRF_SK_SIZE,
    certified_nat_max_check,
    vrf_proof_to_hash,
    vrf_verify,
)

__all__ = [
    "HAS_VRF_NATIVE",
    "VRF_OUTPUT_SIZE",
    "VRF_PK_SIZE",
    "VRF_PROOF_SIZE",
    "VRF_SK_SIZE",
    "certified_nat_max_check",
    "vrf_proof_to_hash",
    "vrf_verify",
]
