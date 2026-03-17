# M0.6 + M0.7: Search Infrastructure & MCP — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build BM25 and HNSW indexes on all knowledge base tables, implement composable search templates (BM25, vector, RRF), deploy a 6-tool read-only Search MCP, and configure CrystalDB MCP for raw SQL access.

**Architecture:** Three composable query templates in `src/vibe_node/db/search.py` (BM25, vector, RRF), used by both MCP and CLI. Per-table BM25 indexes via pg_search, HNSW indexes via pgvector. MCP server in `src/vibe_node/mcp/` with 6 read-only tools. Phase 1 tables (spec_sections, cross_references, gap_analysis) handled gracefully when missing.

**Tech Stack:** ParadeDB pg_search (BM25), pgvector (HNSW), asyncpg, Python MCP SDK, Ollama (query embedding), Typer (CLI)

**Spec:** `docs/superpowers/specs/2026-03-17-m06-m07-search-infrastructure-design.md`
**MCP Spec:** `docs/superpowers/specs/2026-03-16-search-mcp-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `src/vibe_node/db/search.py` | Composable search templates: BM25, vector, RRF, cross-table |
| `src/vibe_node/db/search_config.py` | SEARCH_CONFIG registry mapping entity types to tables/columns |
| `src/vibe_node/mcp/__init__.py` | MCP package init |
| `src/vibe_node/mcp/search_server.py` | MCP server entry point, tool registration |
| `src/vibe_node/db/pool.py` | Shared asyncpg connection pool (used by MCP and CLI) |
| `src/vibe_node/mcp/db.py` | Re-exports shared pool for MCP convenience |
| `src/vibe_node/mcp/embed.py` | Query embedding via Ollama for MCP |
| `src/vibe_node/mcp/tools/__init__.py` | Tools package init |
| `src/vibe_node/mcp/tools/search.py` | search tool |
| `src/vibe_node/mcp/tools/similar.py` | find_similar tool |
| `src/vibe_node/mcp/tools/related.py` | get_related tool |
| `src/vibe_node/mcp/tools/coverage.py` | coverage tool |
| `src/vibe_node/mcp/tools/entity.py` | get_entity tool |
| `src/vibe_node/mcp/tools/versions.py` | compare_versions tool |
| `infra/db/create_indexes.sql` | BM25 + HNSW index creation SQL |
| `tests/test_search.py` | Tests for search templates |
| `tests/test_mcp_tools.py` | Tests for MCP tool handlers |
| `.mcp.json` | MCP server registration |

### Modified Files

| File | Changes |
|------|---------|
| `infra/db/init.sql` | Add index creation SQL at end |
| `src/vibe_node/cli.py` | Add `db create-indexes` command |
| `src/vibe_node/cli_infra.py` | Upgrade `db search` to use RRF |

---

## Chunk 1: M0.6 — Search & Index Infrastructure

### Task 1: Create BM25 and HNSW indexes

**Files:**
- Create: `infra/db/create_indexes.sql`
- Modify: `infra/db/init.sql`
- Modify: `src/vibe_node/cli.py`

- [ ] **Step 1: Write the index creation SQL**

Create `infra/db/create_indexes.sql`:

```sql
-- =============================================================================
-- BM25 + HNSW index creation for vibe-node knowledge base
-- Run after data ingestion: vibe-node db create-indexes
-- Idempotent: DROP IF EXISTS before CREATE
-- =============================================================================

-- ---------------------------------------------------------------------------
-- BM25 Indexes (pg_search)
-- One per table, covering text + filter columns for pushdown
-- ---------------------------------------------------------------------------

-- spec_documents: prose search with English stemming
DROP INDEX IF EXISTS idx_spec_documents_bm25;
CREATE INDEX idx_spec_documents_bm25 ON spec_documents
USING bm25 (id, content_plain, document_title, section_title, subsection_title, era, source_repo, chunk_type)
WITH (key_field='id');

-- code_chunks: code search with source_code tokenizer for content
DROP INDEX IF EXISTS idx_code_chunks_bm25;
CREATE INDEX idx_code_chunks_bm25 ON code_chunks
USING bm25 (id, content, embed_text, function_name, module_name, era, repo, release_tag)
WITH (key_field='id');

-- github_issues: discussion search
DROP INDEX IF EXISTS idx_github_issues_bm25;
CREATE INDEX idx_github_issues_bm25 ON github_issues
USING bm25 (id, content_combined, title, repo, state)
WITH (key_field='id');

-- github_issue_comments: comment-level search
DROP INDEX IF EXISTS idx_github_issue_comments_bm25;
CREATE INDEX idx_github_issue_comments_bm25 ON github_issue_comments
USING bm25 (id, body, repo)
WITH (key_field='id');

-- github_pull_requests: PR search
DROP INDEX IF EXISTS idx_github_pull_requests_bm25;
CREATE INDEX idx_github_pull_requests_bm25 ON github_pull_requests
USING bm25 (id, content_combined, title, repo, state)
WITH (key_field='id');

-- github_pr_comments: PR comment search
DROP INDEX IF EXISTS idx_github_pr_comments_bm25;
CREATE INDEX idx_github_pr_comments_bm25 ON github_pr_comments
USING bm25 (id, body, repo)
WITH (key_field='id');

-- ---------------------------------------------------------------------------
-- HNSW Vector Indexes (pgvector)
-- Cosine distance for embedding similarity
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_spec_documents_hnsw ON spec_documents
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_code_chunks_hnsw ON code_chunks
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_github_issues_hnsw ON github_issues
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_github_issue_comments_hnsw ON github_issue_comments
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_github_pull_requests_hnsw ON github_pull_requests
USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_github_pr_comments_hnsw ON github_pr_comments
USING hnsw (embedding vector_cosine_ops);
```

- [ ] **Step 2: Add CLI command to create indexes**

Add to `src/vibe_node/cli.py`:

```python
@db_app.command(name="create-indexes")
def create_indexes() -> None:
    """Create BM25 and HNSW indexes on all tables.

    Run after initial data ingestion. Safe to re-run (drops and recreates BM25,
    HNSW uses IF NOT EXISTS).
    """
    import subprocess
    from pathlib import Path

    sql_path = Path(__file__).resolve().parents[2] / "infra" / "db" / "create_indexes.sql"
    if not sql_path.exists():
        typer.echo(f"Index SQL not found: {sql_path}", err=True)
        raise typer.Exit(1)

    typer.echo("Creating BM25 and HNSW indexes (this may take a few minutes)...")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "paradedb",
         "psql", "-U", "vibenode", "-d", "vibenode", "-f", "/dev/stdin"],
        input=sql_path.read_text(),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error creating indexes:\n{result.stderr}", err=True)
        raise typer.Exit(1)
    typer.echo("Indexes created successfully.")
    typer.echo(result.stdout)
```

- [ ] **Step 3: Run index creation and verify**

```bash
uv run vibe-node db create-indexes
```

Expected: BM25 and HNSW indexes created on all 6 tables. Verify with:

```bash
docker compose exec paradedb psql -U vibenode -d vibenode -c "\di+ idx_*_bm25"
docker compose exec paradedb psql -U vibenode -d vibenode -c "\di+ idx_*_hnsw"
```

- [ ] **Step 4: Commit**

```bash
git add infra/db/create_indexes.sql src/vibe_node/cli.py
git commit -m "feat(m0.6): create BM25 and HNSW indexes on all knowledge base tables

Prompt: Create pg_search BM25 indexes (text + filter columns with pushdown)
and pgvector HNSW indexes (cosine distance) on all 6 tables. Add CLI command
vibe-node db create-indexes.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 2: Implement search config registry

**Files:**
- Create: `src/vibe_node/db/search_config.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_search.py`:

```python
"""Tests for search templates and configuration."""
import pytest


def test_search_config_has_all_entity_types():
    from vibe_node.db.search_config import SEARCH_CONFIG
    required = {"spec_doc", "code", "issue", "issue_comment", "pr", "pr_comment"}
    assert required.issubset(set(SEARCH_CONFIG.keys()))


def test_search_config_entries_have_required_fields():
    from vibe_node.db.search_config import SEARCH_CONFIG
    for name, cfg in SEARCH_CONFIG.items():
        assert "table" in cfg, f"{name} missing 'table'"
        assert "text_column" in cfg, f"{name} missing 'text_column'"
        assert "preview_column" in cfg, f"{name} missing 'preview_column'"
        assert "filter_columns" in cfg, f"{name} missing 'filter_columns'"


def test_search_config_table_exists_check():
    from vibe_node.db.search_config import SEARCH_CONFIG, get_available_configs
    # get_available_configs should return only configs for tables that exist
    # Without a DB connection, just verify the function signature exists
    assert callable(get_available_configs)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_search.py -v
```

Expected: FAIL with ImportError

- [ ] **Step 3: Implement search config**

Create `src/vibe_node/db/search_config.py`:

```python
"""Search configuration registry.

Maps entity types to their database tables, searchable columns,
and filter columns. Used by search templates and MCP tools.
"""

SEARCH_CONFIG: dict[str, dict] = {
    # Key is "spec_doc" to match the MCP spec; "spec" is reserved for
    # Phase 1's spec_sections table.
    "spec_doc": {
        "table": "spec_documents",
        "text_column": "content_plain",
        "bm25_columns": ["content_plain", "document_title", "section_title", "subsection_title"],
        "preview_column": "content_plain",
        "title_column": "document_title",
        "id_column": "id",
        "filter_columns": {"era": "era", "repo": "source_repo"},
    },
    "code": {
        "table": "code_chunks",
        "text_column": "embed_text",
        "bm25_columns": ["content", "embed_text", "function_name", "module_name"],
        "preview_column": "content",
        "title_column": "function_name",
        "id_column": "id",
        "filter_columns": {"era": "era", "repo": "repo", "release_tag": "release_tag"},
    },
    "issue": {
        "table": "github_issues",
        "text_column": "content_combined",
        "bm25_columns": ["content_combined", "title"],
        "preview_column": "content_combined",
        "title_column": "title",
        "id_column": "id",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "issue_comment": {
        "table": "github_issue_comments",
        "text_column": "body",
        "bm25_columns": ["body"],
        "preview_column": "body",
        "title_column": None,
        "id_column": "id",
        "filter_columns": {"repo": "repo"},
    },
    "pr": {
        "table": "github_pull_requests",
        "text_column": "content_combined",
        "bm25_columns": ["content_combined", "title"],
        "preview_column": "content_combined",
        "title_column": "title",
        "id_column": "id",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "pr_comment": {
        "table": "github_pr_comments",
        "text_column": "body",
        "bm25_columns": ["body"],
        "preview_column": "body",
        "title_column": None,
        "id_column": "id",
        "filter_columns": {"repo": "repo"},
    },
}

# Phase 1 configs — uncomment when tables are created in M1.3:
# "spec_section": {
#     "table": "spec_sections",
#     "text_column": "extracted_rule",
#     "bm25_columns": ["extracted_rule", "verbatim", "title"],
#     "preview_column": "extracted_rule",
#     "title_column": "title",
#     "id_column": "id",
#     "filter_columns": {"era": "era", "subsystem": "subsystem"},
# },
# "gap": {
#     "table": "gap_analysis",
#     "text_column": "delta",
#     "bm25_columns": ["delta", "spec_says", "haskell_does", "implications"],
#     "preview_column": "delta",
#     "title_column": None,
#     "id_column": "id",
#     "filter_columns": {"era": "era", "subsystem": "subsystem"},
# },


async def get_available_configs(conn) -> dict[str, dict]:
    """Return only configs whose tables exist in the database.

    Handles Phase 1 tables gracefully — if spec_sections or gap_analysis
    don't exist yet, they're simply omitted.
    """
    result = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing_tables = {row["tablename"] for row in result}
    return {
        name: cfg for name, cfg in SEARCH_CONFIG.items()
        if cfg["table"] in existing_tables
    }
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_search.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/vibe_node/db/search_config.py tests/test_search.py
git commit -m "feat(m0.6): search config registry mapping entity types to tables

Prompt: Create SEARCH_CONFIG registry with 6 entity types (spec_doc, code,
issue, issue_comment, pr, pr_comment) mapping to tables, columns, and
filters. get_available_configs checks which tables exist.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 3: Implement search templates (BM25, vector, RRF)

**Files:**
- Create: `src/vibe_node/db/search.py`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Write failing tests for search templates**

Add to `tests/test_search.py`:

```python
def test_build_bm25_query():
    """BM25 query builder produces valid SQL structure."""
    from vibe_node.db.search import build_bm25_query
    sql, params = build_bm25_query(
        table="spec_documents",
        text_column="content_plain",
        query="UTxO validation",
        filters={"era": "shelley"},
        filter_columns={"era": "era"},
        limit=10,
        offset=0,
    )
    assert "content_plain" in sql
    assert "pdb.score" in sql
    assert "UTxO validation" in params.values() or any("UTxO" in str(v) for v in params.values())
    assert "shelley" in params.values()


def test_build_vector_query():
    """Vector query builder produces valid SQL structure."""
    from vibe_node.db.search import build_vector_query
    fake_embedding = [0.1] * 1536
    sql, params = build_vector_query(
        table="spec_documents",
        embedding=fake_embedding,
        filters={"era": "shelley"},
        limit=10,
        offset=0,
    )
    assert "embedding" in sql
    assert "<=>" in sql


def test_build_rrf_query():
    """RRF query builder composes BM25 + vector CTEs."""
    from vibe_node.db.search import build_rrf_query
    fake_embedding = [0.1] * 1536
    sql, params = build_rrf_query(
        table="spec_documents",
        text_column="content_plain",
        query="UTxO validation",
        embedding=fake_embedding,
        filters={"era": "shelley"},
        limit=10,
        offset=0,
    )
    assert "bm25" in sql.lower()
    assert "vector" in sql.lower()
    assert "rrf" in sql.lower()
    assert "UNION ALL" in sql
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_search.py -v
```

Expected: 3 new tests FAIL with ImportError

- [ ] **Step 3: Implement search templates**

Create `src/vibe_node/db/search.py`:

```python
"""Composable search templates: BM25, vector, and RRF fusion.

Three query builders that produce (sql, params) tuples for asyncpg execution.
Used by both the Search MCP and the CLI `db search` command.
"""
from __future__ import annotations


def _build_filter_clause(
    filters: dict | None,
    filter_columns: dict | None,
    param_offset: int = 1,
) -> tuple[str, dict, int]:
    """Build WHERE clause fragments from filters.

    Returns (clause_parts, params, next_param_index).
    clause_parts is a list of SQL conditions like "era = $2".
    """
    if not filters or not filter_columns:
        return "", {}, param_offset
    parts = []
    params = {}
    idx = param_offset
    for key, value in filters.items():
        if value is not None and key in filter_columns:
            col = filter_columns[key]
            parts.append(f"{col} = ${idx}")
            params[f"p{idx}"] = value
            idx += 1
    clause = " AND ".join(parts)
    return clause, params, idx


def build_bm25_query(
    table: str,
    text_column: str,
    query: str,
    filters: dict | None = None,
    filter_columns: dict | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[str, list]:
    """Build a BM25 keyword search query.

    Returns (sql, params) for asyncpg execution.
    """
    params = [query]
    idx = 2

    filter_parts = []
    if filters and filter_columns:
        for key, value in filters.items():
            if value is not None and key in filter_columns:
                col = filter_columns[key]
                filter_parts.append(f"{col} = ${idx}")
                params.append(value)
                idx += 1

    where_extra = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""

    params.extend([limit, offset])
    limit_idx = idx
    offset_idx = idx + 1

    sql = f"""
        SELECT *, pdb.score(id) AS bm25_score,
               COUNT(*) OVER () AS total_count
        FROM {table}
        WHERE {text_column} ||| $1{where_extra}
        ORDER BY pdb.score(id) DESC
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """
    return sql, params


def build_vector_query(
    table: str,
    embedding: list[float],
    filters: dict | None = None,
    filter_columns: dict | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[str, list]:
    """Build a vector similarity search query.

    Returns (sql, params) for asyncpg execution.
    """
    embedding_literal = '[' + ','.join(str(x) for x in embedding) + ']'
    params = [embedding_literal]
    idx = 2

    filter_parts = []
    if filters and filter_columns:
        for key, value in filters.items():
            if value is not None and key in filter_columns:
                col = filter_columns[key]
                filter_parts.append(f"{col} = ${idx}")
                params.append(value)
                idx += 1

    where = " AND ".join(filter_parts)
    where_clause = f"WHERE {where}" if where else ""

    params.extend([limit, offset])
    limit_idx = idx
    offset_idx = idx + 1

    sql = f"""
        SELECT *, 1 - (embedding <=> $1::vector) AS similarity,
               COUNT(*) OVER () AS total_count
        FROM {table}
        {where_clause}
        ORDER BY embedding <=> $1::vector
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """
    return sql, params


def build_rrf_query(
    table: str,
    text_column: str,
    query: str,
    embedding: list[float],
    filters: dict | None = None,
    filter_columns: dict | None = None,
    limit: int = 10,
    offset: int = 0,
    k: int = 60,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
    fetch_limit: int = 100,
) -> tuple[str, list]:
    """Build an RRF fusion query combining BM25 + vector search.

    Returns (sql, params) for asyncpg execution.
    """
    embedding_literal = '[' + ','.join(str(x) for x in embedding) + ']'
    params = [query, embedding_literal]
    idx = 3

    filter_parts = []
    if filters and filter_columns:
        for key, value in filters.items():
            if value is not None and key in filter_columns:
                col = filter_columns[key]
                filter_parts.append(f"{col} = ${idx}")
                params.append(value)
                idx += 1

    where_extra = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""

    params.extend([bm25_weight, vector_weight, k, fetch_limit, limit, offset])
    bw_idx = idx
    vw_idx = idx + 1
    k_idx = idx + 2
    fl_idx = idx + 3
    lim_idx = idx + 4
    off_idx = idx + 5

    sql = f"""
        WITH
        bm25 AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY pdb.score(id) DESC) AS rank
            FROM {table}
            WHERE {text_column} ||| $1{where_extra}
            LIMIT ${fl_idx}
        ),
        vector AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> $2::vector) AS rank
            FROM {table}
            {"WHERE " + " AND ".join(filter_parts) if filter_parts else ""}
            LIMIT ${fl_idx}
        ),
        rrf AS (
            SELECT id, ${bw_idx} * 1.0 / (${k_idx} + rank) AS score FROM bm25
            UNION ALL
            SELECT id, ${vw_idx} * 1.0 / (${k_idx} + rank) AS score FROM vector
        ),
        ranked AS (
            SELECT id, SUM(score) AS rrf_score
            FROM rrf
            GROUP BY id
            ORDER BY SUM(score) DESC
        )
        SELECT d.*, r.rrf_score,
               COUNT(*) OVER () AS total_count
        FROM ranked r
        JOIN {table} d ON d.id = r.id
        ORDER BY r.rrf_score DESC
        LIMIT ${lim_idx} OFFSET ${off_idx}
    """
    return sql, params
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_search.py -v
```

Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/vibe_node/db/search.py tests/test_search.py
git commit -m "feat(m0.6): composable search templates — BM25, vector, RRF fusion

Prompt: Implement three query builder functions that produce (sql, params)
tuples. BM25 uses pg_search ||| operator. Vector uses pgvector <=> operator.
RRF composes both via CTE with configurable weights and k-parameter.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 4: Implement cross-table search and upgrade CLI

**Files:**
- Modify: `src/vibe_node/db/search.py`
- Modify: `src/vibe_node/cli_infra.py`

- [ ] **Step 1: Add cross-table search function**

Add to `src/vibe_node/db/search.py`:

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

    Returns (results, total_count). Each result includes 'entity_type' field.
    Skips tables that don't exist (Phase 1 tables).
    """
    from vibe_node.db.search_config import SEARCH_CONFIG, get_available_configs

    available = await get_available_configs(conn)

    if entity_type:
        if entity_type not in available:
            return [], 0
        configs = {entity_type: available[entity_type]}
    else:
        configs = available

    all_results = []
    total = 0

    for etype, cfg in configs.items():
        sql, params = build_rrf_query(
            table=cfg["table"],
            text_column=cfg["text_column"],
            query=query,
            embedding=embedding,
            filters=filters,
            filter_columns=cfg.get("filter_columns"),
            limit=limit,
            offset=0,  # fetch top N from each table, re-rank later
            k=k,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
        )
        try:
            rows = await conn.fetch(sql, *params)
        except Exception as e:
            # Skip tables with index issues or other errors
            import logging
            logging.getLogger(__name__).warning("Search failed on %s: %s", cfg["table"], e)
            continue

        for row in rows:
            r = dict(row)
            r["entity_type"] = etype
            title_col = cfg.get("title_column")
            r["_title"] = r.get(title_col, "") if title_col else ""
            preview_col = cfg["preview_column"]
            preview = r.get(preview_col, "")
            r["_preview"] = preview[:500] if preview else ""
            all_results.append(r)

    # Re-rank by RRF score across all tables
    all_results.sort(key=lambda r: r.get("rrf_score", 0), reverse=True)
    total = len(all_results)

    # Apply pagination
    paginated = all_results[offset:offset + limit]
    return paginated, total
```

- [ ] **Step 2: Upgrade CLI `db search` command**

Find the existing `search` command in `src/vibe_node/cli_infra.py` and replace the ILIKE implementation with RRF. Read the current implementation first to understand its interface, then replace:

```python
@db_app.command(name="search")
def db_search(
    query: str = typer.Argument(help="Search query text"),
    table: str = typer.Option("all", "--table", "-t",
                              help="Entity type: spec, code, issue, pr, all"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
) -> None:
    """Search the knowledge base using BM25 + vector fusion (RRF)."""
    import asyncio

    async def _run():
        from vibe_node.db.pool import get_pool, close_pool
        from vibe_node.db.search import search_all
        from vibe_node.embed.client import EmbeddingClient

        embed_client = EmbeddingClient()
        embedding = await embed_client.embed(query)
        await embed_client.close()

        entity_type = None if table == "all" else table

        pool = await get_pool()
        async with pool.acquire() as conn:
            results, total = await search_all(
                conn, query, embedding,
                entity_type=entity_type,
                limit=limit,
            )
        await close_pool()

        if not results:
            typer.echo("No results found.")
            return

        from rich.console import Console
        from rich.table import Table

        console = Console()
        t = Table(title=f"Search: '{query}' ({total} results)")
        t.add_column("Type", width=8)
        t.add_column("Title", width=40)
        t.add_column("Score", width=8)
        t.add_column("Preview", width=60)

        for r in results:
            t.add_row(
                r.get("entity_type", "?"),
                r.get("_title", "")[:40],
                f"{r.get('rrf_score', 0):.4f}",
                r.get("_preview", "")[:60].replace("\n", " "),
            )
        console.print(t)

    asyncio.run(_run())
```

- [ ] **Step 3: Test CLI search**

```bash
# Test BM25 + vector search
uv run vibe-node db search "UTxO validation"

# Test with entity type filter
uv run vibe-node db search "applyBlock" --table code

# Test with specs
uv run vibe-node db search "chain-sync protocol" --table spec_doc
```

Expected: Results ranked by RRF score from relevant tables.

- [ ] **Step 4: Commit**

```bash
git add src/vibe_node/db/search.py src/vibe_node/cli_infra.py
git commit -m "feat(m0.6): cross-table RRF search and CLI upgrade

Prompt: Implement search_all() for cross-table RRF fusion. Upgrade
vibe-node db search from ILIKE to BM25+vector RRF. Results ranked
by fused score with entity type and preview.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 5: Smoke tests and documentation

**Files:**
- Modify: `tests/test_search.py`

- [ ] **Step 1: Run smoke tests against live database**

```bash
# Verify BM25 works
docker compose exec paradedb psql -U vibenode -d vibenode -c \
  "SELECT id, pdb.score(id) AS score, document_title FROM spec_documents WHERE content_plain ||| 'UTxO validation' ORDER BY pdb.score(id) DESC LIMIT 5;"

# Verify vector works
docker compose exec paradedb psql -U vibenode -d vibenode -c \
  "SELECT id, function_name, 1 - (embedding <=> (SELECT embedding FROM code_chunks WHERE function_name = 'applyBlock' LIMIT 1)) AS similarity FROM code_chunks ORDER BY embedding <=> (SELECT embedding FROM code_chunks WHERE function_name = 'applyBlock' LIMIT 1) LIMIT 5;"

# Verify RRF via CLI
uv run vibe-node db search "UTxO transition rules" --limit 5
uv run vibe-node db search "block validation" --table code --limit 5

# Verify cross-table
uv run vibe-node db search "chain-sync" --limit 10

# Check index sizes
docker compose exec paradedb psql -U vibenode -d vibenode -c \
  "SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) AS size FROM pg_indexes WHERE indexname LIKE 'idx_%bm25' OR indexname LIKE 'idx_%hnsw' ORDER BY indexname;"
```

- [ ] **Step 2: Verify embedding dimensions**

```bash
docker compose exec paradedb psql -U vibenode -d vibenode -c \
  "SELECT vector_dims(embedding) FROM spec_documents WHERE embedding IS NOT NULL LIMIT 1;"
```

Expected: 1536

- [ ] **Step 3: Commit smoke test results as devlog notes**

Document the smoke test results (index sizes, query latencies, sample results) for the devlog.

```bash
git add tests/test_search.py
git commit -m "test(m0.6): smoke tests — BM25, vector, RRF verified against live data

Prompt: Run smoke tests verifying BM25, vector, and RRF search work on
all tables. Verify index sizes and embedding dimensions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Chunk 2: M0.7 — Search MCP & CrystalDB

### Task 6: Create MCP server skeleton and database module

**Files:**
- Create: `src/vibe_node/mcp/__init__.py`
- Create: `src/vibe_node/mcp/search_server.py`
- Create: `src/vibe_node/mcp/db.py`
- Create: `src/vibe_node/mcp/embed.py`
- Create: `src/vibe_node/mcp/tools/__init__.py`

- [ ] **Step 1: Add mcp dependency**

```bash
uv add mcp
```

- [ ] **Step 2: Create MCP database connection module**

Create `src/vibe_node/mcp/__init__.py` (empty).

Create `src/vibe_node/db/pool.py` (shared pool used by both MCP and CLI):

```python
"""Shared asyncpg connection pool.

Used by both the MCP server and CLI commands that need async DB access.
"""
import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the asyncpg connection pool."""
    global _pool
    if _pool is None:
        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://vibenode:vibenode@localhost:5432/vibenode",
        )
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
```

Create `src/vibe_node/mcp/db.py` (re-exports shared pool for MCP convenience):

```python
"""asyncpg connection pool for the MCP server.

Re-exports the shared pool from vibe_node.db.pool so MCP tool modules
can import from vibe_node.mcp.db without knowing the shared location.
"""
from vibe_node.db.pool import get_pool, close_pool  # noqa: F401
```

- [ ] **Step 3: Create MCP embedding module**

Create `src/vibe_node/mcp/embed.py`:

```python
"""Query embedding via Ollama for the MCP server."""
import os

from vibe_node.embed.client import EmbeddingClient

_client: EmbeddingClient | None = None


async def embed_query(text: str) -> list[float]:
    """Embed a query string using the configured Ollama model."""
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return await _client.embed(text)


async def close():
    """Close the embedding client."""
    global _client
    if _client:
        await _client.close()
        _client = None
```

- [ ] **Step 4: Create MCP server entry point**

Create `src/vibe_node/mcp/tools/__init__.py` (empty).

Create `src/vibe_node/mcp/search_server.py`:

```python
"""vibe-node Search MCP server.

Read-only access to the knowledge base via 6 tools:
search, find_similar, get_related, coverage, get_entity, compare_versions.

Run: uv run python -m vibe_node.mcp.search_server
"""
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vibe-search")


def register_tools():
    """Import all tool modules so their @mcp.tool() decorators fire."""
    from vibe_node.mcp.tools import search, similar, related, coverage, entity, versions  # noqa: F401


register_tools()

if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 5: Commit**

```bash
git add src/vibe_node/mcp/ pyproject.toml uv.lock
git commit -m "feat(m0.7): MCP server skeleton with db pool and embedding module

Prompt: Create MCP server entry point, asyncpg connection pool, and Ollama
embedding wrapper. Server uses stdio transport and registers 6 tool modules.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 7: Implement search and find_similar tools

**Files:**
- Create: `src/vibe_node/mcp/tools/search.py`
- Create: `src/vibe_node/mcp/tools/similar.py`

- [ ] **Step 1: Implement search tool**

Create `src/vibe_node/mcp/tools/search.py`:

```python
"""search tool — RRF fusion across all knowledge base tables."""
from __future__ import annotations

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.mcp.embed import embed_query
from vibe_node.db.search import search_all


@mcp.tool()
async def search(
    query: str,
    entity_type: str | None = None,
    era: str | None = None,
    repo: str | None = None,
    # NOTE: subsystem filter will be added when Phase 1 tables
    # (spec_sections, gap_analysis) are created in M1.3.
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Search the Cardano knowledge base using BM25 + vector fusion (RRF).

    Returns ranked results from specs, code, issues, and PRs.
    """
    filters: dict[str, str] = {}
    if era:
        filters["era"] = era
    if repo:
        filters["repo"] = repo

    embedding = await embed_query(query)

    pool = await get_pool()
    async with pool.acquire() as conn:
        results, total = await search_all(
            conn, query, embedding,
            entity_type=entity_type,
            filters=filters if filters else None,
            limit=limit,
            offset=offset,
        )

    return {
        "results": [
            {
                "entity_type": r.get("entity_type", "unknown"),
                "id": str(r.get("id", "")),
                "title": r.get("_title", ""),
                "score": round(r.get("rrf_score", 0), 4),
                "content_preview": r.get("_preview", ""),
            }
            for r in results
        ],
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
```

- [ ] **Step 2: Implement find_similar tool**

Create `src/vibe_node/mcp/tools/similar.py`:

```python
"""find_similar tool — pure vector similarity search."""
from __future__ import annotations

import uuid as _uuid

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.mcp.embed import embed_query
from vibe_node.db.search import build_vector_query
from vibe_node.db.search_config import get_available_configs


@mcp.tool()
async def find_similar(
    text: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    target_type: str | None = None,
    era: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Find semantically similar entities in the knowledge base.

    Given text or an entity ID, returns the most similar specs, code, issues, etc.
    """
    filters: dict[str, str] = {}
    if era:
        filters["era"] = era

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Get embedding — either from text or from an existing entity
        if text:
            embedding = await embed_query(text)
        elif entity_id and entity_type:
            entity_uuid = _uuid.UUID(entity_id)
            available = await get_available_configs(conn)
            cfg = available.get(entity_type)
            if not cfg:
                return {"error": f"Unknown entity type: {entity_type}"}
            row = await conn.fetchrow(
                f"SELECT embedding FROM {cfg['table']} WHERE id = $1",
                entity_uuid,
            )
            if not row or not row["embedding"]:
                return {"error": "Entity not found or has no embedding"}
            embedding = row["embedding"]
        else:
            return {"error": "Provide either 'text' or 'entity_type' + 'entity_id'"}

        # Search target tables
        available = await get_available_configs(conn)
        if target_type:
            configs = {target_type: available[target_type]} if target_type in available else {}
        else:
            configs = available

        all_results = []
        for etype, cfg in configs.items():
            sql, sql_params = build_vector_query(
                table=cfg["table"],
                embedding=embedding,
                filters=filters if filters else None,
                filter_columns=cfg.get("filter_columns"),
                limit=limit,
                offset=0,
            )
            try:
                rows = await conn.fetch(sql, *sql_params)
                for row in rows:
                    r = dict(row)
                    r["entity_type"] = etype
                    title_col = cfg.get("title_column")
                    r["_title"] = r.get(title_col, "") if title_col else ""
                    preview_col = cfg["preview_column"]
                    preview = r.get(preview_col, "")
                    r["_preview"] = preview[:500] if preview else ""
                    all_results.append(r)
            except Exception:
                continue

    # Sort by similarity across all tables
    all_results.sort(key=lambda r: r.get("similarity", 0), reverse=True)
    total = len(all_results)
    paginated = all_results[offset:offset + limit]

    return {
        "results": [
            {
                "entity_type": r.get("entity_type"),
                "id": str(r.get("id", "")),
                "title": r.get("_title", ""),
                "similarity": round(r.get("similarity", 0), 4),
                "content_preview": r.get("_preview", ""),
            }
            for r in paginated
        ],
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
```

- [ ] **Step 3: Commit**

```bash
git add src/vibe_node/mcp/tools/search.py src/vibe_node/mcp/tools/similar.py
git commit -m "feat(m0.7): search and find_similar MCP tools

Prompt: Implement search tool (RRF fusion across all tables) and find_similar
tool (pure vector similarity). Both support entity_type filtering, era/repo
filters, and pagination.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 8: Implement get_related, coverage, get_entity, compare_versions tools

**Files:**
- Create: `src/vibe_node/mcp/tools/related.py`
- Create: `src/vibe_node/mcp/tools/coverage.py`
- Create: `src/vibe_node/mcp/tools/entity.py`
- Create: `src/vibe_node/mcp/tools/versions.py`

- [ ] **Step 1: Implement get_related tool**

Create `src/vibe_node/mcp/tools/related.py`:

```python
"""get_related tool — navigate cross-references."""
from __future__ import annotations

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool

INVERSE_MAP = {
    "implements": "implementedBy",
    "tests": "testedBy",
    "discusses": "discussedIn",
    "references": "referencedBy",
    "contradicts": "contradictedBy",
    "extends": "extendedBy",
    "derivedFrom": "derivationOf",
    "supersedes": "supersededBy",
    "requires": "requiredBy",
    "trackedBy": "tracks",
}
INVERSE_REVERSE = {v: k for k, v in INVERSE_MAP.items()}


@mcp.tool()
async def get_related(
    entity_type: str,
    entity_id: str,
    relationship: str | None = None,
    target_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Navigate cross-references. Given an entity, find everything linked to it
    via the relationship graph. Returns empty results if cross_references table
    doesn't exist yet (created in Phase 1).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check if cross_references table exists
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'cross_references')"
        )
        if not exists:
            return {
                "source": {"entity_type": entity_type, "id": entity_id},
                "results": [],
                "total_count": 0,
                "offset": offset,
                "limit": limit,
                "note": "cross_references table not yet created (Phase 1)",
            }

        # Query both directions
        results = []

        # Outgoing (this entity is source)
        out_rows = await conn.fetch(
            """SELECT * FROM cross_references
               WHERE source_type = $1 AND source_id = $2
               ORDER BY relationship""",
            entity_type, entity_id,
        )
        for row in out_rows:
            rel = row["relationship"]
            results.append({
                "direction": "outgoing",
                "relationship": rel,
                "entity_type": row["target_type"],
                "id": str(row["target_id"]),
                "confidence": row["confidence"],
                "notes": row["notes"],
            })

        # Incoming (this entity is target) — show inverse relationship name
        in_rows = await conn.fetch(
            """SELECT * FROM cross_references
               WHERE target_type = $1 AND target_id = $2
               ORDER BY relationship""",
            entity_type, entity_id,
        )
        for row in in_rows:
            rel = row["relationship"]
            inverse = INVERSE_MAP.get(rel, f"inv_{rel}")
            results.append({
                "direction": "incoming",
                "relationship": inverse,
                "entity_type": row["source_type"],
                "id": str(row["source_id"]),
                "confidence": row["confidence"],
                "notes": row["notes"],
            })

        # Apply filters
        if relationship:
            canonical = INVERSE_REVERSE.get(relationship, relationship)
            results = [r for r in results if r["relationship"] == relationship or r["relationship"] == canonical]
        if target_type:
            results = [r for r in results if r["entity_type"] == target_type]

        total = len(results)
        paginated = results[offset:offset + limit]

    return {
        "source": {"entity_type": entity_type, "id": entity_id},
        "results": paginated,
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
```

- [ ] **Step 2: Implement coverage tool**

Create `src/vibe_node/mcp/tools/coverage.py`:

```python
"""coverage tool — spec coverage dashboard."""
from __future__ import annotations

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool


@mcp.tool()
async def coverage(
    subsystem: str | None = None,
    era: str | None = None,
    show_uncovered: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Spec coverage dashboard. Shows which spec rules have implementations,
    tests, gaps, and discussions. Returns empty if spec_sections table
    doesn't exist yet (Phase 1).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check if required tables exist
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE tablename IN ('spec_sections', 'cross_references', 'test_specifications')"
        )
        existing = {row["tablename"] for row in tables}

        if "spec_sections" not in existing:
            return {
                "summary": {"total_sections": 0},
                "note": "spec_sections table not yet created (Phase 1). Coverage tracking starts after M1.3.",
            }

        # Build coverage query
        conditions = []
        qparams: list = []
        idx = 1
        if subsystem:
            conditions.append(f"ss.subsystem = ${idx}")
            qparams.append(subsystem)
            idx += 1
        if era:
            conditions.append(f"ss.era = ${idx}")
            qparams.append(era)
            idx += 1
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        has_xref = "cross_references" in existing
        has_tests = "test_specifications" in existing

        impl_check = f"""EXISTS (
            SELECT 1 FROM cross_references cr
            WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id
            AND cr.relationship = 'implements'
        )""" if has_xref else "FALSE"

        test_check = f"""EXISTS (
            SELECT 1 FROM test_specifications ts WHERE ts.spec_section_id = ss.id
        )""" if has_tests else "FALSE"

        discuss_check = f"""EXISTS (
            SELECT 1 FROM cross_references cr
            WHERE (cr.source_type = 'spec_section' AND cr.source_id = ss.id
                   OR cr.target_type = 'spec_section' AND cr.target_id = ss.id)
            AND cr.relationship = 'discusses'
        )""" if has_xref else "FALSE"

        summary = await conn.fetchrow(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE {impl_check}) AS with_implementation,
                COUNT(*) FILTER (WHERE {test_check}) AS with_tests,
                COUNT(*) FILTER (WHERE {discuss_check}) AS with_discussions,
                COUNT(*) FILTER (WHERE NOT {impl_check} AND NOT {test_check}) AS uncovered
            FROM spec_sections ss {where}
        """, *qparams)

        output: dict = {
            "summary": {
                "total_sections": summary["total"],
                "with_implementation": summary["with_implementation"],
                "with_tests": summary["with_tests"],
                "with_discussions": summary["with_discussions"],
                "uncovered": summary["uncovered"],
            },
        }

        if show_uncovered:
            # Use AND (not a second WHERE) to combine with existing conditions
            uncovered_where = f"{where} AND" if conditions else "WHERE"
            uncovered = await conn.fetch(f"""
                SELECT ss.section_id, ss.title, ss.subsystem, ss.era, ss.section_type
                FROM spec_sections ss
                {uncovered_where} NOT {impl_check} AND NOT {test_check}
                ORDER BY ss.subsystem, ss.section_id
                LIMIT ${idx} OFFSET ${idx + 1}
            """, *qparams, limit, offset)

            output["uncovered"] = [dict(r) for r in uncovered]
            output["total_uncovered"] = summary["uncovered"]

        output["offset"] = offset
        output["limit"] = limit

    return output
```

- [ ] **Step 3: Implement get_entity tool**

Create `src/vibe_node/mcp/tools/entity.py`:

```python
"""get_entity tool — fetch full entity details."""
from __future__ import annotations

import uuid as _uuid

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.db.search_config import get_available_configs


@mcp.tool()
async def get_entity(
    entity_type: str,
    entity_id: str | None = None,
    section_id: str | None = None,
    function_name: str | None = None,
    repo: str | None = None,
    include_relationships: bool = True,
    rel_limit: int = 20,
    rel_offset: int = 0,
) -> dict:
    """Fetch full details of a specific entity by ID or human-readable identifier."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        available = await get_available_configs(conn)
        cfg = available.get(entity_type)
        if not cfg:
            return {"error": f"Unknown or unavailable entity type: {entity_type}"}

        table = cfg["table"]
        row = None

        if entity_id:
            entity_uuid = _uuid.UUID(entity_id)
            row = await conn.fetchrow(f"SELECT * FROM {table} WHERE id = $1", entity_uuid)
        elif section_id and table == "spec_sections":
            row = await conn.fetchrow(f"SELECT * FROM {table} WHERE section_id = $1", section_id)
        elif function_name and table == "code_chunks":
            q = f"SELECT * FROM {table} WHERE function_name = $1"
            p: list = [function_name]
            if repo:
                q += " AND repo = $2"
                p.append(repo)
            q += " ORDER BY release_tag DESC LIMIT 1"
            row = await conn.fetchrow(q, *p)

        if not row:
            return {"error": "Entity not found"}

        entity = {k: str(v) if hasattr(v, 'hex') else v for k, v in dict(row).items()}
        # Remove embedding from response (too large)
        entity.pop("embedding", None)

        output: dict = {"entity": entity}

        # Include relationships if requested and cross_references exists
        if include_relationships:
            xref_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'cross_references')"
            )
            if xref_exists:
                rels = await conn.fetch(
                    """SELECT * FROM cross_references
                       WHERE (source_type = $1 AND source_id = $2)
                          OR (target_type = $1 AND target_id = $2)
                       LIMIT $3 OFFSET $4""",
                    entity_type, row["id"], rel_limit, rel_offset,
                )
                output["relationships"] = {
                    "results": [dict(r) for r in rels],
                    "total_count": len(rels),
                    "offset": rel_offset,
                    "limit": rel_limit,
                }

    return output
```

- [ ] **Step 4: Implement compare_versions tool**

Create `src/vibe_node/mcp/tools/versions.py`:

```python
"""compare_versions tool — diff entities across versions."""
from __future__ import annotations

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool


@mcp.tool()
async def compare_versions(
    entity_type: str,
    version_a: str,
    version_b: str,
    function_name: str | None = None,
    repo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Compare a function between release tags or see what changed between two versions."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if function_name:
            # Single function comparison
            conditions = "function_name = $1"
            p_a = [function_name, version_a]
            p_b = [function_name, version_b]
            if repo:
                conditions += " AND repo = $2"
                p_a.append(repo)
                p_b.append(repo)
                tag_param = "$3"
            else:
                tag_param = "$2"

            row_a = await conn.fetchrow(
                f"SELECT content, signature, module_name, file_path, content_hash FROM code_chunks WHERE {conditions} AND release_tag = {tag_param}",
                *p_a,
            )
            row_b = await conn.fetchrow(
                f"SELECT content, signature, module_name, file_path, content_hash FROM code_chunks WHERE {conditions} AND release_tag = {tag_param}",
                *p_b,
            )

            status = "unchanged"
            if row_a and not row_b:
                status = "removed"
            elif not row_a and row_b:
                status = "added"
            elif row_a and row_b and row_a["content_hash"] != row_b["content_hash"]:
                status = "changed"
            elif not row_a and not row_b:
                status = "not_found"

            output = {
                "function_name": function_name,
                "repo": repo,
                "version_a": version_a,
                "version_b": version_b,
                "status": status,
                "content_a": dict(row_a) if row_a else None,
                "content_b": dict(row_b) if row_b else None,
            }
        else:
            # Broad comparison — what changed between two tags
            # NOTE: code_tag_manifest has function_name, file_path, content_hash
            # but NOT module_name — that column only exists on code_chunks.
            repo_cond = "AND repo = $3" if repo else ""
            base_params: list = [version_a, version_b]
            if repo:
                base_params.append(repo)

            # Functions in A but not B (removed)
            removed = await conn.fetch(f"""
                SELECT function_name, file_path FROM code_tag_manifest
                WHERE release_tag = $1 {repo_cond}
                AND (function_name, file_path) NOT IN (
                    SELECT function_name, file_path FROM code_tag_manifest WHERE release_tag = $2 {repo_cond}
                )
                LIMIT ${ len(base_params) + 1} OFFSET ${len(base_params) + 2}
            """, *base_params, limit, offset)

            # Functions in B but not A (added)
            added = await conn.fetch(f"""
                SELECT function_name, file_path FROM code_tag_manifest
                WHERE release_tag = $2 {repo_cond}
                AND (function_name, file_path) NOT IN (
                    SELECT function_name, file_path FROM code_tag_manifest WHERE release_tag = $1 {repo_cond}
                )
                LIMIT ${len(base_params) + 1} OFFSET ${len(base_params) + 2}
            """, *base_params, limit, offset)

            # Functions in both but with different content_hash (changed)
            changed = await conn.fetch(f"""
                SELECT a.function_name, a.file_path,
                       a.content_hash AS hash_a, b.content_hash AS hash_b
                FROM code_tag_manifest a
                JOIN code_tag_manifest b ON a.function_name = b.function_name
                    AND a.file_path = b.file_path AND a.repo = b.repo
                WHERE a.release_tag = $1 AND b.release_tag = $2
                    {repo_cond.replace('repo', 'a.repo')}
                    AND a.content_hash != b.content_hash
                LIMIT ${len(base_params) + 1} OFFSET ${len(base_params) + 2}
            """, *base_params, limit, offset)

            output = {
                "repo": repo,
                "version_a": version_a,
                "version_b": version_b,
                "added": [dict(r) for r in added],
                "removed": [dict(r) for r in removed],
                "changed": [dict(r) for r in changed],
                "total_added": len(added),
                "total_removed": len(removed),
                "total_changed": len(changed),
                "offset": offset,
                "limit": limit,
            }

    return output
```

- [ ] **Step 5: Commit**

```bash
git add src/vibe_node/mcp/tools/
git commit -m "feat(m0.7): get_related, coverage, get_entity, compare_versions MCP tools

Prompt: Implement 4 remaining MCP tools. get_related navigates cross-references
with inverse relationship names. coverage shows spec coverage dashboard.
get_entity fetches full details by ID or human-readable key. compare_versions
diffs code between release tags.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 9: Configure MCPs and test end-to-end

**Files:**
- Create: `.mcp.json`

- [ ] **Step 1: Create .mcp.json**

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

- [ ] **Step 2: Test MCP server starts**

```bash
uv run python -m vibe_node.mcp.search_server
```

Expected: Server starts and waits for stdio input (Ctrl+C to stop).

- [ ] **Step 3: Test all tools from Claude Code**

Restart Claude Code to pick up `.mcp.json`. Then test each tool:

1. search: "UTxO validation rules"
2. find_similar: with code text about block validation
3. get_related: with a known entity ID
4. coverage: (will return empty until Phase 1)
5. get_entity: with entity_type=code, function_name=applyBlock
6. compare_versions: two cardano-ledger release tags
7. CrystalDB: `SELECT count(*) FROM spec_documents`

- [ ] **Step 4: Commit**

```bash
git add .mcp.json
git commit -m "feat(m0.7): configure Search MCP and CrystalDB MCP in .mcp.json

Prompt: Register vibe-search (6 read-only tools) and crystaldb (raw SQL)
MCP servers. Both connect to the local ParadeDB instance.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 10: Documentation

**Files:**
- Create or update MCP documentation page

- [ ] **Step 1: Document M0.6 and M0.7 in devlog**

Add devlog entries covering:
- Index creation (BM25 + HNSW)
- Search template architecture (composable BM25/vector/RRF)
- MCP tools (6 tools + CrystalDB)
- Relationship vocabulary (10 types with inverses)
- Semantic search + relationship workflow

- [ ] **Step 2: Update CLI reference**

Add `db create-indexes` and updated `db search` (RRF) to `docs/reference/cli-reference.md`.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs(m0.6, m0.7): search infrastructure and MCP documentation

Prompt: Document BM25/HNSW indexes, composable search templates,
6 MCP tools, relationship vocabulary, and semantic search workflow.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Complete Checklist

- [ ] M0.6: BM25 indexes created on all 6 tables
- [ ] M0.6: HNSW vector indexes created on all 6 tables
- [ ] M0.6: BM25 search template implemented and tested
- [ ] M0.6: Vector search template implemented and tested
- [ ] M0.6: RRF fusion template implemented and tested
- [ ] M0.6: Cross-table search working
- [ ] M0.6: CLI `db search` upgraded from ILIKE to RRF
- [ ] M0.6: CLI `db create-indexes` command working
- [ ] M0.6: Smoke tests pass (BM25, vector, RRF, filters, cross-table)
- [ ] M0.7: MCP server starts and registers all 6 tools
- [ ] M0.7: search tool returns RRF results with pagination
- [ ] M0.7: find_similar returns vector similarity results
- [ ] M0.7: get_related handles missing cross_references gracefully
- [ ] M0.7: coverage handles missing spec_sections gracefully
- [ ] M0.7: get_entity fetches by ID and human-readable key
- [ ] M0.7: compare_versions diffs functions between tags
- [ ] M0.7: CrystalDB MCP configured and working
- [ ] M0.7: .mcp.json registered both servers
- [ ] M0.7: All tools accessible from Claude Code
- [ ] Documentation updated (devlog, CLI reference)
