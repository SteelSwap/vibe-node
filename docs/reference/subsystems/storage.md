# Storage

## Overview
Persistent chain state management. The largest module namespace in the consensus layer (540 functions). ImmutableDB for finalized blocks, VolatileDB for recent forks, LedgerDB for state snapshots, ChainDB as coordinator.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| ouroboros-consensus storage docs | See [specs index](../../specs/index.md) |

## Haskell Package Structure
`Ouroboros.Consensus.Storage` (540 functions) — the largest module namespace in ouroboros-consensus.

## Module Decomposition
- ImmutableDB — append-only finalized blocks
- VolatileDB — recent blocks on competing forks
- LedgerDB — ledger state snapshots for rollback support
- ChainDB — coordinates all databases + chain selection
- Iterator API — for serving chain-sync to downstream peers

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 3
