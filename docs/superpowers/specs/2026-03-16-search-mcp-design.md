# Search MCP — Design Spec

**Goal:** A read-only MCP server that provides semantic search, relationship navigation, and coverage analysis across the vibe-node knowledge base. Primary interface for Agent Millenial during development.

**Architecture:** Single MCP server with 6 tools. Connects to ParadeDB for BM25 + vector search (RRF fusion). All writes go through the CLI — the MCP is strictly read-only. A separate CrystalDB MCP provides raw SQL access as an escape hatch for queries the Search MCP doesn't cover.

**Tech Stack:** Python MCP server (mcp SDK), asyncpg for ParadeDB, Ollama for query embedding

---

## Design Principles

1. **Read-only** — The MCP never modifies data. Writes go through CLI commands.
2. **Pagination everywhere** — Every list response includes `total_count`, `offset`, `limit`.
3. **Semantic + structural** — Combines embedding vectors (semantic similarity) with typed relationships (structural connections).
4. **Entity-aware** — Every result includes its entity type, ID, and enough context to be useful without a follow-up query.

## Tools

### 1. `search`

The primary tool. Embeds a natural language query via Ollama, then executes RRF fusion (BM25 keyword + vector similarity) across all tables. Returns ranked results with content previews.

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | Natural language search query |
| `entity_type` | string | `null` | Filter: `spec`, `code`, `issue`, `pr`, `gap`, or `null` for all |
| `era` | string | `null` | Filter by era (byron, shelley, ..., conway) |
| `subsystem` | string | `null` | Filter by subsystem (networking, ledger, consensus, etc.) |
| `repo` | string | `null` | Filter by source repository |
| `limit` | int | 10 | Max results to return |
| `offset` | int | 0 | Skip first N results |

**Response:**

```json
{
  "results": [
    {
      "entity_type": "spec_section",
      "id": "uuid",
      "title": "UTxO Transition Rule",
      "section_id": "shelley-ledger:rule-7.3",
      "era": "shelley",
      "subsystem": "ledger",
      "content_preview": "First 500 chars of extracted_rule...",
      "score": 0.87,
      "score_breakdown": {"bm25": 0.82, "vector": 0.91}
    }
  ],
  "total_count": 42,
  "offset": 0,
  "limit": 10
}
```

**Search targets by entity_type:**

| entity_type | Table | Text searched | Embedding column |
|------------|-------|--------------|-----------------|
| `spec` | spec_sections | extracted_rule | embedding |
| `spec_doc` | spec_documents | content_plain | embedding |
| `code` | code_chunks | embed_text | embedding |
| `issue` | github_issues | content_combined | embedding |
| `pr` | github_pull_requests | content_combined | embedding |
| `gap` | gap_analysis | delta + implications | embedding |
| `null` (all) | All of the above | — | — |

When `entity_type` is null, results from all tables are merged and ranked by RRF score.

### 2. `get_related`

Navigate the knowledge graph. Given an entity, follow cross_references to find everything linked to it. Automatically checks both directions (canonical + inverse).

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `entity_type` | string | required | Source entity type |
| `entity_id` | string | required | Source entity UUID |
| `relationship` | string | `null` | Filter by relationship type, or `null` for all |
| `target_type` | string | `null` | Filter by target entity type, or `null` for all |
| `limit` | int | 20 | Max results |
| `offset` | int | 0 | Skip first N |

**Response:**

```json
{
  "source": {
    "entity_type": "spec_section",
    "id": "uuid",
    "title": "UTxO Transition Rule",
    "section_id": "shelley-ledger:rule-7.3"
  },
  "results": [
    {
      "direction": "outgoing",
      "relationship": "implementedBy",
      "entity_type": "code_chunk",
      "id": "uuid",
      "title": "applyUTxOTransition",
      "module_name": "Cardano.Ledger.Shelley.Rules.Utxo",
      "repo": "cardano-ledger",
      "release_tag": "release/1.19.0",
      "confidence": 1.0,
      "notes": null
    },
    {
      "direction": "outgoing",
      "relationship": "discussedIn",
      "entity_type": "github_issue",
      "id": "uuid",
      "title": "UTxO validation edge case with datum hashes",
      "repo": "IntersectMBO/cardano-ledger",
      "issue_number": 1234,
      "confidence": 0.7,
      "notes": null
    }
  ],
  "total_count": 5,
  "offset": 0,
  "limit": 20
}
```

The `direction` field indicates whether this is from the canonical stored direction (`outgoing`) or the computed inverse (`incoming`). The `relationship` field shows the appropriate name for the direction (e.g., `implementedBy` for an inverse lookup of `implements`).

### 3. `find_similar`

Pure vector similarity search. Given raw text or an entity ID, find the most semantically similar entities. This is the "I wrote this code, which spec rule does it match?" tool.

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string | `null` | Raw text to embed and search (provide this OR entity_id) |
| `entity_type` | string | `null` | Source entity type (when using entity_id) |
| `entity_id` | string | `null` | Find things similar to this entity (provide this OR text) |
| `target_type` | string | `null` | Only search this entity type, or `null` for all |
| `era` | string | `null` | Filter by era |
| `subsystem` | string | `null` | Filter by subsystem |
| `limit` | int | 10 | Max results |
| `offset` | int | 0 | Skip first N |

**Response:**

```json
{
  "results": [
    {
      "entity_type": "spec_section",
      "id": "uuid",
      "section_id": "shelley-ledger:rule-7.3",
      "title": "UTxO Transition Rule",
      "content_preview": "...",
      "similarity": 0.94
    }
  ],
  "total_count": 25,
  "offset": 0,
  "limit": 10
}
```

### 4. `coverage`

Spec coverage dashboard. Shows which spec rules have implementations, tests, gaps, and discussions.

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `subsystem` | string | `null` | Filter by subsystem |
| `era` | string | `null` | Filter by era |
| `priority` | string | `null` | Filter by priority (critical, high, medium, low) |
| `show_uncovered` | bool | true | Include list of uncovered spec sections |
| `limit` | int | 50 | Max uncovered items to return |
| `offset` | int | 0 | Skip first N uncovered items |

**Response:**

```json
{
  "summary": {
    "total_sections": 847,
    "with_implementation": 312,
    "with_tests": 623,
    "with_gaps": 15,
    "with_discussions": 401,
    "uncovered": 89
  },
  "uncovered": [
    {
      "section_id": "shelley-ledger:rule-8.1",
      "title": "Delegation Certificate Validation",
      "era": "shelley",
      "subsystem": "ledger",
      "section_type": "rule",
      "missing": ["implementation", "tests"]
    }
  ],
  "total_uncovered": 89,
  "offset": 0,
  "limit": 50
}
```

### 5. `get_entity`

Fetch full details of a specific entity by UUID or human-readable identifier.

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `entity_type` | string | required | Entity type |
| `entity_id` | string | `null` | UUID (provide this OR a lookup field) |
| `section_id` | string | `null` | For spec_sections: human-readable ID like `shelley-ledger:rule-7.3` |
| `function_name` | string | `null` | For code_chunks: function name (returns latest tag) |
| `repo` | string | `null` | For code_chunks: narrow function lookup by repo |
| `include_relationships` | bool | true | Include cross-references |
| `rel_limit` | int | 20 | Max relationships to return |
| `rel_offset` | int | 0 | Skip first N relationships |

**Response:**

```json
{
  "entity": {
    "entity_type": "spec_section",
    "id": "uuid",
    "section_id": "shelley-ledger:rule-7.3",
    "title": "UTxO Transition Rule",
    "section_type": "rule",
    "era": "shelley",
    "subsystem": "ledger",
    "verbatim": "The full original spec text...",
    "extracted_rule": "The context-enriched extraction..."
  },
  "relationships": {
    "results": [
      {"direction": "outgoing", "relationship": "implementedBy", "entity_type": "code_chunk", "id": "uuid", "title": "applyUTxOTransition"},
      {"direction": "outgoing", "relationship": "discussedIn", "entity_type": "github_issue", "id": "uuid", "title": "..."}
    ],
    "total_count": 5,
    "offset": 0,
    "limit": 20
  }
}
```

### 6. `compare_versions`

Compare an entity across versions — function changes between tags, or spec rule evolution between eras.

**Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `entity_type` | string | required | `code` or `spec` |
| `function_name` | string | `null` | For code: function to compare |
| `section_id` | string | `null` | For spec: section to compare |
| `repo` | string | `null` | For code: which repo |
| `version_a` | string | required | Tag or era for version A |
| `version_b` | string | required | Tag or era for version B |
| `limit` | int | 50 | Max changed items (for broad queries) |
| `offset` | int | 0 | Skip first N |

**Response (code comparison):**

```json
{
  "entity_type": "code",
  "function_name": "applyBlock",
  "repo": "cardano-ledger",
  "version_a": "release/1.0",
  "version_b": "release/1.19.0",
  "status": "changed",
  "content_a": "function body at version A...",
  "content_b": "function body at version B...",
  "signature_a": "applyBlock :: ...",
  "signature_b": "applyBlock :: ..."
}
```

**Response (broad query — what changed between tags):**

```json
{
  "repo": "cardano-ledger",
  "version_a": "release/1.0",
  "version_b": "release/1.19.0",
  "added": [{"function_name": "...", "module_name": "...", "file_path": "..."}],
  "removed": [{"function_name": "...", "module_name": "...", "file_path": "..."}],
  "changed": [{"function_name": "...", "module_name": "...", "content_hash_a": "...", "content_hash_b": "..."}],
  "total_added": 120,
  "total_removed": 45,
  "total_changed": 230,
  "offset": 0,
  "limit": 50
}
```

---

## MCP Configuration

Registered in `.mcp.json` alongside CrystalDB:

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

## Key Files

| File | Purpose |
|------|---------|
| `src/vibe_node/mcp/search_server.py` | MCP server entry point |
| `src/vibe_node/mcp/tools/search.py` | `search` tool implementation |
| `src/vibe_node/mcp/tools/related.py` | `get_related` tool implementation |
| `src/vibe_node/mcp/tools/similar.py` | `find_similar` tool implementation |
| `src/vibe_node/mcp/tools/coverage.py` | `coverage` tool implementation |
| `src/vibe_node/mcp/tools/entity.py` | `get_entity` tool implementation |
| `src/vibe_node/mcp/tools/versions.py` | `compare_versions` tool implementation |
| `src/vibe_node/mcp/db.py` | Database connection pool for MCP |
| `src/vibe_node/mcp/embed.py` | Query embedding via Ollama |
