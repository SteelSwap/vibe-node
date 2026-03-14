# vibe-node

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![Built with AI](https://img.shields.io/badge/built%20with-AI%20%28vibe%20coded%29-ff6d00.svg)]()
[![Cardano](https://img.shields.io/badge/Cardano-node-0033AD.svg)](https://cardano.org)

A vibe-coded, spec-compliant Cardano node written in Python.

---

## What is this?

**vibe-node** is a from-scratch Cardano node built entirely through AI-assisted development in response to [Pi Lanningham's open challenge](https://x.com/Quantumplation). Every commit is public. Every prompt is visible. Every decision is documented.

This is not just a node — it's a public education in vibe coding with extreme precision.

## Current Status

> **Early Development** — Project scaffolding and tooling. Nothing runs on-chain yet.

| Component | Status |
|-----------|--------|
| Project structure | Done |
| CLI (`vibe-node serve`) | Stubbed |
| Networking / Multiplexer | Not started |
| Chain Sync | Not started |
| Block Fetch | Not started |
| Ledger Validation | Not started |
| Consensus (Ouroboros Praos) | Not started |
| Block Production | Not started |
| Node-to-Client protocols | Not started |

## Quick Start

```bash
git clone https://github.com/AstroSats/vibe-node.git
cd vibe-node
uv sync
uv run vibe-node serve
```

## Documentation

Full documentation is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) and available in the `docs/` directory:

```bash
uv run mkdocs serve
```

- **Architecture** — How the node is structured and why
- **Roadmap** — Milestones, priorities, and progress
- **Development Log** — The journey, including dead ends and lessons learned

## License

[AGPL-3.0](LICENSE)
