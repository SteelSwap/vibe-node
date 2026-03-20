"""vibe.cardano.crypto — Cryptographic primitives for Cardano.

This package implements the cryptographic schemes required by Ouroboros Praos:

* **KES** (Key-Evolving Signatures) — Sum-composition over Ed25519,
  providing forward security for block signing keys.
* **OCert** (Operational Certificates) — Cold-to-hot key delegation
  with KES period bounds and replay-preventing counters.
"""

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
