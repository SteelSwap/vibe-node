"""vibe.cardano.crypto — Cryptographic primitives for Cardano consensus.

This package provides:

* **VRF** (Verifiable Random Function) — ECVRF-ED25519-SHA512-Elligator2
  for leader election via IOG libsodium fork.
* **KES** (Key-Evolving Signatures) — Sum-composition over Ed25519,
  providing forward security for block signing keys.
* **OCert** (Operational Certificates) — Cold-to-hot key delegation
  with KES period bounds and replay-preventing counters.
"""

from vibe.cardano.crypto.vrf import (
    HAS_VRF_NATIVE,
    VRF_OUTPUT_SIZE,
    VRF_PK_SIZE,
    VRF_PROOF_SIZE,
    VRF_SK_SIZE,
    certified_nat_max_check,
    vrf_keypair,
    vrf_proof_to_hash,
    vrf_prove,
    vrf_verify,
)

from .kes import (
    CARDANO_KES_DEPTH,
    ED25519_SIG_SIZE,
    ED25519_VK_SIZE,
    HASH_SIZE,
    MAX_KES_EVOLUTIONS,
    KesSecretKey,
    kes_derive_vk,
    kes_keygen,
    kes_sig_size,
    kes_sign,
    kes_update,
    kes_verify,
    kes_verify_block_signature,
    kes_vk_hash,
)
from .ocert import (
    MAX_KES_EVOLUTIONS as OCERT_MAX_KES_EVO,
    SLOTS_PER_KES_PERIOD,
    OCertError,
    OCertFailure,
    OperationalCert,
    ocert_signed_payload,
    slot_to_kes_period,
    validate_ocert,
    verify_ocert_cold_sig,
)

__all__ = [
    # VRF
    "HAS_VRF_NATIVE",
    "VRF_OUTPUT_SIZE",
    "VRF_PK_SIZE",
    "VRF_PROOF_SIZE",
    "VRF_SK_SIZE",
    "certified_nat_max_check",
    "vrf_keypair",
    "vrf_proof_to_hash",
    "vrf_prove",
    "vrf_verify",
    # KES
    "CARDANO_KES_DEPTH",
    "ED25519_SIG_SIZE",
    "ED25519_VK_SIZE",
    "HASH_SIZE",
    "MAX_KES_EVOLUTIONS",
    "KesSecretKey",
    "kes_derive_vk",
    "kes_keygen",
    "kes_sig_size",
    "kes_sign",
    "kes_update",
    "kes_verify",
    "kes_verify_block_signature",
    "kes_vk_hash",
    # OCert
    "SLOTS_PER_KES_PERIOD",
    "OCertError",
    "OCertFailure",
    "OperationalCert",
    "ocert_signed_payload",
    "slot_to_kes_period",
    "validate_ocert",
    "verify_ocert_cold_sig",
]
