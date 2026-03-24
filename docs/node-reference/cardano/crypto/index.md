# Crypto

Cardano cryptographic primitives — VRF (Verifiable Random Function), KES (Key Evolving Signature), and operational certificates.

## Modules

### VRF

VRF prove/verify and Praos-specific value extraction (leader value, nonce value).

::: vibe.cardano.crypto.vrf
    options:
      show_source: false
      members_order: source

### KES

KES key generation, evolution, signing, and verification. Implements the sum-composition KES scheme at depth 6 (Cardano standard).

::: vibe.cardano.crypto.kes
    options:
      show_source: false
      members_order: source

### Operational Certificates

Operational certificate creation, validation, and the KES period mapping.

::: vibe.cardano.crypto.ocert
    options:
      show_source: false
      members_order: source
