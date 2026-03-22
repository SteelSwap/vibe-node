# Test Inventory — Phase 6 M6.4

**Date:** 2026-03-22
**Total:** ~3,814 test functions across 132 files

## Per-Subsystem Summary

| Subsystem | Directory | Files | Functions | Coverage Notes |
|-----------|-----------|-------|-----------|---------------|
| **Network/Protocol** | tests/network/ + tests/unit/test_*sync*/mux/handshake | 19+partial | ~800+ | Strongest — all miniprotocols |
| **Consensus** | tests/consensus/ | 10 | 364 | Strong — Praos, HFC, nonce, rewards |
| **Ledger/Era Rules** | tests/ledger/ + tests/unit/test_*ledger*/byron/shelley/alonzo/babbage/conway | 1+~20 | ~600+ | Strong — all eras |
| **Crypto** | tests/crypto/ | 5 | ~130 | Good — KES, VRF, opcert |
| **Plutus** | tests/plutus/ + tests/conformance/ | 4+6 | ~210 | Good — CEK, cost models, conformance |
| **Node Integration** | tests/node/ | 10 | 112 | Good — lifecycle, epoch, KES, params |
| **Mempool** | tests/mempool/ | 3 | 40 | Moderate |
| **Forge** | tests/forge/ | 2 | 31 | Moderate |
| **Storage** | tests/storage/ | 3 | **12** | **Weakest — priority for parity** |
| **Property-based** | tests/property/ | 11 | 275 | Good — Hypothesis roundtrips |

## Priority for Haskell Test Parity

1. **Storage (12 tests)** — Only covers trace events, regression #773, and volatile max blocks. Missing: ImmutableDB chunk/index tests, ChainDB chain selection tests, LedgerDB snapshot/restore tests, crash recovery tests.
2. **Forge (31 tests)** — Missing: header format edge cases, body size limit tests, VRF result encoding variants.
3. **Mempool (40 tests)** — Missing: eviction policy tests, concurrent access tests, re-validation on rollback.
4. **Storage + Ledger** — Need cross-subsystem tests for ledger state application during sync.

## Knowledge Base Infrastructure

- `code_tag_manifest` table has Haskell functions indexed per release tag
- Filter by `function_name LIKE 'prop_%' OR function_name LIKE 'test_%' OR function_name LIKE 'unit_%'` to get Haskell test functions
- `test_specifications` table ready for parity matrix entries
- `cross_references` table links tests to spec sections
