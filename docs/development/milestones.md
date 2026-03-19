# Roadmap & Milestones

This page summarizes the project milestones tracked in [Plane](https://plane.so). All work items, priorities, and dependencies live in Plane — this page provides a public-facing summary for full transparency.

## Phase Overview

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0 — Development Architecture** | :material-check-circle: Complete | Knowledge base, search infrastructure, MCP integrations, CLI, docs |
| **Phase 1 — Research & Analysis** | :material-check-circle: Complete | 2,046 rules, 1,567 gaps, architecture blueprint, test strategy |
| **Phase 2 — Serialization & Networking** | :material-check-circle: Complete | CBOR decoders, multiplexer, handshake, chain-sync — 643 tests, Haskell test parity |
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

## Phase 1 — Research & Analysis :material-check-circle:{ .green }

**Status: COMPLETE** — 2,046 spec rules extracted, 1,567 gaps QA-validated, architecture blueprint finalized.

Phase 1 used the Phase 0 knowledge base to perform deep research into the Cardano specs and Haskell codebase. The output is a complete architectural design for the Python node, informed by spec analysis and gap documentation.

| Module | Wave | Description | Status |
|--------|------|-------------|--------|
| M1.1 — Subsystem Decomposition | 1 | 10 subsystems, boundaries, specs, dependency graph, phase sequencing | :material-check-circle: Complete |
| M1.2 — Public-Facing Documentation | 2 | 11 "How It Works" pages with SVG infographics | :material-check-circle: Complete |
| M1.3 — Cross-Referencing Infrastructure | 2 | DB tables, PydanticAI pipeline, QA validation pipeline, CLI | :material-check-circle: Complete |
| M1.4 — Spec Rule Extraction | 3 | 2,046 rules extracted across all 10 subsystems | :material-check-circle: Complete |
| M1.5 — Haskell Code & Discussion Mapping | 3 | 7,152 cross-references, 1,567 gaps (425 critical, 427 important) | :material-check-circle: Complete |
| M1.6 — Library Audit | 3 | pycardano (USE), uplc (USE), PyArrow+DuckDB, per-subsystem evaluation | :material-check-circle: Complete |
| M1.7 — Data Architecture | 3 | Arrow+Dict (86x faster than LMDB), benchmarks at 1M UTxOs, crash recovery design | :material-check-circle: Complete |
| M1.8 — Test Strategy & Specifications | 4 | 5-type taxonomy, 17,453 auto-generated test specs, per-phase test gates | :material-check-circle: Complete |
| M1.9 — Architecture Blueprint | 5 | Phase 2-6 roadmap with parallel tracks, risk register, Mithril/recovery design | :material-check-circle: Complete |

### Phase 1 Research Output

| Metric | Count |
|--------|-------|
| Spec rules extracted | 2,032 |
| Cross-references (spec ↔ code) | 12,012 |
| — Implementation links | 6,156 |
| — Test links | 5,075 |
| Gap analysis entries (QA-validated) | 1,491 |
| Critical gaps | 419 |
| Important gaps | 539 |
| Proposed Python test specifications | 16,646 |
| Haskell test functions indexed | 11,611 |
| Haskell test functions linked to specs | 1,453 |
| Subsystems fully analyzed | 10 of 10 |

---

## Phase 2 — Serialization & Networking :material-check-circle:{ .green }

**Status: COMPLETE** — vibe-node talks to Cardano. 643 tests, 1,000-block gate passed, full Haskell test parity.

Phase 2 built the serialization and networking foundation: CBOR block decoders, the Ouroboros multiplexer, typed protocol framework, and the handshake + chain-sync miniprotocols. The gate test proved end-to-end: connect to a real Haskell cardano-node, negotiate version 15, and sync 1,000 block headers.

| Module | Description | Status |
|--------|-------------|--------|
| M2.1 — CBOR Block Decoder | Block header/body decoder (all eras), pycardano evaluation, CBOR property tests | :material-check-circle: Complete |
| M2.2 — TCP Multiplexer | Segment framing, async TCP bearer, mux/demux with fair scheduling and qMax | :material-check-circle: Complete |
| M2.3 — Typed Protocol Framework | Agency model, PeerRole, typed state transitions, protocol runner with codec | :material-check-circle: Complete |
| M2.4 — Handshake Protocol | CBOR messages, FSM, version negotiation (pureHandshake), N2N v14/v15 | :material-check-circle: Complete |
| M2.5 — Chain-Sync Client | CBOR messages, FSM, client with find_intersection/request_next, sync loop | :material-check-circle: Complete |
| M2.6 — Conformance Test Harness | Ogmios fixtures, block metadata conformance, integration tests | :material-check-circle: Complete |

### Phase 2 Test Output

| Category | Tests |
|----------|-------|
| Unit tests | 399 |
| Property tests (Hypothesis) | 59 |
| Conformance tests (Ogmios) | 8 |
| Integration tests (live cardano-node) | 8 |
| Haskell test parity | 70 |
| Test gap fills | 87 |
| **Total** | **643** (was 12 before Phase 2) |

### Pipeline Improvements

Phase 2 also improved the research pipeline:
- Split code search into production vs test code (`is_test` column)
- Keyword search for Haskell test functions (golden*, prop_*, roundTrip*, ts_*)
- Continuation search — automatically fetches deeper when >60% of candidates link
- `vibe-node research extract-rules all` and `qa-validate all` for batch processing
- `vibe-node research reset` for clean re-extraction

---

## Phase 3–6 Overview

- **Phase 3 — Chain Sync & Storage:** Block-fetch client, Arrow+Dict storage engine, Mithril import, crash recovery
- **Phase 4 — Ledger & Consensus:** UTxO ledger validation, Plutus script evaluation, Ouroboros Praos consensus, tip selection
- **Phase 5 — Block Production & N2C:** Block forging, mempool, leader schedule, all node-to-client miniprotocols
- **Phase 6 — Hardening:** Power-loss recovery, memory optimization, 10-day soak test against Haskell nodes

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
