# Mempool

## Overview
Transaction staging area. Validates incoming transactions against a cached ledger state, maintains ordering, and provides transactions for block production. Re-validates on chain switches.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| ouroboros-consensus mempool docs | See [specs index](../../specs/index.md) |

## Haskell Package Structure
Part of ouroboros-consensus. Key module: `Ouroboros.Consensus.Mempool`. Caches the ledger state resulting from applying all mempool transactions.

## Module Decomposition
- Transaction buffer with capacity management
- Validation against cached ledger state
- Transaction ordering and dependency tracking
- Re-validation on chain switch (rollback)
- Snapshot for block production

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 4
