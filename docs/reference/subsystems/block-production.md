# Block Production / Forge

## Overview
Block assembly when the node is elected slot leader. Constructs the block header with VRF proof and assembles the body from mempool transactions.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| Consensus + ledger specs combined | See [specs index](../../specs/index.md) |

## Haskell Package Structure
Intersection of ouroboros-consensus (leader check, header creation) and cardano-ledger (block body construction, transaction selection).

## Module Decomposition
- Leader schedule check (VRF proof)
- Block header construction (KES signature)
- Block body assembly from mempool
- Transaction selection and ordering
- Era-specific block format

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 5
