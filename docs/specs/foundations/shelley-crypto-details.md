# Cryptographic Details
## Hashing

The hashing algorithm for all verification keys and multi-signature scripts is BLAKE2b-224. Explicitly, this is the payment and stake credentials (Figure fig:defs:addresses), the genesis keys and their delegates (Figure fig:ts-types:pp-update), stake pool verification keys (Figure fig:delegation-transitions), and VRF verification keys (Figure fig:delegation-defs).

Everywhere else we use BLAKE2b-256. In the CDDL specification in Appendix sec:cddl, $\mathsf{hash28}$ refers to BLAKE2b-224 and and $\mathsf{hash32}$ refers to BLAKE2b-256. BLAKE2 is specified in RFC 7693 [@rfcBLAKE2].

## Addresses

The and functions from Figure fig:crypto-defs-shelley use Ed25519. See [@rfcEdDSA].

## KES

The and functions from Figure fig:kes-defs-shelley use the iterated sum construction from Section 3.1 of [@cryptoeprint:2001:034]. We allow up to $2^7$ key evolutions, which is larger than the maximum number of evolutions allow by the spec, , which will be set to $90$. See Figure fig:rules:ocert.

## VRF

The function from Figure fig:defs-vrf uses ECVRF-ED25519-SHA512-Elligator2 as described in the draft IETF specification [@rfcVRFDraft].
