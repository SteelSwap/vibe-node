# Dependency Audit — Phase 6 M6.1

**Date:** 2026-03-22
**Version:** v0.5.0
**Auditor:** Agent Millenial

## Summary

27 dependency workarounds found across the codebase. pycardano has the most (11), followed by cbor2pure (5), cross-dependency structural patterns (5), uplc (3), and cryptography/PyNaCl (3).

| Dependency | Workarounds | Severity | Primary Issue |
|-----------|-------------|----------|---------------|
| **pycardano** | 11 | High | Missing Block/Byron types; incomplete era coverage; dual-type architecture |
| **cbor2pure** | 5 | Medium | Semantic tag conflict workaround (now partially redundant); no indefinite-length list API |
| **Cross-dependency** | 5 | Medium | Block format variability; CBOR re-encoding roundtrips |
| **uplc** | 3 | Low | Missing cost model injection API; CBOR roundtrip for data conversion |
| **cryptography/PyNaCl** | 3 | Low | Overly broad exception catches around verification |

---

## cbor2pure Workarounds (5)

### 1.1 `_strip_tag()` manual CBOR tag parsing
- **File:** `serialization/block.py:52-86`
- **Issue:** cbor2 C extension interprets tags 0-5 as semantic types (datetime, bignum, etc.) before any `tag_hook`. Cardano uses tags 0-7 for era identification.
- **Workaround:** Manual byte-level tag parsing to extract era tag without full CBOR decode.
- **Removable:** Partially — we use cbor2pure which avoids C bindings, but the function is kept for performance (avoids full decode just for era detection).

### 1.2 Duplicated `_strip_tag()` in transaction.py
- **File:** `serialization/transaction.py:106-132`
- **Issue:** Same as 1.1, duplicated for standalone use.
- **Removable:** Yes — should be deduplicated into shared utility (M6.2 will handle).

### 1.3 `_loads()` wrapper and `_decode_tagged_block()`
- **File:** `serialization/block.py:87, 351-365`
- **Issue:** Strips tag first, then decodes payload separately to avoid semantic tag interpretation.
- **Removable:** Yes — with cbor2pure exclusive usage.

### 1.4 Definite-length list encoding for tx-submission
- **File:** `network/txsubmission.py:188-202`
- **Issue:** cbor2pure lacks indefinite-length list API. Haskell uses indefinite-length, but accepts both.
- **Removable:** Partially — works but technically non-conformant encoding.

### 1.5 `import cbor2pure as cbor2` alias pattern
- **File:** All 32+ production source files
- **Issue:** Permanent choice to avoid cbor2 C binding bugs.
- **Removable:** No — deliberate permanent pattern.
- **Note:** Test files still use bare `import cbor2` — acceptable since tests don't hit the C binding bug path.

---

## pycardano Workarounds (11)

### 2.1-2.4 Transaction deserialization fallbacks
- **Files:** `serialization/transaction.py:161-228`, `serialization/eval_pycardano.py:500-572`
- **Issue:** pycardano fails on Conway-specific fields (voting_procedures, proposal_procedures), some Alonzo witness types, Babbage output extensions.
- **Workaround:** `try/except` wrappers that fall back to raw CBOR dicts. Body type is `TransactionBody | dict`.
- **Removable:** Yes — if pycardano fork adds full Conway/Babbage support.

### 2.5-2.8 Dual-interface `getattr` defensive access
- **Files:** `ledger/delegation.py:80-88`, `ledger/shelley.py:502-503, 535-538`, `node/run.py:614-644`
- **Issue:** Code must handle both pycardano `TransactionBody`/`Address` objects and raw dicts/bytes.
- **Workaround:** Pervasive `getattr(obj, "field", None)`, `hasattr()` checks.
- **Removable:** Partially — could define a unified transaction interface Protocol type.

### 2.9 Auxiliary data architecture mismatch
- **File:** `ledger/alonzo.py:1045-1050`
- **Issue:** pycardano stores `auxiliary_data` on `Transaction`, not `TransactionWitnessSet`. Our validation receives witness set separately.
- **Removable:** No — architectural difference in pycardano.

### 2.10-2.11 Optional import + CBOR roundtrip conversion
- **Files:** `plutus/evaluate.py:217-234, 259-270`
- **Issue:** No direct pycardano-to-uplc PlutusData conversion. CBOR roundtrip used as bridge.
- **Removable:** Yes — if direct conversion API existed.

---

## uplc Workarounds (3)

### 3.1 Cost model parameters not wired
- **File:** `plutus/evaluate.py:99-100, 404-406`
- **Issue:** Uses uplc's hardcoded default cost models instead of on-chain protocol parameters.
- **Removable:** Yes — when uplc API supports parameter injection.

### 3.2 Double-CBOR unwrap with fallback
- **File:** `plutus/evaluate.py:146-156`
- **Issue:** On-chain scripts have varying CBOR wrapping levels. Code tries both.
- **Removable:** No — spec-compliant handling of on-chain format variability.

### 3.3 De Bruijn normalization for test comparison
- **File:** `tests/conformance/test_uplc_conformance.py:150-159`
- **Issue:** Variable naming differences between uplc Python and Plutus reference.
- **Removable:** No — standard lambda calculus comparison technique.

---

## cryptography / PyNaCl Workarounds (3)

### 4.1-4.2 Broad exception catches on Ed25519 verify
- **Files:** `crypto/kes.py:75-80`, `crypto/ocert.py:206-211`
- **Issue:** Catches `except Exception` instead of specific `InvalidSignature`.
- **Removable:** Yes — narrow to `except (InvalidSignature, ValueError, TypeError)`.

### 4.3 Broad exception catch on PyNaCl verify
- **File:** `ledger/shelley.py:394-399`
- **Issue:** Catches `except Exception` instead of `nacl.exceptions.BadSignatureError`.
- **Removable:** Yes — narrow to specific PyNaCl exceptions.

---

## Fork Action Plan

| Dependency | Fork? | Priority Fixes | Upstream PR? |
|-----------|-------|---------------|-------------|
| **cbor2pure** | Yes → SteelSwap/cbor2 | Indefinite-length list API; audit edge cases | Yes |
| **uplc** | Yes → SteelSwap/uplc | String-04 escape parsing; cost model parameter API | Yes |
| **pycardano** | Yes → SteelSwap/pycardano | Conway field support; type stub completion; Block types (stretch) | Yes |
| **cryptography** | No | Narrow exception catches (fix in our code, not upstream) | N/A |

## Fork Maintenance Strategy

- Pin packages to SteelSwap fork via pyproject.toml git references
- Track upstream releases — rebase patches on each upstream release
- If upstream merges our PRs, switch back to upstream and drop the fork
- Acceptable divergence window: 6 months before we escalate (write minimal replacement)
