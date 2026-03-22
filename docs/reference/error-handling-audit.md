# Error Handling Audit — Phase 6 M6.5

**Date:** 2026-03-22
**Scope:** Production codebase

## Summary

30 findings. Zero bare `except:` (good). 4 critical silent swallowing in forge/sync paths.

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 4 | Silent swallowing or DEBUG-only in forge loop and sync pipeline |
| HIGH | 6 | Broad catches in critical paths with some logging |
| MEDIUM | 10 | Broad catches in non-critical/cleanup/tooling |
| LOW | 10 | Correctly handled (re-raise, error wrap, structured returns) |

## Critical Fixes Required

### 1. run.py:974 — Forge loop startup: silent `except Exception: pass`
ChainDB tip read fails silently → forge starts with `prev_header_hash=None`, `prev_block_number=0`. Forged block won't chain to actual tip.
**Fix:** Add `logger.warning("Failed to read chain tip: %s", exc)`

### 2. run.py:1034 — Forge loop per-slot: silent `except Exception: pass`
Per-slot ChainDB read fails silently → forges with stale prev_hash.
**Fix:** Add `logger.warning` and `continue` to skip the slot.

### 3. run.py:650 — Block-fetch: ledger apply at DEBUG only
UTxO delta application failure logged at DEBUG → ledger silently diverges.
**Fix:** Elevate to `logger.warning`

### 4. run.py:462 — Chain-sync: header parse at DEBUG only
Header parse failure logged at DEBUG → block silently dropped from chain.
**Fix:** Elevate to `logger.warning`

## High Priority

- run.py:703 — block-fetch continuous: elevate to `logger.warning` (sync pipeline terminates)
- run.py:1078 — forged block storage: elevate to `logger.error` (produced but not stored)
- chaindb.py:277 — block promotion: elevate to `logger.warning`
- delegation.py:135 — cert processing: elevate to `logger.warning`

## Acceptable (Keep As-Is)

- Handshake/disconnect cleanup with `pass` (lines 377, 769, 782)
- Task cancellation cleanup (lines 262, 776)
- Forge loop per-slot failure at ERROR (line 1103)
- Peer connection loop at ERROR (line 291)
- Crypto verify returning False (kes.py:79, ocert.py:210, shelley.py:398) — narrow exception types later
- pycardano fallbacks (transaction.py:175, 197, 222)
- Plutus eval failure (evaluate.py:418)
- Mempool callback (mempool.py:256)
