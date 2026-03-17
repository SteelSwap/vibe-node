# M0.6 + M0.7: Search Infrastructure & MCP — Design Spec

**Goal:** Build BM25 and HNSW indexes on all knowledge base tables, implement composable search templates (BM25, vector, RRF fusion), and deploy a 6-tool read-only Search MCP plus CrystalDB MCP for raw SQL access.

**Architecture:** Three composable query templates in a shared Python module (`src/vibe_node/db/search.py`), used by both the MCP server and CLI. Per-table BM25 indexes via pg_search, HNSW vector indexes via pgvector, RRF fusion via SQL CTEs.

**Assumes:** All ingestion pipelines complete (spec_documents, code_chunks, github_issues/PRs populated with embeddings).

---

## M0.6: Search & Index Infrastructure

### BM25 Indexes (pg_search)

One BM25 index per table covering all searchable text columns. Uses `CREATE INDEX USING bm25` with `key_field` set to the primary key. Include filter columns (era, repo, subsystem) for index pushdown.

| Table | BM25 Columns | Filter Columns (pushdown) |
|-------|-------------|--------------------------|
| spec_documents | content_plain, document_title, section_title, subsection_title | era, source_repo, chunk_type |
| code_chunks | content, embed_text, function_name, module_name | era, repo, release_tag |
| github_issues | content_combined, title | repo, state |
| github_issue_comments | body | repo |
| github_pull_requests | content_combined, title | repo, state |
| github_pr_comments | body | repo |

**Phase 1 tables** (`spec_sections`, `cross_references`, `test_specifications`, `gap_analysis`) do not exist yet. They will be created during Phase 1 (M1.3). The search templates and MCP tools must handle missing tables gracefully — check if the table exists before querying, return empty results if not. This means:
- `search` and `find_similar` skip non-existent tables when searching across all entity types
- `get_related` and `coverage` return empty results until `cross_references` / `spec_sections` are created
- Indexes for Phase 1 tables will be created as part of M1.3 when the tables are added

**Tokenizer:** `pdb.simple('stemmer=english')` for prose columns (spec content, issue bodies). `pdb.source_code` for code columns (code_chunks.content). `pdb.literal` for filter columns.

### HNSW Vector Indexes (pgvector)

One HNSW index per embedding column using cosine distance.

```sql
CREATE INDEX idx_<table>_embedding ON <table>
USING hnsw (embedding vector_cosine_ops);
```

Applied to all 6 tables with embedding columns (spec_documents, code_chunks, github_issues, github_issue_comments, github_pull_requests, github_pr_comments).

### Composable Search Templates

Three query templates in `src/vibe_node/db/search.py`:

#### BM25 Template

```python
async def search_bm25(
    conn,
    query: str,
    table: str,
    text_column: str,
    filters: dict | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """BM25 keyword search on a single table.
    Returns (results, total_count).
    """
```

Uses pg_search `|||` operator with `pdb.score()` for ranking. Filter columns pushed into the BM25 index scan. Returns results with BM25 score.

#### Vector Template

```python
async def search_vector(
    conn,
    embedding: list[float],
    table: str,
    filters: dict | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Vector similarity search on a single table.
    Returns (results, total_count).
    """
```

Uses pgvector `<=>` operator (cosine distance) with HNSW index. Returns results with similarity score (1 - distance).

#### RRF Template

```python
async def search_rrf(
    conn,
    query: str,
    embedding: list[float],
    table: str,
    text_column: str,
    filters: dict | None = None,
    limit: int = 10,
    offset: int = 0,
    k: int = 60,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> tuple[list[dict], int]:
    """RRF fusion combining BM25 + vector search on a single table.
    Returns (results, total_count).
    """
```

Composes BM25 and vector CTEs, fuses scores with configurable k-parameter and weights:

```sql
WITH
bm25 AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY pdb.score(id) DESC) AS rank
  FROM {table}
  WHERE {text_column} ||| :query
    AND (:era IS NULL OR era = :era)          -- filter pushdown
    AND (:repo IS NULL OR repo = :repo)       -- filter pushdown
  LIMIT :fetch_limit
),
vector AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> :embedding) AS rank
  FROM {table}
  WHERE (:era IS NULL OR era = :era)          -- same filters applied
    AND (:repo IS NULL OR repo = :repo)
  LIMIT :fetch_limit
),
rrf AS (
  SELECT id, :bm25_weight * 1.0 / (:k + rank) AS score FROM bm25
  UNION ALL
  SELECT id, :vector_weight * 1.0 / (:k + rank) AS score FROM vector
)
-- GROUP BY d.id is valid because id is the PK (functional dependency)
SELECT d.*, SUM(rrf.score) AS rrf_score
FROM rrf JOIN {table} d USING (id)
GROUP BY d.id
ORDER BY rrf_score DESC
LIMIT :limit OFFSET :offset
```

**`total_count` semantics:** For single-table queries, `total_count` is the number of unique IDs in the fused result set (before LIMIT/OFFSET). Computed via a window function `COUNT(*) OVER ()` on the grouped results. For cross-table `search_all`, `total_count` is the sum of per-table counts. This is an approximation — exact cross-table count would require materializing all results, which is too expensive.

#### Cross-Table Search

```python
async def search_all(
    conn,
    query: str,
    embedding: list[float],
    entity_type: str | None = None,
    filters: dict | None = None,
    limit: int = 10,
    offset: int = 0,
    k: int = 60,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> tuple[list[dict], int]:
    """Search across all tables (or a single entity type) using RRF.
    Returns unified results with entity_type, content_preview, and scores.
    """
```

When `entity_type` is None, runs RRF on each table, merges results, re-ranks by RRF score. When specified, runs RRF on just that table.

### Table-to-Search Configuration

A registry mapping entity types to their table, text columns, and preview fields:

```python
SEARCH_CONFIG = {
    "spec": {
        "table": "spec_documents",
        "text_column": "content_plain",
        "preview_column": "content_plain",
        "title_column": "document_title",
        "filter_columns": {"era": "era", "repo": "source_repo"},
    },
    "code": {
        "table": "code_chunks",
        "text_column": "embed_text",
        "preview_column": "content",
        "title_column": "function_name",
        "filter_columns": {"era": "era", "repo": "repo", "release_tag": "release_tag"},
    },
    "issue": {
        "table": "github_issues",
        "text_column": "content_combined",
        "preview_column": "content_combined",
        "title_column": "title",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "issue_comment": {
        "table": "github_issue_comments",
        "text_column": "body",
        "preview_column": "body",
        "title_column": None,
        "filter_columns": {"repo": "repo"},
    },
    "pr": {
        "table": "github_pull_requests",
        "text_column": "content_combined",
        "preview_column": "content_combined",
        "title_column": "title",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "pr_comment": {
        "table": "github_pr_comments",
        "text_column": "body",
        "preview_column": "body",
        "title_column": None,
        "filter_columns": {"repo": "repo"},
    },
    # Phase 1 tables — added when created in M1.3:
    # "spec_section": { "table": "spec_sections", ... },
    # "gap": { "table": "gap_analysis", ... },
}
```

Extended in Phase 1 with `spec_section` and `gap_analysis` entries.

### Smoke Tests

After index creation, run validation queries:

1. BM25 search returns results for known terms ("UTxO", "applyBlock", "chain-sync") on each table
2. Vector search: embed "UTxO validation rules" via Ollama, search spec_documents — verify top results are relevant
3. RRF fusion: same query, verify results from both BM25 and vector appear in fused output
4. Filter pushdown: search with `era=shelley` returns only Shelley-era results
5. Cross-table search: query without entity_type returns results from specs, code, and issues
6. Verify embedding dimension matches column definition (1536)
7. All queries complete within reasonable time (<1s for BM25, <2s for vector, <3s for RRF)

Report: row counts per table, index sizes, sample query latencies.

### CLI Upgrade

Upgrade `vibe-node db search` from ILIKE to use the RRF template. Keep the same interface but use proper BM25 + vector search under the hood.

---

## M0.7: Search MCP

Fully specified in `docs/superpowers/specs/2026-03-16-search-mcp-design.md`. Key implementation details:

### Server Architecture

```
src/vibe_node/mcp/
├── __init__.py
├── search_server.py    # MCP server entry point, tool registration
├── db.py               # asyncpg connection pool
├── embed.py            # Query embedding via Ollama
└── tools/
    ├── __init__.py
    ├── search.py        # search tool — uses search_all() from db/search.py
    ├── similar.py       # find_similar — uses search_vector()
    ├── related.py       # get_related — queries cross_references
    ├── coverage.py      # coverage — aggregate spec_sections queries
    ├── entity.py        # get_entity — single entity + relationships
    └── versions.py      # compare_versions — code_tag_manifest diffs
```

Each tool is a standalone module with a single `async def handle(params) -> dict` function. The server registers all tools and routes calls.

### Shared Dependencies

- `src/vibe_node/db/search.py` — The three search templates (BM25, vector, RRF) + cross-table search
- `src/vibe_node/db/xref.py` — Cross-reference queries (used by get_related, coverage)
- `src/vibe_node/embed/client.py` — Ollama embedding client (used by search, find_similar)

### MCP Registration

```json
{
  "mcpServers": {
    "vibe-search": {
      "command": "uv",
      "args": ["run", "python", "-m", "vibe_node.mcp.search_server"],
      "env": {
        "DATABASE_URL": "postgresql://vibenode:vibenode@localhost:5432/vibenode",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "EMBEDDING_MODEL": "hf.co/jinaai/jina-code-embeddings-1.5b-GGUF:Q8_0"
      }
    },
    "crystaldb": {
      "command": "npx",
      "args": ["-y", "@crystaldb/mcp", "--connection-string", "postgresql://vibenode:vibenode@localhost:5432/vibenode"]
    }
  }
}
```

### CrystalDB MCP

No code to write — just configure the connection string in `.mcp.json`. CrystalDB provides raw SQL read access as the escape hatch for queries the Search MCP doesn't cover.

---

## Module Breakdown

### M0.6 Issues (6)

1. Create BM25 indexes on all tables
2. Create HNSW vector indexes on all tables
3. Implement BM25 search template
4. Implement vector search template
5. Implement RRF fusion template + cross-table search
6. Smoke tests + upgrade CLI db search

### M0.7 Issues (8)

1. Build Search MCP server with search + find_similar tools
2. Implement get_related tool
3. Implement coverage tool
4. Implement get_entity tool
5. Implement compare_versions tool
6. Configure CrystalDB MCP
7. Add MCPs to .mcp.json and test all 6 tools E2E
8. Document M0.7: tools, ontology, usage patterns

### Dependencies

```
M0.6 BM25 indexes ──┐
M0.6 HNSW indexes ──┼── M0.6 search templates ── M0.6 smoke tests
                     │                                    │
                     └── M0.7 search + find_similar ──────┤
                         M0.7 get_related ────────────────┤
                         M0.7 coverage ───────────────────┤
                         M0.7 get_entity ─────────────────┤
                         M0.7 compare_versions ───────────┤
                         M0.7 CrystalDB config ───────────┤
                                                          │
                                               M0.7 E2E tests
                                               M0.7 documentation
```
