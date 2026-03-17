# Phase 0, Wave 3 — Search Infrastructure & MCP

**Date:** 2026-03-15 — 2026-03-17
**Status:** Complete
**Milestones:** M0.6, M0.7

Wave 3 turned the ingested knowledge base into a queryable search layer. M0.6 added BM25 and HNSW indexes plus composable search templates. M0.7 exposed those templates as a six-tool FastMCP server and configured CrystalDB as a raw SQL escape hatch.

---

## M0.6 — Search & Index Infrastructure

**Work Items:** 5/5 complete

### What We Built

Full-text and semantic search across all 6 knowledge base tables, with results fused via Reciprocal Rank Fusion (RRF).

### Indexes

| Index Type | Extension | Tables | Notes |
|-----------|-----------|--------|-------|
| BM25 | pg_search (ParadeDB) | All 6 | DROP + CREATE pattern; run via `db create-indexes` |
| HNSW | pgvector | All 6 | `IF NOT EXISTS`; indexes the `embedding` column |

### Search Templates

Three composable templates in `src/vibe_node/ingest/config.py`:

```
bm25_search(table, query, limit)      → BM25 full-text ranked results
vector_search(table, embedding, limit) → HNSW approximate nearest neighbors
rrf_search(table, query, embedding, limit) → BM25 + vector fused via RRF
```

`search_all(query, embedding, limit)` runs `rrf_search` across all 6 tables and merges into a single ranked list.

### CLI Upgrade

`vibe-node db search` replaced ILIKE with the full RRF pipeline. The query is embedded via Ollama before being dispatched to `search_all`. `--table` now accepts the canonical table-type names (`spec_doc`, `code`, `issue`, `issue_comment`, `pr`, `pr_comment`, `all`).

`vibe-node db create-indexes` added as an explicit post-ingestion setup step.

### Database Size at Completion

| Table | Rows | Size |
|-------|------|------|
| code_chunks | ~45K | 19 GB (17 GB indexes) |
| spec_documents | ~2.8K | < 1 GB |
| github_issues | ~3.2K | < 1 GB |
| github_pull_requests | ~4.1K | < 1 GB |
| github_issue_comments | ~12.8K | < 1 GB |
| github_pr_comments | ~28.4K | < 1 GB |
| **Total** | | **~20 GB** |

`code_chunks` dominates due to per-function embeddings across dozens of release tags.

---

## M0.7 — Search MCP

**Work Items:** 6/6 complete

### What We Built

A FastMCP server that exposes the search layer to AI agents as structured, read-only tools. Agents can search by query, navigate by relationship, inspect entities, check spec coverage, and compare function implementations across Haskell releases.

### MCP Tools

| Tool | Description |
|------|-------------|
| `search` | BM25 + vector RRF across the knowledge base |
| `find_similar` | Vector neighbors for a known entity (by ID) |
| `get_related` | Traverse typed relationships from an entity |
| `coverage` | Which spec sections have implementation evidence |
| `get_entity` | Fetch full content for a known entity ID |
| `compare_versions` | Diff a function's implementation across release tags |

All 6 tools are read-only. No mutations to the knowledge base are exposed via MCP.

### Relationship Vocabulary

10-type vocabulary borrowed from W3C PROV-O, Dublin Core, SPDX, and OSLC RM:

| Relationship | Direction |
|-------------|-----------|
| `implements` | code → spec |
| `references` | any → any |
| `supersedes` | newer → older |
| `derives_from` | specialized → general |
| `tests` | test → implementation |
| `documents` | doc → implementation |
| `depends_on` | consumer → dependency |
| `related_to` | bidirectional |
| `part_of` | child → parent |
| `version_of` | tagged version → canonical |

Relationships are vector-proposed (search returns candidates) and agent-confirmed (agent decides if the relationship is meaningful). No explicit relationship table yet — Phase 1 will add one.

### Architecture

```
Agent / Claude Desktop
       │
       ▼ MCP (stdio)
src/vibe_node/mcp/search_server.py  (FastMCP)
       │
       ▼ asyncpg
src/vibe_node/db/pool.py  (shared connection pool)
       │
       ▼
ParadeDB (pg_search + pgvector)
```

The shared `db/pool.py` module is used by both the MCP server and the CLI, so connection settings are configured in one place.

### Phase 1 Table Handling

Several tables (`spec_relationships`, `implementation_evidence`) are planned for Phase 1 but do not exist yet. All 6 MCP tools handle missing tables gracefully — they return empty result sets rather than raising errors. This allows the MCP server to be deployed and used now without waiting for Phase 1 schema work.

### CrystalDB Integration

CrystalDB MCP is configured as a raw SQL escape hatch alongside the search MCP. When a structured tool is insufficient (debugging, schema inspection, ad-hoc analysis), agents can drop to direct SQL without leaving the MCP layer.

---

## Issues Encountered & Fixed

| Issue | Cause | Fix |
|-------|-------|-----|
| RRF query returned only (id, score) without title/preview | SELECT only from `rrf_scores` CTE, no JOIN back to source table | Added second query to fetch full rows by ranked IDs |
| Score column name mismatch | `build_rrf_query` produces `rrf_total`; calling code used `rrf_score` | Fixed all references to use the actual column name `rrf_total` |
| GitHub ingestion 504/connection drops on large repos | CIPs and formal-ledger-specs PRs trigger gateway timeouts | Added 5 retries with exponential backoff for HTTP 502/503/504 and `RemoteProtocolError` |
| Code indexing silently skipped partially-ingested tags | Completion check used `EXISTS (SELECT 1 FROM code_chunks WHERE repo=... AND tag=...)` — true even for partial runs | Added `code_tag_completion` table as an explicit completion marker; tag only skipped if a row exists in that table |
