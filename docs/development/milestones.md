# Roadmap & Milestones

This page summarizes the project milestones tracked in [Plane](https://plane.so). All work items, priorities, and dependencies live in Plane — this page provides a public-facing summary for full transparency.

## Phase Overview

| Phase | Status | Description |
|-------|--------|-------------|
| **Phase 0 — Development Architecture** | :material-check-circle: Complete | Knowledge base, search infrastructure, MCP integrations, CLI, docs |
| **Phase 1 — Research & Analysis** | :material-check-circle: Complete | 2,046 rules, 1,567 gaps, architecture blueprint, test strategy |
| **Phase 2 — Serialization & Networking** | :material-check-circle: Complete | CBOR decoders, multiplexer, handshake, chain-sync — 643 tests, Haskell test parity |
| **Phase 3 — Chain Sync & Storage** | :material-check-circle: Complete | Block-fetch, Arrow+Dict storage, Byron-Mary ledger, Mithril import, crash recovery — 1,264 tests |
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

## Phase 3 — Chain Sync & Storage :material-check-circle:{ .green }

**Status: COMPLETE** — vibe-node syncs the chain. 1,264 tests, real preprod benchmark.

Phase 3 built the storage engine, block-fetch protocol, Byron through Mary ledger rules, Mithril snapshot import, and crash recovery. The full preprod benchmark proved we can import 4.5M blocks and hold 3.96M UTxOs in an Arrow table with 1.72s cold start.

| Module | Description | Status |
|--------|-------------|--------|
| M3.1 — Block-Fetch Client | CBOR messages, FSM, client, integration test | :material-check-circle: Complete |
| M3.2 — Storage Abstractions | AppendStore, KeyValueStore, StateStore protocols | :material-check-circle: Complete |
| M3.3 — ImmutableDB | Chunked flat files, primary/secondary indexes, iterators, DeleteAfter | :material-check-circle: Complete |
| M3.4 — VolatileDB | Hash-indexed blocks, successor map, GC, disk persistence | :material-check-circle: Complete |
| M3.5 — LedgerDB | Arrow table + dict UTxO, diff layer, snapshot/restore, rollback | :material-check-circle: Complete |
| M3.6 — Byron Ledger | Byron types, UTXO rules, fee calculation | :material-check-circle: Complete |
| M3.7 — Shelley-Mary Ledger | UTXO/UTXOW, delegation, timelocks, multi-asset | :material-check-circle: Complete |
| M3.8 — ChainDB Coordinator | Block routing, chain selection, GC, wipe volatile | :material-check-circle: Complete |
| M3.9 — Mithril Import | Parse Haskell chunks, import UTxO state | :material-check-circle: Complete |
| M3.10 — Crash Recovery | Arrow IPC snapshots, diff replay, cold start <3s | :material-check-circle: Complete |

### Phase 3 Benchmark (Real Preprod)

| Metric | Value |
|--------|-------|
| Chain size | 4,523,663 blocks, 13.86 GiB |
| UTxO count | 3,959,509 |
| Arrow IPC size | 642 MiB (22% smaller than Haskell's 826 MiB) |
| Cold start | 1.72 seconds |
| Lookup latency | 0.70 μs/op |
| Arrow+dict RSS | 1.8 GiB |
| Parse throughput | 15,208 blocks/s |

### Phase 3 Test Output

| Category | Tests |
|----------|-------|
| Unit tests | 1,168 |
| Property tests (Hypothesis) | 71 |
| Conformance tests (Ogmios) | 12 |
| Integration tests (live node) | 13 |
| **Total** | **1,264** |

---

## Phase 4 — Ledger & Consensus :material-check-circle:{ .green }

**Status: COMPLETE** — 12 modules delivered across 3 waves. 3,415 tests passing.

Phase 4 built the full ledger validation (Alonzo through Conway), Ouroboros Praos consensus with VRF/KES verification, Plutus script evaluation via uplc, the remaining N2N miniprotocols, and a 3-node devnet. Exhaustive Haskell test audit across all phases identified and filled ~900 test gaps. Security fix: SPO default vote protocol-version-dependent behavior (VNODE-280).

| Module | Wave | Description | Status |
|--------|------|-------------|--------|
| M4.1 — VRF (libsodium FFI) | 1 | pybind11 wrapping IOG libsodium fork, ECVRF-ED25519-SHA512-Elligator2 | :material-check-circle: Complete |
| M4.2 — KES | 1 | Sum-composition over Ed25519 via cryptography library | :material-check-circle: Complete |
| M4.3 — Alonzo Ledger | 1 | Collateral, datums, script integrity hash, two-phase validation, 6 UTXOW rules | :material-check-circle: Complete |
| M4.4 — Plutus Integration | 1 | uplc bridge, ScriptContext V1/V2/V3, cost model, ExUnits, UPLC conformance | :material-check-circle: Complete |
| M4.5 — Tx-Submission Protocol | 1 | N2N tx-submission miniprotocol (protocol ID 4) | :material-check-circle: Complete |
| M4.6 — Keep-Alive Protocol | 1 | N2N keep-alive miniprotocol (protocol ID 8) | :material-check-circle: Complete |
| M4.7 — Babbage-Conway Ledger | 2 | Inline datums, reference scripts, governance, DRep delegation, enactment | :material-check-circle: Complete |
| M4.8 — Ouroboros Praos | 2 | Chain selection, leader election, block header verification, mutation testing | :material-check-circle: Complete |
| M4.9 — Epoch Boundary | 2 | Stake snapshots, rewards, nonce evolution, protocol params | :material-check-circle: Complete |
| M4.10 — Hard Fork Combinator | 3 | Era transitions Byron→Conway, state translation, PastHorizonError | :material-check-circle: Complete |
| M4.11 — Conformance Suite | 3 | Full-era ledger conformance, UPLC conformance (999 test cases) | :material-check-circle: Complete |
| M4.12 — Devnet Integration | 3 | 3-node devnet, genesis files, monitoring | :material-check-circle: Complete |

---

## Phase 5 — Block Production & Full Node Integration :material-check-circle:{ .green }

**Status: COMPLETE** — 28 modules delivered across 7 waves. 4,045+ tests passing.

Phase 5 built block production (VRF leader election, KES-signed forging), the mempool, all N2C miniprotocols, all N2N server/responder implementations, the full node main loop (`vibe-node serve`), pipelining, and the complete integration wiring that connects every subsystem into a working node. The 3-node private devnet runs with vibe-node forging blocks alongside 2 Haskell nodes with bidirectional communication.

| Module | Wave | Description | Status |
|--------|------|-------------|--------|
| M5.1 — Mempool | 1 | TxValidator protocol, capacity management, re-validation, eviction | :material-check-circle: Complete |
| M5.2 — Block Forging | 1 | VRF leader check, KES-signed Babbage+ header, block body construction | :material-check-circle: Complete |
| M5.3 — Local Chain-Sync (N2C) | 1 | Server with ChainDB follower, full block streaming | :material-check-circle: Complete |
| M5.4 — Local Tx-Submission (N2C) | 1 | Server with mempool integration, era-tagged CBOR | :material-check-circle: Complete |
| M5.5 — Local State-Query (N2C) | 1 | Server with LedgerDB queries, acquire/release pattern | :material-check-circle: Complete |
| M5.6 — Local Tx-Monitor (N2C) | 1 | Server with mempool snapshot, has-tx, sizes | :material-check-circle: Complete |
| M5.7 — Node Main Loop | 2 | run_node(), SlotClock, PeerManager, signal handling | :material-check-circle: Complete |
| M5.8 — Pipelining | 2 | PipelinedRunner, chain-sync 300 in-flight, block-fetch 100 | :material-check-circle: Complete |
| M5.9 — Devnet Genesis Fix | 2 | Hex addresses, genDelegs, VRF hashes, TraceDispatcher config | :material-check-circle: Complete |
| M5.13 — N2N Protocol Servers | 4 | Handshake responder, chain-sync server, block-fetch server, keep-alive server, tx-submission server | :material-check-circle: Complete |
| M5.14 — Storage Integration | 5 | ChainDB stack in run_node(), forged blocks persisted | :material-check-circle: Complete |
| M5.15 — Sync & Validation Pipeline | 5 | chain-sync → block-fetch → validate → store | :material-check-circle: Complete |
| M5.16 — Inbound Connection Handlers | 6 | N2N + N2C servers on inbound connections, shared state | :material-check-circle: Complete |
| M5.17 — Forge-to-Announce Pipeline | 6 | NodeKernel, chain-sync/block-fetch servers serve forged blocks | :material-check-circle: Complete |
| M5.18 — KES Key Deserialization | 4 | 608-byte Sum6KES format, deterministic keygen from seed | :material-check-circle: Complete |
| M5.19 — Persistent Block-Fetch | 4 | Continuous mode from asyncio.Queue, no protocol reset | :material-check-circle: Complete |
| M5.20 — Block Validation in Sync | 5 | Era-aware validate_block() on every received block | :material-check-circle: Complete |
| M5.21 — Ledger State Application | 5 | UTxO consumed/created tracking via LedgerDB.apply_block() | :material-check-circle: Complete |
| M5.22 — Epoch Nonce | 4 | Genesis hash seed, VRF accumulation, epoch boundary evolution | :material-check-circle: Complete |
| M5.23 — N2C Server Wiring | 4 | N2C handshake (v16-20), all 4 local servers on Unix socket | :material-check-circle: Complete |
| M5.25 — Stake Distribution | 7 | Genesis stake parsing, per-pool relative stake for leader check | :material-check-circle: Complete |
| M5.26 — KES Key Evolution | 7 | Period tracking, evolution on boundary, expiry detection | :material-check-circle: Complete |
| M5.27 — Mithril Snapshot Import | 7 | --mithril-snapshot CLI, startup import, known_points from tip | :material-check-circle: Complete |
| M5.28 — Strict Block Validation | 7 | Reject invalid blocks, protocol params from genesis, --permissive-validation | :material-check-circle: Complete |

### Phase 5 — CLI & Node Entry Points

The node is launched via `vibe-node serve` with full configuration:

```bash
vibe-node serve \
  --network-magic 42 \
  --genesis-dir infra/devnet/genesis \
  --peers localhost:30001,localhost:30002 \
  --vrf-key keys/pool3/vrf.skey \
  --cold-skey keys/pool3/cold.skey \
  --port 3001
```

All options support environment variables (`VIBE_*`) for Docker deployment.

### Phase 5 — Devnet Results

The 3-node private devnet (2 Haskell + 1 vibe-node) demonstrates:

- Bidirectional handshake v14 between all nodes
- vibe-node syncs 1,896+ headers from Haskell peers
- vibe-node forges 7+ blocks per minute via VRF leader election
- Haskell nodes connect inbound to vibe-node and handshake successfully
- All 3 nodes running, healthy, producing blocks on the same chain

### Phase 5 Test Output

| Category | Tests |
|----------|-------|
| Unit tests | 3,200+ |
| Property tests (Hypothesis) | 200+ |
| Conformance tests | 100+ |
| Integration tests | 50+ |
| KES/VRF crypto | 130+ |
| **Total** | **4,045+** |

---

## Phase 6 — Hardening :material-clock-outline:

**Status: PLANNED** — Production readiness and conformance verification.

| Module | Description | Status |
|--------|-------------|--------|
| M5.10 — Devnet 48h Test | Continuous 48-hour devnet run, tip agreement monitoring | :material-clock-outline: Planned |
| M5.11 — Preprod Block Production | Produce valid blocks on preprod testnet | :material-clock-outline: Planned |
| M5.12 — Haskell Conformance Verification | Full end-to-end comparison against Haskell node | :material-clock-outline: Planned |
| M6.1 — Power-loss Recovery | Verify crash recovery with kill -9 during sync | :material-clock-outline: Planned |
| M6.2 — Memory Optimization | Match or beat Haskell node memory usage | :material-clock-outline: Planned |
| M6.3 — 10-Day Soak Test | 10 continuous days of tip agreement within 2160 slots | :material-clock-outline: Planned |

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
