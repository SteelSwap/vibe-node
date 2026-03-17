# vibe-node

A vibe-coded, spec-compliant Cardano node written in Python.

Built in response to [Pi Lanningham's open challenge](about/challenge.md) to vibe-code an alternative Cardano node from scratch. Every commit is public. Every prompt is visible. Every decision is documented.

## What is this?

**vibe-node** is a from-scratch Cardano node implementation in Python, built entirely through AI-assisted development ("vibe coding"). The entire development process — prompts, decisions, dead ends, and all — is documented in the git history and these docs.

This is not just a node. It's a public demonstration that AI-assisted development can produce spec-compliant, production-grade blockchain infrastructure.

## Current Status

!!! warning "Phase 0 — Development Architecture"
    Building the knowledge base and dev infrastructure. Spec ingestion, code indexing, and GitHub issue tracking are operational. Node implementation has not yet started.

## Quick Start

```bash
# Clone and install
git clone https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync

# Start infrastructure
uv run vibe-node infra up

# Run the node (not yet implemented)
uv run vibe-node serve
```

## Documentation

- **[About](about/index.md)** — The challenge, methodology, toolchain, and how we build
- **[Specifications](specs/index.md)** — Cardano specs and gap analysis
- **[Development](development/index.md)** — Roadmap, milestones, and progress
- **[Reference](reference/index.md)** — CLI, schema, architecture, and pipeline docs
