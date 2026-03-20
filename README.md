# vibe-node

[![Code: AGPL-3.0](https://img.shields.io/badge/Code-AGPL--3.0-blue.svg)](LICENSE)
[![Data: CC-BY-SA-4.0](https://img.shields.io/badge/Data-CC--BY--SA--4.0-lightgrey.svg)](LICENSE-DATA)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![Built with AI](https://img.shields.io/badge/built%20with-AI%20%28vibe%20coded%29-ff6d00.svg)]()
[![Cardano](https://img.shields.io/badge/Cardano-node-0033AD.svg)](https://cardano.org)
[![Tests](https://img.shields.io/badge/tests-1%2C617%20passing-brightgreen.svg)]()
[![Version](https://img.shields.io/badge/version-v0.3.0-blue.svg)](https://github.com/SteelSwap/vibe-node/releases/tag/v0.3.0)

A vibe-coded, spec-compliant Cardano node written in Python.

---

## What is this?

**vibe-node** is a from-scratch Cardano node built entirely through AI-assisted development in response to [Pi Lanningham's open challenge](https://x.com/Quantumplation). Every commit is public. Every prompt is visible. Every decision is documented.

This is not just a node — it's a public education in vibe coding with extreme precision.

## Current Status

> **Phase 4 — Ledger & Consensus: IN PROGRESS** (Wave 1 complete, Wave 2 next).
> vibe-node syncs the chain, decodes all eras, validates Byron-Mary, and has Alonzo ledger + Plutus evaluation + VRF/KES crypto + all N2N miniprotocols.

### What the node can do

- **Sync** from a Mithril snapshot and follow the chain tip via chain-sync + block-fetch
- **Decode** all-era Cardano blocks (Byron through Conway) via pycardano CBOR
- **Store** blocks in Arrow+Dict storage engine (ImmutableDB, VolatileDB, LedgerDB, ChainDB)
- **Validate** Byron, Shelley, Allegra, Mary, and Alonzo ledger rules
- **Evaluate** Plutus scripts (V1/V2/V3) via uplc with cost model enforcement
- **Verify** VRF proofs (pybind11 + IOG libsodium) and KES signatures (sum-composition)
- **Communicate** via all 5 N2N miniprotocols: handshake, chain-sync, block-fetch, tx-submission, keep-alive
- **Recover** from crashes via Arrow IPC snapshots + diff replay (cold start: 1.72s at 3.96M UTxOs)

### What's next

- Babbage-Conway ledger rules (inline datums, reference scripts, governance)
- Ouroboros Praos consensus (chain selection, leader election, block header verification)
- Hard fork combinator (era transitions)
- 3-node private devnet (1 vibe-node + 2 Haskell)

### Phase Summary

| Phase | Status | Highlights |
|-------|--------|------------|
| **Phase 0** — Dev Architecture | Complete | Knowledge base, search infra, MCP, CLI, docs |
| **Phase 1** — Research & Analysis | Complete | 2,046 rules, 1,567 gaps, architecture blueprint |
| **Phase 2** — Serialization & Networking | Complete | CBOR decoders, multiplexer, handshake, chain-sync — 643 tests |
| **Phase 3** — Chain Sync & Storage | Complete | Block-fetch, Arrow+Dict storage, Byron-Mary ledger, Mithril, crash recovery — 1,264 tests |
| **Phase 4** — Ledger & Consensus | **In Progress** | VRF/KES, Alonzo ledger, Plutus, tx-submission, keep-alive — 465 new tests |

### Benchmarks (Real Preprod)

| Metric | Value |
|--------|-------|
| Chain size | 4,523,663 blocks, 13.86 GiB |
| UTxO count | 3,959,509 |
| Arrow IPC size | 642 MiB (22% smaller than Haskell's 826 MiB) |
| Cold start | 1.72 seconds |
| Lookup latency | 0.70 us/op |
| Parse throughput | 15,208 blocks/s |

## Architecture

```
vibe-node monorepo (uv workspace)
├── packages/
│   ├── vibe-core/        # Protocol-agnostic: multiplexer, typed protocols, storage abstractions
│   ├── vibe-cardano/     # Cardano-specific: serialization, network, ledger, storage, crypto, plutus
│   └── vibe-tools/       # Dev infrastructure: ingestion, search, MCP, CLI
├── vendor/
│   └── libsodium-iog/    # IOG libsodium fork (VRF extensions)
├── infra/                # Docker Compose, Dockerfiles
├── docs/                 # MkDocs Material site
└── tests/                # Integration and conformance tests
```

## Quick Start

```bash
git clone --recurse-submodules https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync

# Build VRF native extension (optional — requires C compiler)
./scripts/build-vrf.sh

# Run the full test suite (~2,400 tests)
uv run pytest

# Start infrastructure (ParadeDB, cardano-node, Ogmios, etc.)
uv run vibe-node infra up

# Search the knowledge base
uv run vibe-node db search "Ouroboros Praos VRF"
```

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
