# vibe-node

[![Code: AGPL-3.0](https://img.shields.io/badge/Code-AGPL--3.0-blue.svg)](LICENSE)
[![Data: CC-BY-SA-4.0](https://img.shields.io/badge/Data-CC--BY--SA--4.0-lightgrey.svg)](LICENSE-DATA)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](https://www.python.org/downloads/)
[![Built with AI](https://img.shields.io/badge/built%20with-AI%20%28vibe%20coded%29-ff6d00.svg)]()
[![Cardano](https://img.shields.io/badge/Cardano-node-0033AD.svg)](https://cardano.org)

A vibe-coded, spec-compliant Cardano node written in Python.

---

## What is this?

**vibe-node** is a from-scratch Cardano node built entirely through AI-assisted development in response to [Pi Lanningham's open challenge](https://x.com/Quantumplation). Every commit is public. Every prompt is visible. Every decision is documented.

This is not just a node — it's a public education in vibe coding with extreme precision.

## Current Status

> **Phase 0 — Development Architecture** nearing completion. Knowledge base operational, node implementation next.

### Phase 0: Dev Infrastructure

| Component | Status |
|-----------|--------|
| Project scaffold (Python 3.14, uv, typer CLI) | Done |
| Docker Compose stack (ParadeDB, Ollama, Mithril, cardano-node, Ogmios, PaddleOCR) | Done |
| Git submodules (6 repos: cardano-node, cardano-ledger, ouroboros-network, ouroboros-consensus, plutus, formal-ledger-specs) | Done |
| Database schema (7 tables, SQLModel + asyncpg) | Done |
| Spec ingestion pipeline (LaTeX/pandoc, CDDL, Markdown, Agda, PDF/PaddleOCR) | Done |
| Code indexing pipeline (tree-sitter-haskell, Agda parser, content-hash dedup) | Done |
| GitHub issues & PRs ingestion (GraphQL, full discussion threads) | Done |
| CLI commands (infra, ingest, db) | Done |
| Documentation (4-tab MkDocs site with SteelSwap branding) | Done |
| Search infrastructure (BM25 + vector + RRF fusion) | Not started |
| MCP integrations (Search MCP, CrystalDB MCP) | Not started |

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

# Start infrastructure
uv run vibe-node infra up

# Check status
uv run vibe-node infra status

# Ingest specs, code, and GitHub issues
uv run vibe-node ingest specs
uv run vibe-node ingest code --limit 1
uv run vibe-node ingest issues --limit 10

# Search the knowledge base
uv run vibe-node db search "Ouroboros Praos VRF"

# Run the node (not yet implemented)
uv run vibe-node serve
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

**Source code** (everything under `src/`, `tests/`, `infra/`, configuration files, CLI tooling, ingestion pipelines, etc.) is licensed under the GNU Affero General Public License v3.0.

**Database contents** (the populated knowledge base produced by the ingestion pipelines — spec extractions, cross-references, test specifications, embeddings, and all other derived data) are a separate work product licensed under the Creative Commons Attribution-ShareAlike 4.0 International License. If you redistribute or build upon the database contents, you must provide attribution and share under the same or a compatible license.

Relicensing of either component may be available on request. Contact SteelSwap for details.

&copy; 2026 SteelSwap
