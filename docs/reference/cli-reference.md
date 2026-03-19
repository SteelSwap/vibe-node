# CLI Reference

The `vibe-node` CLI is built on [Typer](https://typer.tiangolo.com/) and provides a unified interface for infrastructure management, data ingestion, and database operations.

## Top Level

```
vibe-node [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--version`, `-v` | Show version and exit |
| `--help` | Show help and exit |

## vibe-node serve

```
vibe-node serve [OPTIONS]
```

Start the Cardano node.

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Host to bind to |
| `--port` | `3001` | Port to listen on |

!!! note
    Not yet implemented. The vibes are immaculate, but the node is still being built.

---

## vibe-node infra

Docker Compose infrastructure management.

### infra up

```
vibe-node infra up [OPTIONS]
```

Start the full Docker Compose stack (ParadeDB, Ollama, Mithril, cardano-node, Ogmios).

| Option | Default | Description |
|--------|---------|-------------|
| `--detach / --no-detach`, `-d` | `--detach` | Run in background |

```bash
# Start everything in background
vibe-node infra up

# Start in foreground (see all logs)
vibe-node infra up --no-detach
```

### infra down

```
vibe-node infra down [OPTIONS]
```

Stop the Docker Compose stack.

| Option | Default | Description |
|--------|---------|-------------|
| `--volumes`, `-v` | `false` | Also remove Docker volumes (destroys all data) |

```bash
# Stop services, keep data
vibe-node infra down

# Stop services and destroy all volumes
vibe-node infra down --volumes
```

### infra status

```
vibe-node infra status
```

Show status of all Docker services. Equivalent to `docker compose ps`.

### infra logs

```
vibe-node infra logs [SERVICE] [OPTIONS]
```

View logs from Docker services.

| Argument/Option | Default | Description |
|----------------|---------|-------------|
| `SERVICE` | all | Service name (e.g. `paradedb`, `ollama`). Omit for all services |
| `--follow`, `-f` | `false` | Follow log output |
| `--tail`, `-n` | `50` | Number of lines to show |

```bash
# Last 50 lines from all services
vibe-node infra logs

# Follow ParadeDB logs
vibe-node infra logs paradedb --follow

# Last 200 lines from Ollama
vibe-node infra logs ollama --tail 200
```

---

## vibe-node ingest

Data ingestion commands. All ingest commands require the Docker infrastructure to be running (`vibe-node infra up`).

### ingest issues

```
vibe-node ingest issues [OPTIONS]
```

Ingest GitHub issues and PRs with full discussion threads via GraphQL.

**Requires** `GITHUB_TOKEN` environment variable (or in `.env` file).

| Option | Default | Description |
|--------|---------|-------------|
| `--repo`, `-r` | all 7 repos | Single repo to ingest (e.g. `IntersectMBO/cardano-node`) |
| `--limit`, `-n` | unlimited | Max issues/PRs per repo |
| `--rescan` | off | Re-fetch all items to check for new comments (skips re-embedding if comment count unchanged) |

```bash
# Ingest everything
vibe-node ingest issues

# Test with 10 items from one repo
vibe-node ingest issues --repo IntersectMBO/cardano-node --limit 10

# Update existing items with new comments
vibe-node ingest issues --rescan
```

### ingest specs

```
vibe-node ingest specs [OPTIONS]
```

Ingest spec documents from vendor submodules.

| Option | Default | Description |
|--------|---------|-------------|
| `--format`, `-f` | all formats | Only ingest this format: `markdown`, `cddl`, `latex`, `agda`, `pdf` |
| `--source`, `-s` | all sources | Only ingest sources matching this substring (checks repo, era, glob) |
| `--limit`, `-n` | unlimited | Max files per source |
| `--history` | off | Walk git commit history for versioned spec tracking (slow) |

```bash
# Ingest everything
vibe-node ingest specs

# Only markdown specs
vibe-node ingest specs --format markdown

# Only Ouroboros consensus specs
vibe-node ingest specs --source consensus

# Test LaTeX conversion with 2 files from ledger
vibe-node ingest specs --format latex --source ledger --limit 2
```

### ingest code

```
vibe-node ingest code [OPTIONS]
```

Index Haskell and Agda source code from vendor submodules by release tag.

| Option | Default | Description |
|--------|---------|-------------|
| `--repo`, `-r` | all 6 repos | Single repo to ingest (e.g. `cardano-ledger`) |
| `--limit`, `-n` | unlimited | Max tags per repo |

```bash
# Index everything
vibe-node ingest code

# Single repo, 2 most recent tags
vibe-node ingest code --repo cardano-node --limit 2
```

---

## vibe-node db

Database management commands.

### db status

```
vibe-node db status
```

Show row counts for all 6 tables. Useful for verifying ingestion progress.

```bash
$ vibe-node db status
  table_name          | count
 ---------------------+-------
  code_chunks         | 45230
  github_issue_comments | 12841
  github_issues       |  3206
  github_pr_comments  | 28412
  github_pull_requests |  4105
  spec_documents      |  2847
```

### db reset

```
vibe-node db reset [OPTIONS]
```

Drop all tables and recreate the database schema. **This is destructive.** Requires double confirmation unless `--force` is used.

| Option | Default | Description |
|--------|---------|-------------|
| `--yes`, `-y` | `false` | Skip first confirmation prompt |
| `--force`, `-f` | `false` | Skip ALL confirmations (for scripts) |

```bash
# Interactive (two confirmations)
vibe-node db reset

# Skip first confirmation
vibe-node db reset --yes

# No confirmations (CI/scripts)
vibe-node db reset --force
```

### db snapshot

```
vibe-node db snapshot
```

Create a `pg_dump` snapshot of the ParadeDB database. Snapshots are saved to `snapshots/` with a timestamp filename and zstd compression.

```bash
$ vibe-node db snapshot
Creating snapshot: snapshots/vibenode_20260315_143022.dump
Snapshot saved: snapshots/vibenode_20260315_143022.dump (127.3 MB)
```

### db restore

```
vibe-node db restore SNAPSHOT_FILE [OPTIONS]
```

Restore the database from a `pg_dump` snapshot. **This replaces all existing data.**

| Argument/Option | Description |
|----------------|-------------|
| `SNAPSHOT_FILE` | Path to `.dump` file (required) |
| `--force`, `-f` | Skip confirmation |

```bash
# Interactive
vibe-node db restore snapshots/vibenode_20260315_143022.dump

# Non-interactive
vibe-node db restore snapshots/vibenode_20260315_143022.dump --force
```

### db search

```
vibe-node db search QUERY [OPTIONS]
```

Search the knowledge base using BM25 + vector fusion (Reciprocal Rank Fusion). Embeds the query via Ollama, runs a BM25 full-text search and an HNSW approximate nearest-neighbor search in parallel, then merges results with RRF for the final ranked list. Upgraded from ILIKE in M0.6.

| Argument/Option | Default | Description |
|----------------|---------|-------------|
| `QUERY` | required | Search query text |
| `--table`, `-t` | `all` | Table to search: `spec_doc`, `code`, `issue`, `issue_comment`, `pr`, `pr_comment`, or `all` |
| `--limit`, `-n` | `10` | Max results |

```bash
# Search everything
vibe-node db search "UTxO validation"

# Search only specs
vibe-node db search "block header" --table spec_doc

# Search code with more results
vibe-node db search "applyBlock" --table code --limit 20
```

### db create-indexes

```
vibe-node db create-indexes
```

Create BM25 (pg_search) and HNSW (pgvector) indexes on all 6 knowledge base tables. Run once after initial data ingestion. Safe to re-run: BM25 indexes are dropped and recreated, HNSW indexes use `IF NOT EXISTS`.

```bash
vibe-node db create-indexes
```

### db xref add

```
vibe-node db xref add SOURCE_TYPE SOURCE_ID TARGET_TYPE TARGET_ID RELATIONSHIP [OPTIONS]
```

Add a cross-reference between two entities in the knowledge base.

| Option | Description |
|--------|-------------|
| `--confidence`, `-c` | Confidence score 0.0-1.0 (default: 1.0) |
| `--notes` | Optional notes about the relationship |
| `--by` | Who created the reference (default: "manual") |

Relationship types: `implements`, `tests`, `discusses`, `references`, `contradicts`, `extends`, `derivedFrom`, `supersedes`, `requires`, `trackedBy`

### db xref query

```
vibe-node db xref query ENTITY_TYPE ENTITY_ID [OPTIONS]
```

Query all cross-references involving an entity (as source or target). Shows both outgoing relationships and incoming (inverse) relationships.

| Option | Description |
|--------|-------------|
| `--rel`, `-r` | Filter by relationship type |
| `--target`, `-t` | Filter by target entity type |

### db xref coverage

```
vibe-node db xref coverage [OPTIONS]
```

Show spec coverage report — which spec rules have implementations, tests, gaps documented, and which are uncovered.

| Option | Description |
|--------|-------------|
| `--subsystem`, `-s` | Filter by subsystem |
| `--era`, `-e` | Filter by era |

### db test-specs list

```
vibe-node db test-specs list [OPTIONS]
```

List planned test specifications from the knowledge base.

| Option | Description |
|--------|-------------|
| `--subsystem`, `-s` | Filter by subsystem |
| `--phase`, `-p` | Filter by implementation phase |
| `--type`, `-t` | Filter by test type (unit, property, replay, conformance, integration) |
| `--priority` | Filter by priority (critical, high, medium, low) |
| `--limit`, `-n` | Max results (default: 50) |

---

## vibe-node research

Research and analysis commands for the PydanticAI rule extraction pipeline.

### research extract-rules

```
vibe-node research extract-rules SUBSYSTEM [OPTIONS]
```

Run the 4-stage agentic pipeline for a subsystem:

1. **Rule Extraction** (Opus 4.6) — LLM reads spec chunks, extracts structured rules
2. **Semantic Search** (Ollama) — Vector search for candidate code, tests, issues
3. **Link Evaluation** (Sonnet 4.5) — LLM evaluates each candidate relationship
4. **Gap Detection + Test Proposals** (Opus 4.6) — Compares spec vs code, proposes Hypothesis tests

| Option | Description |
|--------|-------------|
| `--limit`, `-n` | Max spec chunks to process |
| `--concurrency`, `-c` | Chunks to process in parallel (default: 3) |

Valid subsystems: `networking`, `miniprotocols-n2n`, `miniprotocols-n2c`, `consensus`, `ledger`, `plutus`, `serialization`, `mempool`, `storage`, `block-production`

Requires AWS credentials (Bedrock) or `ANTHROPIC_API_KEY`. Override models via `EXTRACTION_MODEL` and `LINKING_MODEL` env vars.

```bash
# Run on serialization subsystem
vibe-node research extract-rules serialization

# Limit to 5 chunks, 5 concurrent
vibe-node research extract-rules networking --limit 5 -c 5

# Check results
vibe-node db xref coverage --subsystem serialization
vibe-node db test-specs list --subsystem serialization
```

---

## Key Files

| File | Purpose |
|------|---------|
| `src/vibe_node/cli.py` | Main CLI app, db, ingest, and research commands |
| `src/vibe_node/cli_infra.py` | Infra commands, db snapshot/restore/search |
| `src/vibe_node/cli_xref.py` | Cross-reference and test-specs CLI commands |
| `src/vibe_node/db/pool.py` | Shared asyncpg connection pool (CLI + MCP) |
| `src/vibe_node/db/spec_sections.py` | Spec sections CRUD |
| `src/vibe_node/db/xref.py` | Cross-references CRUD + coverage analysis |
| `src/vibe_node/db/test_specs.py` | Test specifications CRUD |
| `src/vibe_node/research/pipeline.py` | PydanticAI 4-stage extraction pipeline |
| `src/vibe_node/research/models.py` | Pydantic models for pipeline I/O |
| `src/vibe_node/mcp/search_server.py` | FastMCP search server (6 read-only tools) |
