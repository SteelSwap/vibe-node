# Phase 0 — Development Architecture

**Date:** 2026-03-14 — 2026-03-17
**Status:** Complete
**Version:** v0.0.0

Phase 0 built the entire development infrastructure: Docker stack, knowledge base, ingestion pipelines, search layer, MCP integration, and documentation. Three waves, each building on the previous.

---

## Wave 1 — Foundation

**Date:** 2026-03-14
**PRs:** #1, #2, #3, #5

Wave 1 laid every foundation this project stands on. Three modules, built in parallel, zero dependencies between them.

### M0.1 — Docker Compose Stack

The full development stack is a single `vibe-node infra up` away.

| Service | Image | Purpose |
|---------|-------|---------|
| ParadeDB | `paradedb/paradedb:latest-pg17` | Document DB with BM25 + pgvector |
| Ollama | `ollama/ollama:latest` | Embedding inference (Jina Code 1.5B) |
| Mithril | Custom Dockerfile | Snapshot downloader for preprod/mainnet |
| cardano-node | `ghcr.io/intersectmbo/cardano-node` | Haskell reference node |
| Ogmios | `cardanosolutions/ogmios` | JSON/WebSocket interface to node |

### M0.2 — Git Submodules & Database Schema

| Submodule | Tag | Purpose |
|-----------|-----|---------|
| `vendor/cardano-node` | 10.6.2 | Node source, release tags |
| `vendor/cardano-ledger` | release/1.19.0 | Ledger rules, formal specs, CDDL |
| `vendor/ouroboros-network` | ouroboros-network-0.22.6.0 | Networking, miniprotocols |
| `vendor/ouroboros-consensus` | ouroboros-consensus-0.11.0.0 | Consensus spec, storage |
| `vendor/plutus` | 1.59.0.0 | Plutus Core spec, cost models |
| `vendor/formal-ledger-specs` | conway-v1.0 | Conway Agda formal specs |

6 tables in ParadeDB with pgvector `vector(1536)` columns: `spec_documents`, `code_chunks`, `github_issues`, `github_issue_comments`, `github_pull_requests`, `github_pr_comments`.

### M0.9 — Documentation & CLAUDE.md

- MkDocs site with 4-tab structure (How It Works, About, Specifications, Development, Reference)
- SVG infographics for methodology docs, Mermaid for engineering docs
- CLAUDE.md with spec consultation discipline, gap analysis format, no-alternative-node rule
- GitHub Actions for docs deployment

---

## Wave 2 — Ingestion & CLI

**Date:** 2026-03-14 — 2026-03-15
**PRs:** #4, #6, #7

Wave 2 built the three ingestion pipelines and full CLI.

### M0.3 — Spec Ingestion Pipeline

Converts Cardano specs from 5 formats across 6 submodules into chunked, embedded, searchable documents.

| Format | Converter | Source |
|--------|-----------|--------|
| Markdown | Direct passthrough | Consensus design docs, CIPs |
| CDDL | Chunk by rule definition | Binary schemas per era |
| LaTeX | pandoc with `--katex` | Formal specs (Shelley, Byron, Alonzo, network) |
| Literate Agda | Custom extractor | Conway/Dijkstra specs |
| PDF | pymupdf4llm | Ouroboros academic papers |

Features: hierarchical titles, reading order linked list, embed context prefixes, version tracking via git history, conversion cache.

### M0.4 — Code Indexing Pipeline

Walks release tags across 6 submodules, parses Haskell/Agda source with tree-sitter, embeds function-level chunks. Extracts 12 declaration types, groups multi-equation functions, infers Cardano era from module paths. Content-hash dedup avoids re-embedding unchanged functions across tags.

### M0.5 — Issues & PRs Ingestion

GraphQL-based GitHub ingestion (~100x fewer API calls than REST). Fetches issues, PRs, and all discussion threads including line-level review comments. Covers 7 repos: cardano-node, cardano-ledger, ouroboros-network, ouroboros-consensus, plutus, formal-ledger-specifications, CIPs.

### M0.8 — CLI Commands

| Command | Description |
|---------|-------------|
| `vibe-node serve` | Start the node (stub) |
| `vibe-node infra up/down/status/logs` | Docker Compose management |
| `vibe-node ingest issues/specs/code` | Ingestion pipelines |
| `vibe-node db status/reset/snapshot/restore/search` | Database management |
| `vibe-node db create-indexes` | BM25 + HNSW index creation |

---

## Wave 3 — Search Infrastructure & MCP

**Date:** 2026-03-15 — 2026-03-17
**Milestones:** M0.6, M0.7

Wave 3 turned the ingested knowledge base into a queryable search layer.

### M0.6 — Search & Index Infrastructure

BM25 (pg_search) and HNSW (pgvector) indexes across all 6 tables. Three composable search templates: `bm25_search`, `vector_search`, `rrf_search` (Reciprocal Rank Fusion). `search_all` runs RRF across all tables and merges into a single ranked list.

| Table | Rows | Size |
|-------|------|------|
| code_chunks | ~45K | 19 GB (17 GB indexes) |
| spec_documents | ~2.8K | < 1 GB |
| github_issues/PRs/comments | ~48.5K | < 3 GB |
| **Total** | | **~20 GB** |

### M0.7 — Search MCP

FastMCP server with 6 read-only tools:

| Tool | Description |
|------|-------------|
| `search` | BM25 + vector RRF across the knowledge base |
| `find_similar` | Vector neighbors for a known entity |
| `get_related` | Traverse typed relationships |
| `coverage` | Spec sections with implementation evidence |
| `get_entity` | Fetch full content by ID |
| `compare_versions` | Diff a function across release tags |

10-type relationship vocabulary (implements, references, supersedes, derives_from, tests, documents, depends_on, related_to, part_of, version_of). CrystalDB MCP configured as raw SQL escape hatch.

---

## Issues Encountered & Fixed

| Issue | Cause | Fix |
|-------|-------|-----|
| ParadeDB `latest` pulls PG18 | Breaking volume mount paths | Pinned to `latest-pg17` |
| Ollama GPU not available in Docker on Mac | Docker Desktop runs Linux VM | Accepted CPU-only |
| Mithril download path mismatch | `/data/db/db/` vs `/data/db` | Download to `/data` |
| PaddleOCR Python 3.14 incompatible | No 3.14 wheels | Docker sidecar with 3.13 |
| pandoc HTML math wrappers | Default wraps in `<span>` | `--katex`, `--to=markdown-raw_html` |
| tree-sitter `declarations` wrapper | Functions inside wrapper node | Unwrap before iterating |
| Code duplicate rows on line shifts | Unique constraint on `line_start` | Changed to `content_hash` |
| GitHub ingestion 504/timeouts | Large repos trigger gateway errors | 5 retries + exponential backoff |
| RRF query missing titles | SELECT only from CTE, no JOIN | Added fetch by ranked IDs |
| Embedding ReadTimeout | CPU Ollama slow on large chunks | 300s timeout + 2 retries |
