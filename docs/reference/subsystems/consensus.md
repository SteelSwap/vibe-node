# Consensus / Ouroboros Praos

## Overview
Leader election via VRF, KES key evolution, tip selection, chain growth. The consensus layer ensures everyone agrees on the chain. Separates block *selection* (consensus) from block *contents* (ledger).

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| Ouroboros Praos/Genesis papers, ouroboros-consensus report | See [specs index](../../specs/index.md) |

## Haskell Package Structure
ouroboros-consensus (1,973 src functions), ouroboros-consensus-protocol (73 functions), ouroboros-consensus-cardano (852 functions). Key namespaces: `Ouroboros.Consensus.Protocol` (129), `Ouroboros.Consensus.HardFork` (369).

## Module Decomposition
- Protocol state machine (Praos, Genesis)
- Chain selection (SelectView, LedgerView)
- Leader check (VRF)
- KES key evolution
- Hard fork combinator (multi-era)
- Forecasting (ledger views for header validation)

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 4
