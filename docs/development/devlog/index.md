# Development Log

The development log captures the journey — what we built, what we tried, what failed, and what we learned. Radical transparency means the dead ends get documented too.

Each entry is organized by phase, with specific module and work item details.

---

## Phase 5: Block Production & Haskell Acceptance

- **[Phase 5 — Block Production & Haskell Acceptance](phase5.md)** (M5.1–M5.33)
    - Block forging (VRF leader election, KES-signed headers, operational certificates)
    - Mempool with tx validation, capacity enforcement, block selection
    - All N2N server protocols (chain-sync, block-fetch, tx-submission, keep-alive)
    - All N2C miniprotocols (local chain-sync, local tx-submission, local state-query, local tx-monitor)
    - **Haskell block acceptance** — forged blocks pass VRF, KES, header format, and chain validation
    - 9 critical bugs found and fixed via systematic Haskell comparison
    - 4,290+ tests, 3-node devnet with bidirectional block production

## Phase 4: Ledger & Consensus

- **[Phase 4 — Ledger & Consensus](phase4.md)** (M4.1–M4.12)
    - VRF (libsodium FFI via pybind11), KES (sum-composition over Ed25519)
    - Alonzo through Conway ledger rules, Plutus integration via uplc
    - Ouroboros Praos consensus, epoch boundary, hard fork combinator
    - Tx-submission + keep-alive miniprotocols, 3-node devnet

## Phase 3: Chain Sync & Storage

- **[Phase 3 — Chain Sync & Storage](phase3.md)** (M3.1–M3.10)
    - Block-fetch client, Arrow+Dict storage engine (ImmutableDB, VolatileDB, LedgerDB, ChainDB)
    - Byron through Mary ledger rules (UTXO, delegation, timelocks, multi-asset)
    - Mithril snapshot import, crash recovery (Arrow IPC + diff replay)
    - 1,264 tests, real preprod benchmark (3.96M UTxOs, 1.72s cold start)

## Phase 2: Serialization & Networking

- **[Phase 2 — Serialization & Networking](phase2.md)** (M2.1–M2.6)
    - CBOR block decoder (all eras), TCP multiplexer, typed protocol framework
    - Handshake + chain-sync miniprotocols — first communication with Cardano
    - 491 tests, 1,000-block gate test passed
    - Pipeline improvements: is_test tagging, split search, continuation, batch CLI

## Phase 1: Research & Analysis

- **[Phase 1 — Research & Analysis](phase1.md)** (M1.1–M1.9)
    - 2,046 spec rules extracted, 1,567 QA-validated gaps, 7,152 cross-references
    - Architecture: Arrow+Dict storage, pycardano, uplc, 3-track parallel roadmap
    - Monorepo restructure: vibe-core / vibe-cardano / vibe-tools workspace
    - Test strategy: 5-type taxonomy, 17,453 auto-generated test specs

## Phase 0: Development Architecture

- **[Phase 0 — Development Architecture](phase0.md)** (M0.1–M0.9)
    - Wave 1: Docker Compose stack, git submodules, database schema, documentation site
    - Wave 2: Spec ingestion, code indexing, GitHub issues/PRs, CLI commands
    - Wave 3: BM25/HNSW indexes, search templates, 6-tool FastMCP server, CrystalDB integration
