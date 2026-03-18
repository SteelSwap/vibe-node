# Miniprotocols (Node-to-Client)

## Overview
Local chain-sync, local tx-submission, local state-query, and local tx-monitor for wallet and tool communication via Unix sockets.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| ouroboros-network local protocol specs | See [specs index](../../specs/index.md) |

## Haskell Package Structure
ouroboros-network-protocols. Same typed-protocols state machine framework as N2N but over Unix sockets / named pipes.

## Module Decomposition
- Local chain-sync
- Local tx-submission
- Local state-query
- Local tx-monitor

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 5
