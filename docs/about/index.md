# About vibe-node

**vibe-node** is a from-scratch Cardano node written in Python, built entirely through AI-assisted development ("vibe coding") in response to Pi Lanningham's open challenge.

This isn't just a node. It's a public demonstration that AI-assisted development can produce spec-compliant, production-grade blockchain infrastructure — with every prompt visible, every decision documented, and every dead end on the record.

## What You'll Find Here

- **[The Challenge](challenge.md)** — Pi Lanningham's open challenge and what we're building to meet it
- **[How We Build](methodology.md)** — The vibe-coding philosophy and development cycle
- **[Toolchain](toolchain.md)** — Every tool we use, why we chose it, and how it fits together
- **[Agent Architecture](agents.md)** — Agent Millenial as orchestrator, worker agents, skills
- **[Coordination](coordination.md)** — How Plane tracks work items and how docs stay in sync

## Quick Start

```bash
git clone https://github.com/SteelSwap/vibe-node.git
cd vibe-node
uv sync
uv run vibe-node infra up    # Start Docker stack
uv run vibe-node serve        # Start the node (not yet implemented)
```
