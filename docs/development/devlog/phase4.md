# Phase 4 — Ledger & Consensus

**Date:** 2026-03-20 — ongoing
**Status:** In Progress
**Version:** v0.4.0 (planned)

**vibe-node validates the chain.** Phase 4 builds full ledger validation (Alonzo through Conway), Ouroboros Praos consensus with VRF/KES, Plutus script evaluation via uplc, and the remaining N2N miniprotocols. The gate test: 3-node private devnet with tip agreement within 2160 slots for 24 continuous hours, zero divergence on block/transaction validity.

---

## Wave 1 — Foundations (6 parallel modules)

### M4.1 — VRF (libsodium FFI)

VRF verification via pybind11 wrapping the vendored IOG libsodium fork. ECVRF-ED25519-SHA512-Elligator2 — the same VRF construction used by Cardano for leader election.

- **pybind11 C extension** (`_vrf_native.cpp`) wrapping `crypto_vrf_ietfdraft03_*` functions
- **CMake build** compiles libsodium from vendored source as static library
- **Python API:** `vrf_keypair()`, `vrf_prove(sk, alpha)`, `vrf_verify(pk, proof, alpha)`, `vrf_proof_to_hash(proof)`
- **Leader check:** `certified_nat_max_check(vrf_output, sigma, f)` — pure Python with 40-digit `Decimal` precision for threshold `1 - (1-f)^σ`
- `HAS_VRF_NATIVE` flag with graceful fallback for environments without the C extension
- **Key finding:** σ=1.0 doesn't mean "always elected" — it means elected with probability f (~5%) per slot, the maximum possible rate

**Tests:** 48 (33 original + 14 end-to-end native + 4 skipped without native)

---

### M4.2 — KES (Key-Evolving Signatures)

Sum-composition KES over Ed25519 using the `cryptography` library. Binary tree of key pairs providing forward security for block signing.

- **Sum-composition binary tree** per the MMM paper (Section 3.1), depth-configurable
- Cardano mainnet: depth 6 → 2^6 = 64 KES periods per key
- **Signature format:** `child_sig || left_vk || right_vk` at each level (448 bytes for depth 6)
- `kes_sign()`, `kes_verify()`, `kes_update()` — key evolution erases used leaves
- **Operational certificates:** all 6 OCERT predicate failures from Shelley formal spec Figure 16:
  KESBeforeStart, KESAfterEnd, CounterTooSmall, InvalidSignature, InvalidKesSignature, NoCounterForKeyHash
- `slot_to_kes_period()` for slot-to-period conversion

**Tests:** 64 (41 KES + 23 OCert), including Hypothesis property tests

---

### M4.3 — Alonzo Ledger

Alonzo-era UTxO transition rules building on Phase 3's Shelley-Mary:

- **UTXO rules:** CollateralContainsNonADA, InsufficientCollateral, TooManyCollateralInputs, ExUnitsTooBigUTxO, ScriptIntegrityHashMismatch, OutsideForecast
- **UTXOW rules:** script witness validation, redeemer pointer resolution, required signers
- **Two-phase validation:** collateral rules only apply when `has_plutus_scripts=True`
- **Types:** ExUnits (component-wise arithmetic), Redeemer, RedeemerTag, ScriptPurpose, Language, CostModel, ExUnitPrices, AlonzoProtocolParams
- `compute_script_integrity_hash()` — Blake2b-256 of redeemers + datums + language views
- `alonzo_min_utxo_value()` using coinsPerUTxOWord

**Tests:** 101 (52 types + 49 rules), including Hypothesis property tests

---

### M4.4 — Plutus Integration

Bridge to uplc CEK machine for Plutus script evaluation:

- **Script evaluation:** `evaluate_script()` — deserialize, apply args, run CEK, enforce budget
- **ScriptContext construction:** `TxInfoBuilder` with `build_v1()` (10 fields), `build_v2()` (12 fields), `build_v3()` (16 fields including governance)
- **Data conversion:** pycardano types → uplc AST (constr, map, list, int, bytestring)
- **Cost models:** CostModel with parameter count enforcement (V1:166, V2:175, V3:233)
- `hash_script_integrity()` for scriptDataHash computation
- **VNODE-151 documented:** uplc issue #35 — `frozendict` silently deduplicates PlutusMap keys. Haskell preserves duplicates. 3 tests document the divergence.
- uplc 1.3.2 installed cleanly on Python 3.14

**Tests:** 84 (34 evaluate + 25 context + 25 cost model)

---

### M4.5 — Tx-Submission Protocol

N2N tx-submission miniprotocol (protocol ID 4):

- **6 message types:** MsgInit, MsgRequestTxIds, MsgReplyTxIds, MsgRequestTxs, MsgReplyTxs, MsgDone
- **Wire format** verified against Haskell `TxSubmission2` encoding in `ouroboros-network-0.22.6.0`
- **5-state FSM:** StInit → StIdle → StTxIds/StTxs → StDone
- **Pull-based:** server drives by requesting tx IDs and full transactions
- `TxSubmissionClient` with async API and `run_tx_submission_client()` loop

**Tests:** 87 (46 codec + 41 protocol), including Hypothesis CBOR round-trip

---

### M4.6 — Keep-Alive Protocol

N2N keep-alive miniprotocol (protocol ID 8):

- **Messages:** MsgKeepAlive(cookie), MsgKeepAliveResponse(cookie), MsgDone
- **3-state FSM:** StClient → StServer → StDone
- Cookie validation enforcing uint16 range (0..65535)
- `run_keep_alive_client()` with configurable interval (default 90s)

**Tests:** 81 (48 codec + 33 protocol), including Hypothesis property tests

---

### Wave 1 Test Summary

| Module | Unit | Property | Total |
|--------|------|----------|-------|
| M4.1 — VRF | 34 | 14 | 48 |
| M4.2 — KES/OCert | 48 | 16 | 64 |
| M4.3 — Alonzo Ledger | 87 | 14 | 101 |
| M4.4 — Plutus | 72 | 12 | 84 |
| M4.5 — Tx-Submission | 63 | 24 | 87 |
| M4.6 — Keep-Alive | 57 | 24 | 81 |
| **Wave 1 Total** | **361** | **104** | **465** |

Combined with Phase 2-3 tests: **1,617 total tests passing** (20 skipped).

---

## Wave 2 — Consensus & Full Ledger (depends on Wave 1)

### M4.7 — Babbage-Conway Ledger

*Planned — depends on M4.3 Alonzo + M4.4 Plutus*

### M4.8 — Ouroboros Praos

*Planned — depends on M4.1 VRF + M4.2 KES*

### M4.9 — Epoch Boundary

*Planned — depends on M4.8 Praos*

---

## Wave 3 — Integration (depends on Wave 2)

### M4.10 — Hard Fork Combinator

*Planned — depends on all ledger eras + consensus*

### M4.11 — Conformance Suite

*Planned — depends on all ledger + consensus modules*

### M4.12 — Devnet Integration

*Planned — depends on all Phase 4 modules*

---

## Issues Encountered & Fixed

| Issue | Fix |
|-------|-----|
| M4.1 agent used ctypes stub instead of pybind11 | Built proper pybind11 + vendored IOG libsodium in follow-up commit |
| M4.1 tests assumed σ=1.0 means "always elected" | Fixed: σ=1.0 gives probability f per slot (~5% on mainnet), not guaranteed |
| M4.2 crypto/__init__.py merge conflict with M4.1 | Both agents created the file — merged VRF + KES exports |
| M4.5/M4.6 branches not auto-pushed by agents | Pushed from worktrees manually |
| uplc frozendict deduplicates PlutusMap keys (VNODE-151) | Documented divergence with 3 tests; upstream fix needed |
