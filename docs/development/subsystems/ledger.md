# Ledger Rules

## Overview
UTxO transition rules, delegation, governance, protocol parameters, epoch boundaries. Spans all eras from Byron through Conway. The ledger is *stateless* — a pure function from (state, block) → state.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| cardano-ledger formal specs per era, formal-ledger-specs (Agda) | See [specs index](../../specs/index.md) |

## Haskell Package Structure
cardano-ledger with eras/byron (1,679 functions), eras/shelley (1,463), eras/alonzo (486), eras/conway (126). libs/small-steps (83 — STS framework), libs/cardano-ledger-core (625). Key namespaces: `Shelley.Spec.Ledger`, `Cardano.Ledger`.

## Module Decomposition
- STS framework (small-steps)
- UTxO rules per era
- Delegation and stake pools
- Protocol parameter updates
- Epoch boundary processing (rewards)
- Governance (Conway)

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 3–5
