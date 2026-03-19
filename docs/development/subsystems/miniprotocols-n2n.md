# Miniprotocols (Node-to-Node)

## Overview
Chain-sync, block-fetch, tx-submission, and keep-alive state machines for inter-node communication.

## Governing Specs
| Spec Source | Key Sections |
|-------------|-------------|
| ouroboros-network miniprotocol specs | See [specs index](../../specs/index.md) |

## Haskell Package Structure
ouroboros-network-protocols (518 functions), ouroboros-network (877 functions). Key namespace: `Ouroboros.Network.Protocol` (399 functions).

## Module Decomposition
- Chain-sync client/server
- Block-fetch client/server
- Tx-submission client/server
- Keep-alive
- Peer sharing

## Library Recommendations
*To be populated during Phase 1 analysis (M1.8)*

## Test Strategy
*To be populated during Phase 1 analysis (M1.8)*

## Phase Assignment
**Implementation Phase:** 2
