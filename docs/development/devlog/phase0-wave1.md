# Phase 0, Wave 1 — Foundation

**Date:** 2026-03-14
**Status:** Complete
**PRs:** #1, #2, #3, #5

Wave 1 laid every foundation this project stands on. Three modules, built in parallel, zero dependencies between them.

---

## M0.1 — Docker Compose Stack

**PR:** #1 (`m0.1-docker-compose`)
**Work Items:** 7/7 complete

The full development stack is a single `vibe-node infra up` away.

### Services

| Service | Image | Purpose |
|---------|-------|---------|
| ParadeDB | `paradedb/paradedb:latest-pg17` | Document DB with BM25 + pgvector |
| Ollama | `ollama/ollama:latest` | Embedding inference (Jina Code 1.5B) |
| Mithril | Custom Dockerfile | Snapshot downloader for preprod/mainnet |
| cardano-node | `ghcr.io/intersectmbo/cardano-node` | Haskell reference node |
| Ogmios | `cardanosolutions/ogmios` | JSON/WebSocket interface to node |

### Issues Encountered

- **ParadeDB `latest` pulls PG18**, which has breaking volume mount path changes. Pinned to `latest-pg17`.
- **vLLM replaced with Ollama.** vLLM Docker images are Linux/NVIDIA CUDA only — no Mac M-series support. Ollama works everywhere via Metal/NVIDIA/CPU.
- **Ollama GPU not available in Docker on Mac.** Docker Desktop runs a Linux VM with no Metal access. Accepted CPU-only for reproducibility over speed.
- **Community embedding model replaced with official Jina 1.5B GGUF** from HuggingFace, with SHA256 digest verification on every pull.
- **Mithril needed ancillary verification key** for the `--include-ancillary` flag. Ed25519 signature verification failed without it.
- **Mithril download path mismatch.** `--download-dir /data/db` creates `/data/db/db/`, but cardano-node expects `--database-path /data/db`. Fixed by downloading to `/data`.
- **cardano-node socket at `/ipc/node.socket`**, not `/data/node.socket`. Added separate `cardano-node-ipc` shared volume.
- **Ogmios needs `--node-config`** pointing to config.json, but the official image stores it in nix store paths that change per version. Added `cardano-config` init container that fetches config from `book.play.dev.cardano.org`.
- **Mithril fails on re-run** if download directory is not empty. Added entrypoint wrapper that skips download when data exists.

---

## M0.2 — Git Submodules & Database Schema

**PR:** #2 (`m0.2-submodules-schema`), #5 (`m0.2-additional-submodules`)
**Work Items:** 13/13 complete (including 3 additional submodules added for Wave 2)

### Submodules

| Submodule | Tag | Purpose |
|-----------|-----|---------|
| `vendor/cardano-node` | 10.6.2 | Node source, release tags |
| `vendor/cardano-ledger` | release/1.19.0 | Ledger rules, formal specs, CDDL |
| `vendor/ouroboros-network` | ouroboros-network-0.22.6.0 | Networking, miniprotocols |
| `vendor/ouroboros-consensus` | ouroboros-consensus-0.11.0.0 | Consensus spec, storage |
| `vendor/plutus` | 1.59.0.0 | Plutus Core spec, cost models |
| `vendor/formal-ledger-specs` | conway-v1.0 | Conway Agda formal specs |

### Database Schema

6 tables in ParadeDB with pgvector `vector(1536)` columns:

- `spec_documents` — converted spec content with hierarchical titles and version tracking
- `code_chunks` — function-level Haskell/Agda source per release tag
- `github_issues` — issues with full discussion threads
- `github_issue_comments` — individual comments for fine-grained search
- `github_pull_requests` — PRs with review discussions
- `github_pr_comments` — general, review, and line-level review comments

### Issues Encountered

- **Tag naming conventions vary wildly** across repos. cardano-node uses bare semver, cardano-ledger uses package-prefixed tags, ouroboros uses per-package tags. Each repo needs its own tag filter regex.
- **SQLModel/asyncpg type mismatch** with PostgreSQL ARRAY and vector columns. Switched to raw SQL inserts to avoid type issues.

---

## M0.9 — Documentation & CLAUDE.md

**PR:** #3 (`m0.9-documentation`)
**Work Items:** 9/9 complete

### Deliverables

- **How We Build section** — 5 pages: methodology, toolchain, agent architecture, coordination, workflow
- **Gap Analysis methodology page** — spec as ideal, code as reality, gap as measured delta
- **SVG infographics** — 5 custom SVGs with SteelSwap brand palette for methodology docs
- **mkdocs.yml** — full navigation, pymdownx.arithmatex for math rendering, MathJax
- **CLAUDE.md** — spec consultation discipline, gap analysis entry format, no-alternative-node-implementations rule
- **README.md** — Phase 0 status dashboard with shields
- **GitHub Actions** — docs deploy workflow for GitHub Pages

### Design Decisions

- **SVG infographics for methodology docs** (public-facing), **Mermaid diagrams for engineering docs** (developer-facing). Dual-audience approach.
- **CLAUDE.md includes hard prohibition** on referencing alternative node implementations (Amaru, Dingo, Dolos). Only published specs and the Haskell node are permitted sources.
