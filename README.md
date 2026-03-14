# vibe-node

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![Built with AI](https://img.shields.io/badge/built%20with-AI%20%28vibe%20coded%29-ff6d00.svg)]()
[![Cardano](https://img.shields.io/badge/Cardano-node-0033AD.svg)](https://cardano.org)

A vibe-coded, spec-compliant Cardano node written in Python.

---

## What is this?

**vibe-node** is a from-scratch Cardano node built entirely through AI-assisted development in response to [Pi Lanningham's open challenge](https://x.com/Quantumplation). Every commit is public. Every prompt is visible. Every decision is documented.

This is not just a node — it's a public education in vibe coding with extreme precision.

## Current Status

> **Phase 0 — Development Architecture** in progress. Building the knowledge base and dev infrastructure.

### Phase 0: Dev Infrastructure

| Component | Status |
|-----------|--------|
| Project scaffold (Python 3.14, uv, typer CLI) | Done |
| Docker Compose stack (ParadeDB, vLLM, cardano-node, Ogmios) | In Progress |
| Git submodules (cardano-node, cardano-ledger, ouroboros-network) | In Progress |
| Database schema (SQLModel + ParadeDB init) | In Progress |
| Spec ingestion pipeline (PaddleOCR, pandoc) | Not started |
| Code indexing pipeline (tree-sitter-haskell) | Not started |
| GitHub issues indexing | Not started |
| Search infrastructure (BM25 + vector + RRF) | Not started |
| MCP integrations (Search MCP, CrystalDB MCP) | Not started |
| CLI commands (infra, ingest, db) | Not started |
| Documentation (How We Build, Gap Analysis) | In Progress |

### Node Implementation (Phase 1+)

| Component | Status |
|-----------|--------|
| Networking / Multiplexer | Not started |
| Chain Sync | Not started |
| Block Fetch | Not started |
| Ledger Validation | Not started |
| Consensus (Ouroboros Praos) | Not started |
| Block Production | Not started |
| Node-to-Client protocols | Not started |

## Quick Start

```bash
git clone https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync
uv run vibe-node serve
```

### Development Infrastructure

```bash
# Start the full dev stack (requires Docker)
docker compose up -d

# Or CPU-only mode (no GPU required for vLLM):
docker compose --profile cpu up -d
```

## Documentation

Full documentation is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) and available in the `docs/` directory:

```bash
uv run mkdocs serve
```

- **[How We Build](docs/methodology/index.md)** — Vibe-coding methodology, toolchain, agent architecture
- **[Gap Analysis](docs/gap-analysis/index.md)** — Spec vs. implementation divergences
- **[Architecture](docs/architecture/overview.md)** — How the node is structured and why
- **[Roadmap](docs/roadmap/tasks.md)** — 56 tasks across 9 modules for Phase 0
- **[Development Log](docs/devlog/index.md)** — The journey, including dead ends and lessons learned

## License

[AGPL-3.0](LICENSE)
