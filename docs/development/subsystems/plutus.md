# Plutus / Script Evaluation

## Overview
Plutus Core interpreter implementing the CEK abstract machine, cost models for resource accounting, and the bridge between ledger validation and script execution.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| plutus specs, cost model docs | See [specs index](../../specs/index.md) |

## Haskell Package Structure
plutus-core (1,084 functions), untyped-plutus-core (558), cost-model (302), plutus-ledger-api (179). Key namespace: `PlutusCore.Evaluation.Machine` (144 functions).

## Module Decomposition
- Plutus Core AST and parser
- CEK abstract machine
- Builtin functions and types
- Cost model evaluation
- Script validation bridge (plutus-ledger-api)
- FLAT serialization for on-chain scripts

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 5
