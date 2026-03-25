# Critical Gap Analysis — Per Subsystem

376 critical gaps where the Cardano formal spec and Haskell reference implementation diverge in consensus-affecting ways. Each gap documents what the spec says, what Haskell does differently, and whether our Python implementation addresses it.

**Severity:** critical = must match Haskell behavior exactly (consensus-affecting)

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
