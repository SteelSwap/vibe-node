# Test Parity Matrix — Phase 6 M6.4

**Date:** 2026-03-22
**Total new tests added:** 539

## Per-Subsystem Coverage

| Subsystem | Before M6.4 | New Tests | After M6.4 | Haskell Parity Areas |
|-----------|-------------|-----------|------------|---------------------|
| **Serialization** | ~200 | 152 | ~352 | All-era CBOR round-trip, era detection, tx body fields, boundary values, malformed rejection |
| **Networking** | ~800 | 111 | ~911 | FSM states, codec round-trips, wrong-state rejection, terminal invariants, Hypothesis property tests |
| **Ledger** | ~600 | 104 | ~704 | UTxO rules, fee validation, strict cert processing, multi-asset, timelocks, Conway governance |
| **Storage** | 12 | 31 | 43 | ImmutableDB append/retrieve, VolatileDB GC, ChainDB chain selection, LedgerDB snapshot/restore |
| **Consensus + Crypto** | ~494 | 41 | ~535 | Chain selection properties, Praos leader threshold, epoch nonce evolution, VRF determinism, KES evolution |
| **Mempool** | 40 | 26 | 66 | Capacity edge cases, eviction, re-validation, tx ordering, snapshot isolation |
| **Forge** | 31 | 26 | 57 | Header encoding per CDDL, body size, VRF result, KES signature, prev_hash chaining |
| **Plutus** | ~130 | 28 | ~158 | Cost model param counts, builtin version enforcement, PlutusData CBOR round-trip, ExUnits |
| **Node** | 112 | 20 | 132 | Config validation, epoch boundary, KES period, SlotClock, wall-clock roundtrip |
| **Property** | 275 | — | 275 | (Covered by Hypothesis tests in other subsystems) |
| **Conformance** | ~80 | — | ~80+ | UPLC conformance cap removed (100→all), string-04 fixed |

## Summary

| Metric | Value |
|--------|-------|
| **New tests written** | 539 |
| **Previous total** | ~3,814 |
| **New total** | ~4,353 |
| **Subsystems covered** | 9 of 10 |
| **Weakest before** | Storage (12 tests) |
| **Weakest after** | Storage (43 tests — 3.6x improvement) |

## Remaining Gaps (Phase 7)

- **Storage:** Still the weakest subsystem. Need more ImmutableDB chunk rotation tests, VolatileDB concurrent access, ChainDB fork switch under load.
- **Conformance:** UPLC conformance cap removed but full 999-case run needs CI verification.
- **Property tests:** Could add more Hypothesis tests for network protocol message round-trips.
- **Integration:** No new integration tests added — requires Docker Compose infrastructure.

## Methodology

Each subsystem was compared against the Haskell test function inventory from the knowledge base (`code_tag_manifest` table, filtered by `prop_*`, `test_*`, `unit_*` prefixes). Tests were prioritized by:
1. Critical/important gaps in the existing coverage
2. Code paths affecting block production, validation, and chain selection
3. Tests for deprecated features and Haskell-internal plumbing were out of scope
