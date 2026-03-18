# vibe-node

A vibe-coded, spec-compliant Cardano node written in Python.

Built in response to [Pi Lanningham's open challenge](about/challenge.md) to vibe-code an alternative Cardano node from scratch. Every commit is public. Every prompt is visible. Every decision is documented.

## What is this?

**vibe-node** is a from-scratch Cardano node implementation in Python, built entirely through AI-assisted development ("vibe coding"). The entire development process — prompts, decisions, dead ends, and all — is documented in the git history and these docs.

This is not just a node. It's a public demonstration that AI-assisted development can produce spec-compliant, production-grade blockchain infrastructure.

## Current Status

!!! success "Phase 0 — Development Architecture: COMPLETE"
    The knowledge base, search infrastructure, MCP integrations, CLI, and documentation are all operational. **Phase 1 — Research & Analysis** is next, followed by node implementation in Phase 2.

| Component | Status |
|-----------|--------|
| Docker Compose Stack (ParadeDB, Ollama, Mithril, cardano-node, Ogmios, PaddleOCR) | :material-check-circle: Complete |
| Spec Ingestion (LaTeX, Markdown, CDDL, Literate Agda, PDF) | :material-check-circle: Complete |
| Code Indexing (tree-sitter Haskell + Agda, versioned by release tag) | :material-check-circle: Complete |
| GitHub Ingestion (Issues, PRs, comments from 7 repos) | :material-check-circle: Complete |
| Search Infrastructure (BM25 + HNSW, RRF fusion) | :material-check-circle: Complete |
| Search MCP (6 tools) + CrystalDB MCP | :material-check-circle: Complete |
| CLI (infra, ingest, db subcommands) | :material-check-circle: Complete |
| Node Implementation | :material-clock-outline: Phase 2+ |

## Quick Start

```bash
# Clone and install
git clone https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync

# Start infrastructure
uv run vibe-node infra up

# Ingest the knowledge base
uv run vibe-node ingest specs
uv run vibe-node ingest code --limit 1
uv run vibe-node ingest issues --limit 10

# Search
uv run vibe-node db search "Ouroboros Praos VRF"
```

## Documentation

- **[About](about/index.md)** — The challenge, methodology, toolchain, and how we build
- **[Specifications](specs/index.md)** — Cardano specs and gap analysis
- **[Development](development/index.md)** — Roadmap, milestones, and progress
- **[Reference](reference/index.md)** — CLI, schema, architecture, and pipeline docs
