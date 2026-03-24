# vibe-node

[![Code: AGPL-3.0](https://img.shields.io/badge/Code-AGPL--3.0-blue.svg)](LICENSE)
[![Data: CC-BY-SA-4.0](https://img.shields.io/badge/Data-CC--BY--SA--4.0-lightgrey.svg)](LICENSE-DATA)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![Built with AI](https://img.shields.io/badge/built%20with-AI%20%28vibe%20coded%29-ff6d00.svg)]()
[![Cardano](https://img.shields.io/badge/Cardano-node-0033AD.svg)](https://cardano.org)
[![Tests](https://img.shields.io/badge/tests-4%2C290%20passing-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-v0.5.0-blue.svg)]()

A vibe-coded, spec-compliant Cardano node written in Python. **v0.5.0: The vibes are valid.**

---

## What is this?

**vibe-node** is a from-scratch Cardano node built entirely through AI-assisted development in response to [Pi Lanningham's open challenge](https://x.com/Quantumplation). Every commit is public. Every prompt is visible. Every decision is documented.

This is not just a node — it's a public education in vibe coding with extreme precision.

## Current Status

> **Phase 5 — Block Production & Haskell Acceptance: COMPLETE.** 4,290+ tests passing.
> vibe-node forges blocks that are **accepted by Haskell cardano-nodes**. VRF proofs, KES signatures, header format, and block numbering all pass Haskell validation. The 3-node private devnet (2 Haskell + 1 vibe-node) runs with bidirectional chain-sync, block-fetch, and block production.

### What the node can do

- **Sync** from genesis or Mithril snapshot, following the chain tip via pipelined chain-sync + block-fetch
- **Forge blocks** via VRF leader election with KES-signed headers and operational certificates
- **Validate** all-era blocks (Byron through Conway) with full ledger rules, Plutus evaluation, and UTxO tracking
- **Store** blocks in Arrow+Dict storage engine (ImmutableDB, VolatileDB, LedgerDB, ChainDB) with crash recovery
- **Communicate** via all N2N miniprotocols (handshake, chain-sync, block-fetch, tx-submission, keep-alive) — both client and server
- **Serve** local clients via all N2C miniprotocols (local chain-sync, local tx-submission, local state-query, local tx-monitor)
- **Manage** a mempool with transaction validation, capacity enforcement, and block selection
- **Run** in a 3-node private devnet with 2 Haskell nodes — bidirectional chain-sync, block-fetch, and block production
- **Produce blocks accepted by Haskell nodes** — VRF (Praos mkInputVRF), KES signatures, Babbage/Conway header format, and chain selection all validated

### What's next

- Phase 6: Hardening — 48-hour devnet soak test, preprod block production, power-loss recovery validation, memory optimization, 10-day conformance window
- Fix remaining chain ordering edge case (UnexpectedPrevHash during fork switches)
- Ledger state ticking for transaction-bearing blocks

### Phase Summary

| Phase | Status | Highlights |
|-------|--------|------------|
| **Phase 0** — Dev Architecture | Complete | Knowledge base, search infra, MCP, CLI, docs |
| **Phase 1** — Research & Analysis | Complete | 2,046 rules, 1,567 gaps, architecture blueprint |
| **Phase 2** — Serialization & Networking | Complete | CBOR decoders, multiplexer, handshake, chain-sync — 643 tests |
| **Phase 3** — Chain Sync & Storage | Complete | Block-fetch, Arrow+Dict storage, Byron-Mary ledger, Mithril, crash recovery — 1,264 tests |
| **Phase 4** — Ledger & Consensus | Complete | VRF/KES, Alonzo-Conway ledger, Plutus, Praos consensus, HFC, devnet — 3,415 tests |
| **Phase 5** — Block Production & N2C | Complete | Block forging, mempool, N2C miniprotocols, Haskell block acceptance, 3-node devnet — 4,290+ tests |

### Benchmarks (Real Preprod)

| Metric | Value |
|--------|-------|
| Chain size | 4,523,663 blocks, 13.86 GiB |
| UTxO count | 3,959,509 |
| Arrow IPC size | 642 MiB (22% smaller than Haskell's 826 MiB) |
| Cold start | 1.72 seconds |
| Lookup latency | 0.70 us/op |
| Parse throughput | 15,208 blocks/s |

### Preview Full Sync Benchmark

Infrastructure for benchmarking full preview testnet sync against the Haskell cardano-node. See [benchmark methodology](docs/development/preview-sync-benchmark.md) for details.

```bash
# Sync vibe-node against preview testnet with metrics capture
./scripts/run-sync-benchmark.sh --interval 30

# Sync Haskell node for comparison
./scripts/run-haskell-sync-benchmark.sh --interval 30

# Analyze and compare results
python scripts/analyze-sync-results.py \
    --vibe infra/preview-sync/results/vibe-node-metrics.json \
    --haskell infra/preview-sync/results/haskell-node-metrics.json \
    --output benchmarks/preview-sync/
```

## Quick Start

```bash
# Clone with submodules (needed for VRF)
git clone --recurse-submodules https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync

# Build VRF native extension (requires cmake + autotools)
cd packages/vibe-cardano && cmake -B build && cmake --build build && cd ../..

# Run the full test suite (~4,000+ tests)
uv run pytest

# Start the node (relay mode, connect to preview/preprod)
uv run vibe-node serve --network-magic 2 --peers relays-new.cardano-testnet.iohkdev.io:3001

# Start the 3-node devnet
cd infra/devnet
./scripts/generate-keys.sh
docker compose -f docker-compose.devnet.yml up -d
```

## Architecture

```
vibe-node monorepo (uv workspace)
├── packages/
│   ├── vibe-core/        # Protocol-agnostic: multiplexer, typed protocols, pipelining
│   ├── vibe-cardano/     # Cardano-specific: serialization, network, ledger, storage, crypto, forge, mempool
│   └── vibe-tools/       # Dev infrastructure: ingestion, search, MCP, CLI
├── vendor/
│   └── libsodium-iog/    # IOG libsodium fork (VRF extensions)
├── infra/
│   ├── devnet/           # 3-node private devnet (Docker Compose)
│   └── preview-sync/     # Preview testnet sync benchmark (vs Haskell)
├── docs/                 # MkDocs Material site
└── tests/                # Integration, conformance, and property tests
```

### Node Components

| Component | Description |
|-----------|-------------|
| **Multiplexer** | Segment framing, async TCP bearer, fair scheduling |
| **Miniprotocols** | All N2N (5) and N2C (4) protocols — client and server |
| **Pipelining** | PipelinedRunner with backpressure (chain-sync: 300, block-fetch: 100) |
| **Ledger** | Byron through Conway validation, Plutus V1/V2/V3 via uplc |
| **Consensus** | Ouroboros Praos: VRF leader election, KES signing, chain selection |
| **Storage** | ChainDB (ImmutableDB + VolatileDB + LedgerDB), Arrow IPC snapshots |
| **Mempool** | Transaction validation, capacity management, block selection |
| **Block Forge** | VRF proof, KES-signed header, operational certificate |
| **Node Main** | `vibe-node serve` CLI with full genesis config, key loading, graceful shutdown |

## Documentation

Full documentation is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/):

```bash
uv run mkdocs serve
```

- **[About](docs/about/index.md)** — The challenge, methodology, toolchain, and how we build
- **[Specifications](docs/specs/index.md)** — Cardano specs and gap analysis
- **[Development](docs/development/index.md)** — Roadmap, milestones, and progress
- **[Reference](docs/reference/index.md)** — CLI, schema, architecture, and pipeline docs

## Licensing

This project uses a dual-license structure to reflect the two distinct work products it produces.

| Component | License | File |
|-----------|---------|------|
| Source code | [AGPL-3.0](LICENSE) | `LICENSE` |
| Database contents | [CC-BY-SA-4.0](LICENSE-DATA) | `LICENSE-DATA` |

**Source code** (everything under `packages/`, `tests/`, `infra/`, configuration files, CLI tooling, ingestion pipelines, etc.) is licensed under the GNU Affero General Public License v3.0.

**Database contents** (the populated knowledge base produced by the ingestion pipelines — spec extractions, cross-references, test specifications, embeddings, and all other derived data) are a separate work product licensed under the Creative Commons Attribution-ShareAlike 4.0 International License. If you redistribute or build upon the database contents, you must provide attribution and share under the same or a compatible license.

Relicensing of either component may be available on request. Contact SteelSwap for details.

&copy; 2026 SteelSwap
