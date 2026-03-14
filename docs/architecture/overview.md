# Architecture Overview

!!! note "Under Construction"
    Architecture documentation will be built incrementally as the node takes shape. Each major subsystem gets its own design doc with rationale, alternatives considered, and conformance testing approach.

## High-Level Components

```mermaid
graph TB
    NET[Networking Layer] --> CS[Chain Sync]
    NET --> BF[Block Fetch]
    NET --> TX[Tx Submission]
    NET --> KA[Keep-Alive]
    CS --> LEDGER[Ledger State]
    BF --> LEDGER
    TX --> LEDGER
    LEDGER --> CONSENSUS[Consensus / Ouroboros Praos]
    CONSENSUS --> FORGE[Block Production]
    LEDGER --> STORE[Storage]
```

## Design Principles

- **Correctness first.** The Haskell node is the oracle. If we disagree, we're wrong.
- **Stream everything.** Minimize memory by processing data incrementally.
- **Python until proven otherwise.** Reach for Rust/C extensions only when profiling demands it.
- **Test at the boundary.** Conformance tests against the Haskell node are the gold standard.
