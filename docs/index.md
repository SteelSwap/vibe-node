# vibe-node

A vibe-coded, spec-compliant Cardano node written in Python.

Built in response to [Pi Lanningham's open challenge](https://github.com/input-output-hk/cardano-node) to vibe-code an alternative Cardano node from scratch. Every commit is public. Every prompt is visible. Every decision is documented.

## What is this?

**vibe-node** is a from-scratch Cardano node implementation in Python, built entirely through AI-assisted development ("vibe coding"). The entire development process — prompts, decisions, dead ends, and all — is documented in the git history and these docs.

This is not just a node. It's a public demonstration that AI-assisted development can produce spec-compliant, production-grade blockchain infrastructure.

## Current Status

!!! warning "Early Development"
    vibe-node is in early development. Nothing works yet. The vibes, however, are immaculate.

## Quick Start

```bash
# Clone and install
git clone https://github.com/AstroSats/vibe-node.git
cd vibe-node
uv sync

# Run the node
uv run vibe-node serve
```

## Documentation

- **[Architecture](architecture/overview.md)** — How the node is structured and why
- **[Roadmap](roadmap/milestones.md)** — What's planned, what's done, and what's next
- **[Development Log](devlog/index.md)** — The journey, not just the destination
