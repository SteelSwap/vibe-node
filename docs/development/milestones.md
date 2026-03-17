# Roadmap & Milestones

This page summarizes the project milestones tracked in [Plane](https://plane.so). All work items, priorities, and dependencies live in Plane — this page provides a public-facing summary for full transparency.

## Phase Overview

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0 — Development Architecture** | :material-check-circle: Complete | Knowledge base, search infrastructure, MCP integrations, CLI, docs |
| **Phase 1 — Research & Analysis** | :material-progress-wrench: In Progress | Spec deep-dives, Haskell code analysis, architecture design |
| **Phase 2 — Networking** | :material-clock-outline: Planned | Ouroboros multiplexer, miniprotocol state machines |
| **Phase 3 — Chain Sync & Storage** | :material-clock-outline: Planned | Chain-sync client, block fetch, CBOR deserialization, persistent storage |
| **Phase 4 — Ledger & Consensus** | :material-clock-outline: Planned | UTxO ledger rules, Plutus evaluation, Ouroboros Praos, VRF/KES |
| **Phase 5 — Block Production & N2C** | :material-clock-outline: Planned | Block forging, mempool, all node-to-client miniprotocols |
| **Phase 6 — Hardening** | :material-clock-outline: Planned | Power-loss recovery, memory optimization, 10-day soak test |

---

## Phase 0 — Development Architecture :material-check-circle:{ .green }

**Status: COMPLETE** — All 9 modules delivered across 4 waves.

Phase 0 produced zero node code. It built the complete development infrastructure so that every subsequent phase has searchable specs, indexed Haskell source, a live Cardano node for conformance testing, and MCP integrations for Agent Millenial to consult during implementation.

| Module | Description | Status |
|--------|-------------|--------|
| M0.1 — Docker Compose Stack | ParadeDB, Ollama, Mithril, cardano-node, Ogmios, PaddleOCR | :material-check-circle: Complete |
| M0.2 — Submodules & Schema | 6 git submodules, 7+ database tables, SQLModel models | :material-check-circle: Complete |
| M0.3 — Spec Ingestion | LaTeX, Markdown, CDDL, Literate Agda, PDF via PaddleOCR sidecar | :material-check-circle: Complete |
| M0.4 — Code Indexing | tree-sitter Haskell + Agda, content-hash dedup, versioned tags | :material-check-circle: Complete |
| M0.5 — GitHub Ingestion | Issues, PRs, comments via GraphQL from 7 repos | :material-check-circle: Complete |
| M0.6 — Search & Indexes | BM25 + HNSW indexes, RRF fusion, composable search templates | :material-check-circle: Complete |
| M0.7 — MCP Integrations | Search MCP (6 tools) + CrystalDB MCP for raw SQL | :material-check-circle: Complete |
| M0.8 — CLI | infra, ingest, db subcommands with full coverage | :material-check-circle: Complete |
| M0.9 — Documentation | 4-tab MkDocs site, SteelSwap branding, devlog | :material-check-circle: Complete |

See [Phase 0 Tasks](tasks.md) for the full breakdown of 56 tasks across these modules.

---

## Phase 1 — Research & Analysis :material-progress-wrench:

**Status: IN PROGRESS** — Design specs and implementation plans ready.

Phase 1 uses the Phase 0 knowledge base to perform deep research into the Cardano specs and Haskell codebase. The output is a complete architectural design for the Python node, informed by spec analysis and gap documentation.

| Module | Description | Status |
|--------|-------------|--------|
| M1.1 — Networking Spec Analysis | Ouroboros network spec deep-dive, multiplexer design | :material-clock-outline: Planned |
| M1.2 — Chain-Sync Protocol Analysis | Chain-sync miniprotocol spec and Haskell implementation study | :material-clock-outline: Planned |
| M1.3 — Block-Fetch Protocol Analysis | Block-fetch miniprotocol spec and implementation study | :material-clock-outline: Planned |
| M1.4 — CBOR & Serialization Analysis | CDDL schemas, CBOR encoding rules, era-specific formats | :material-clock-outline: Planned |
| M1.5 — Ledger Rules Analysis | Shelley through Conway ledger transition rules | :material-clock-outline: Planned |
| M1.6 — Consensus Analysis | Ouroboros Praos, VRF/KES, chain selection | :material-clock-outline: Planned |
| M1.7 — Storage Architecture Design | Block storage, ledger state, UTxO set persistence | :material-clock-outline: Planned |
| M1.8 — Node Architecture Design | Overall Python node architecture, module boundaries, data flow | :material-clock-outline: Planned |
| M1.9 — Gap Analysis Compilation | Comprehensive spec-vs-Haskell gap analysis across all subsystems | :material-clock-outline: Planned |

---

## Phase 2–6 Overview

Phases 2 through 6 implement the actual Cardano node, progressing from networking through hardening:

- **Phase 2 — Networking:** Ouroboros multiplexer, typed protocol state machines, connection management
- **Phase 3 — Chain Sync & Storage:** Chain-sync and block-fetch clients, CBOR deserialization, block storage
- **Phase 4 — Ledger & Consensus:** UTxO ledger validation, Plutus script evaluation, Ouroboros Praos consensus, tip selection
- **Phase 5 — Block Production & N2C:** Block forging, mempool, leader schedule, all node-to-client miniprotocols
- **Phase 6 — Hardening:** Power-loss recovery, memory optimization, 10-day soak test against Haskell nodes

Detailed task breakdowns for Phases 2–6 will be published as each phase begins.

---

## Acceptance Criteria

The final deliverable must satisfy all of [Pi Lanningham's challenge criteria](../about/challenge.md), verified over a 10-day testing window:

1. Sync from a recent mainnet Mithril snapshot or genesis to tip
2. Produce valid blocks accepted by other nodes on preview/preprod
3. Implement all node-to-node and node-to-client miniprotocols
4. Run in a private devnet alongside 2 Haskell nodes
5. Match or beat Haskell node memory usage over 10 days
6. Agree on tip selection within 2160 slots for 10 continuous days
7. Recover from power-loss without human intervention
8. Agree with the Haskell node on all block/transaction validity and chain-tip selection
