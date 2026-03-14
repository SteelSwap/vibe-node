# Roadmap & Milestones

This page summarizes the project milestones tracked in [Plane](https://plane.so). All work items, priorities, and dependencies live in Plane — this page provides a public-facing summary for full transparency.

## Milestone Overview

| Milestone | Status | Description |
|-----------|--------|-------------|
| **M0 — Project Scaffold** | :material-progress-wrench: In Progress | Project structure, CI, docs, tooling |
| **M1 — Networking** | :material-clock-outline: Planned | Ouroboros multiplexer, miniprotocol state machines |
| **M2 — Chain Sync** | :material-clock-outline: Planned | Chain-sync client, header validation |
| **M3 — Block Fetch & Storage** | :material-clock-outline: Planned | Block fetching, CBOR deserialization, persistent storage |
| **M4 — Ledger Validation** | :material-clock-outline: Planned | UTxO ledger rules, Plutus script evaluation |
| **M5 — Consensus** | :material-clock-outline: Planned | Ouroboros Praos, VRF/KES, tip selection |
| **M6 — Block Production** | :material-clock-outline: Planned | Forge blocks, leader schedule, mempool |
| **M7 — Node-to-Client** | :material-clock-outline: Planned | Local chain-sync, state-query, tx-submission, tx-monitor |
| **M8 — Hardening** | :material-clock-outline: Planned | Power-loss recovery, memory optimization, 10-day soak test |

## Acceptance Criteria

The final deliverable must satisfy all of [Pi Lanningham's challenge criteria](../index.md), verified over a 5-day testing window:

1. Sync from a recent mainnet Mithril snapshot or genesis to tip
2. Produce valid blocks accepted by other nodes on preview/preprod
3. Implement all node-to-node and node-to-client miniprotocols
4. Run in a private devnet alongside 2 Haskell nodes
5. Match or beat Haskell node memory usage over 10 days
6. Agree on tip selection within 2160 slots for 10 continuous days
7. Recover from power-loss without human intervention
8. Agree with the Haskell node on all block/transaction validity and chain-tip selection
