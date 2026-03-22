# UPLC Gap Report: Python (uplc) vs Haskell (plutus)

**Date:** 2026-03-22
**uplc version:** 1.3.2 (theeldermillenial/uplc fork)
**Scope:** All behavioral differences between uplc Python and Haskell plutus

## Critical (Consensus Divergence)

### 1. V3 flat decoder: trailing bytes not rejected
PlutusV3 requires strict rejection of trailing bytes after flat-encoded programs. uplc's `unflatten()` doesn't check for remaining data. V1/V2 are lenient (correct), but V3 must reject.
- **Component:** uplc `flat_decoder.py:finalize()` + our `evaluate.py` wrapper
- **Fix:** After `read_program()`, verify no non-padding bits remain for V3

### 2. On-chain cost model parameters not wired in
`evaluate_script()` uses hardcoded default cost models from static JSON files instead of on-chain protocol parameters. Budget calculations will diverge from Haskell.
- **Component:** Our `evaluate.py` wrapper (lines 99-101, 404-406)
- **Fix:** Wire `cost_model` parameter through to `updated_builtin_cost_model_from_network_config()`

## High (Script Failures)

### 3. Duplicate map keys silently lost
`PlutusMap` uses `frozendict` which deduplicates keys. Haskell `Data` preserves duplicate keys. Scripts relying on duplicate map keys will behave differently.
- **Component:** uplc `ast.py:PlutusMap` + `data_from_cbortag`
- **Fix:** Replace frozendict with ordered list of pairs (upstream issue #35)

### 4. SECP256k1 missing length checks
`verify_ecdsa_secp256k1` and `verify_schnorr_secp256k1` have `# TODO length checks`. Haskell validates pubkey (33/32 bytes), signature (64 bytes), message (32 bytes) sizes.
- **Component:** uplc `ast.py:991-1019`
- **Fix:** Add explicit size validation before crypto calls

### 5. BLS12-381 is optional dependency
All 17 BLS builtins implemented but `pyblst` is optional. Missing pyblst means V3 scripts using BLS fail at runtime instead of at validation.
- **Component:** uplc `ast.py:37-60`
- **Fix:** Make pyblst a hard dependency for vibe-node

### 6. Builtin version enforcement missing
uplc doesn't enforce which builtins are available per Plutus version. A V1 script could use V2+ builtins (SerialiseData) or V3+ builtins (BLS) without error.
- **Component:** uplc `plutus_version_enforcer.py` (only checks Constr/Case terms)
- **Fix:** Scan AST for BuiltIn nodes, reject if builtin not in version's allowed set

### 7. Zero-cost builtins for unknown entries
`machine.py:28-29` returns `Budget(0, 0)` for builtins not in the cost model. New V3 builtins missing from the base model get free evaluation.
- **Component:** uplc `machine.py`, `cost_model.py`
- **Fix:** Raise error for unknown builtins instead of returning zero cost

### 8. V3 ScriptPurpose constructor tags
Conway V3 adds Voting (4) and Proposing (5) to ScriptPurpose and may reorder existing constructors. Our `context.py` only handles V1/V2 tags.
- **Component:** Our `context.py`
- **Fix:** Implement V3-specific ScriptPurpose constructors

## Medium

### 9. Budget exhaustion: fragile string matching
`evaluate.py:436` checks `"Exhausted budget"` string. If uplc changes the message, detection breaks.
- **Fix:** Check `result.cost` directly against budget limits

### 10. Only 100/999 conformance tests run
`test_uplc_conformance.py:118` caps at 100 cases. We test ~10% of the Haskell conformance suite.
- **Fix:** Remove cap, use pytest markers for CI speed

### 11. Bitwise builtins (CIP-0122) untested against full conformance
All 13 bitwise builtins implemented but conformance coverage unknown due to the 100-case cap.
- **Fix:** Run full suite, verify bitwise-specific cases pass

### 12. eval() defaults to V3 cost model
`tools.py:98-99` defaults to V3 regardless of script version. Our conformance tests inherit this.
- **Fix:** Version-aware cost model selection in test runner

### 13. RIPEMD-160 API correctness
`ast.py:1325` may use wrong PyCryptodome API (`RIPEMD160Hash` vs `RIPEMD160.new()`).
- **Fix:** Verify against known test vectors

## Low

### 14. load_network_config file extension bug
`cost_model.py:601` checks `file.suffix == "json"` but `Path.suffix` returns `".json"`. Works by accident (single file per directory).
- **Fix:** Change to `file.suffix == ".json"`

## Fixed This Session

### String escape sequences (was CRITICAL)
`\DDD` (decimal) and `\oOOO` (octal) escapes now handled by custom `_decode_haskell_string()`. string-04 conformance test passes.

## Summary

| Severity | Count | Consensus Impact |
|----------|-------|-----------------|
| CRITICAL | 2 | Budget divergence, V3 validation divergence |
| HIGH | 6 | Script failures, incorrect evaluation |
| MEDIUM | 5 | Test coverage gaps, fragile code |
| LOW | 1 | Masked bug |
| FIXED | 1 | String escapes |
