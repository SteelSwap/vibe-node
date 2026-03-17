# Cryptographic Details {#sec:crypto-details}

## Hashing

The hashing algorithm for all verification keys and multi-signature scripts is BLAKE2b-224. Explicitly, this is the payment and stake credentials (Figure [\[fig:defs:addresses\]](#fig:defs:addresses){reference-type="ref" reference="fig:defs:addresses"}), the genesis keys and their delegates (Figure [\[fig:ts-types:pp-update\]](#fig:ts-types:pp-update){reference-type="ref" reference="fig:ts-types:pp-update"}), stake pool verification keys (Figure [\[fig:delegation-transitions\]](#fig:delegation-transitions){reference-type="ref" reference="fig:delegation-transitions"}), and VRF verification keys (Figure [\[fig:delegation-defs\]](#fig:delegation-defs){reference-type="ref" reference="fig:delegation-defs"}).

Everywhere else we use BLAKE2b-256. In the CDDL specification in Appendix [\[sec:cddl\]](#sec:cddl){reference-type="ref" reference="sec:cddl"}, $\mathsf{hash28}$ refers to BLAKE2b-224 and and $\mathsf{hash32}$ refers to BLAKE2b-256. BLAKE2 is specified in RFC 7693 [@rfcBLAKE2].

## Addresses

The and functions from Figure [\[fig:crypto-defs-shelley\]](#fig:crypto-defs-shelley){reference-type="ref" reference="fig:crypto-defs-shelley"} use Ed25519. See [@rfcEdDSA].

## KES

The and functions from Figure [\[fig:kes-defs-shelley\]](#fig:kes-defs-shelley){reference-type="ref" reference="fig:kes-defs-shelley"} use the iterated sum construction from Section 3.1 of [@cryptoeprint:2001:034]. We allow up to $2^7$ key evolutions, which is larger than the maximum number of evolutions allow by the spec, , which will be set to $90$. See Figure [\[fig:rules:ocert\]](#fig:rules:ocert){reference-type="ref" reference="fig:rules:ocert"}.

## VRF

The function from Figure [\[fig:defs-vrf\]](#fig:defs-vrf){reference-type="ref" reference="fig:defs-vrf"} uses ECVRF-ED25519-SHA512-Elligator2 as described in the draft IETF specification [@rfcVRFDraft].
