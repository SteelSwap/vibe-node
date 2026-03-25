# Critical Gap Analysis — Per Subsystem

376 critical gaps where the Cardano formal spec and Haskell reference implementation diverge in consensus-affecting ways. Each gap documents what the spec says, what Haskell does differently, and whether our Python implementation addresses it.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

## Known Limitation: "No Implementing Code Found" False Negatives

**100 of 376 critical gaps** (27%) have `haskell_does` = "No implementing Haskell code was found." The Phase 1 pipeline used git-grep on vendor submodules to find implementations but missed code that:

- Lives in a different module than expected (e.g., forge sync gate is in `BlockchainTime` and `NodeKernel`, not where the spec rule would suggest)
- Uses indirect mechanisms (e.g., STM `retry` blocking rather than an explicit `if syncing then skip`)
- Is spread across multiple layers (e.g., the sync gate has 3 independent layers in 3 different files)

**Example:** The "block production must be disabled while syncing" gap was marked "no implementing code found" — but deep investigation revealed 3 layers: `CurrentSlotUnknown` (hard block via safe zone / `3k/f` horizon), `OutsideForecastRange` (ledger view unavailable), and GSM state machine (peer selection gating). All exist in the Haskell codebase.

**Impact:** For these 100 gaps, the `implications` field says "implement from spec since no Haskell reference" — but the Haskell reference likely exists. Each should be re-verified against the vendor code before implementing.

| Subsystem | "No code found" gaps |
|-----------|---------------------|
| Ledger | 30 |
| Networking | 17 |
| Consensus | 15 |
| Plutus | 14 |
| Block Production | 11 |
| Storage | 8 |
| Serialization | 4 |
| Mempool | 1 |
| **Total** | **100** |

## Summary

| Subsystem | Critical Gaps | File |
|-----------|-------------|------|
| [Ledger](ledger.md) | 104 | `gaps/ledger.md` |
| [Consensus](consensus.md) | 73 | `gaps/consensus.md` |
| [Networking](networking.md) | 67 | `gaps/networking.md` |
| [Plutus](plutus.md) | 34 | `gaps/plutus.md` |
| [Block Production](block_production.md) | 28 | `gaps/block_production.md` |
| [Storage](storage.md) | 28 | `gaps/storage.md` |
| [Serialization](serialization.md) | 26 | `gaps/serialization.md` |
| [Mempool](mempool.md) | 10 | `gaps/mempool.md` |
| [Miniprotocols N2N](miniprotocols_n2n.md) | 4 | `gaps/miniprotocols_n2n.md` |
| [Miniprotocols N2C](miniprotocols_n2c.md) | 2 | `gaps/miniprotocols_n2c.md` |
| **Total** | **376** | |

## Our Status (from M6.10 audit)

| Subsystem | MISSING | PARTIAL | ADDRESSED | WRONG | N/A |
|-----------|---------|---------|-----------|-------|-----|
| Ledger+Mempool | 68 | 34 | 6 | 0 | 6 |
| Consensus | 48 | 8 | 1 | 0 | 16 |
| Networking | 14 | 5 | 2 | 0 | 52 |
| Plutus | 17 | 8 | 9 | 0 | 0 |
| Storage | 17 | 7 | 0 | 1 | 3 |
| Serialization | 18 | 5 | 3 | 0 | 0 |
| **Total** | **182** | **67** | **21** | **1** | **77** |

## Status Definitions

- **ADDRESSED** — our code correctly follows Haskell's behavior for this divergence
- **PARTIAL** — we have some implementation but it's incomplete
- **MISSING** — we have no implementation matching Haskell's behavior
- **WRONG** — our implementation actively contradicts Haskell's behavior
- **N/A** — not applicable to our current scope (Genesis, Peras, Byron-specific)
- **TODO** — not yet verified against our code
