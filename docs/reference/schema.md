# Database Schema

!!! info "License: CC-BY-SA-4.0"
    The **contents** of the database (spec extractions, cross-references, test specifications, embeddings, and all other data produced by the ingestion pipelines) are licensed under [Creative Commons Attribution-ShareAlike 4.0 International](https://github.com/SteelSwap/vibe-node/blob/main/LICENSE-DATA). If you redistribute or build upon the database contents, you must provide attribution to SteelSwap and share under the same or a compatible license. The database schema definitions and source code remain under [AGPL-3.0](https://github.com/SteelSwap/vibe-node/blob/main/LICENSE).

ParadeDB (PostgreSQL 17) with pg_search (BM25) and pgvector extensions. All tables use `vector(1536)` for Jina Code 1.5B embeddings.

## Tables

### spec_documents

Converted spec content with version history. The same spec file may have multiple rows at different commits.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| document_title | varchar(512) | Top-level document name |
| section_title | varchar(512) | h2 heading (nullable) |
| subsection_title | varchar(512) | h3 heading (nullable) |
| prev_chunk_id | uuid | Previous chunk in reading order |
| next_chunk_id | uuid | Next chunk in reading order |
| source_repo | varchar(256) | e.g. "IntersectMBO/cardano-ledger" |
| source_path | varchar(1024) | File path within repo |
| era | varchar(32) | byron, shelley, conway, multi-era, etc. |
| spec_version | varchar(64) | Tag name or commit hash prefix |
| commit_hash | varchar(40) | Git commit SHA |
| commit_date | timestamptz | When committed |
| content_markdown | text | Markdown with math notation |
| content_plain | text | Stripped text for BM25 |
| embed_text | text | Hierarchical context + content for embedding |
| embedding | vector(1536) | Jina Code 1.5B |
| chunk_type | varchar(32) | section, schema, agda, definition, rule |
| content_hash | varchar(64) | SHA256 for deduplication |

### code_chunks

Function-level Haskell/Agda source indexed per release tag.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| repo | varchar(256) | e.g. "cardano-node" |
| release_tag | varchar(64) | e.g. "10.6.2" |
| commit_hash | varchar(40) | |
| commit_date | timestamptz | |
| file_path | varchar(1024) | |
| module_name | varchar(512) | e.g. "Cardano.Ledger.Alonzo.Rules" |
| function_name | varchar(256) | |
| line_start | integer | |
| line_end | integer | |
| content | text | Source code |
| signature | text | Type signature (nullable) |
| embed_text | text | Codebase/File/Module/Function context + content |
| embedding | vector(1536) | |
| content_hash | varchar(64) | SHA256 of content for dedup across versions |
| era | varchar(32) | Inferred from module path |

**Unique:** (repo, release_tag, file_path, function_name, content_hash)

### code_tag_manifest

Tracks which functions exist at each release tag. Enables versioned codebase queries: "what existed at version X", "when was function Y added/removed", "what changed between X and Y".

| Column | Type | Description |
|--------|------|-------------|
| repo | varchar(256) PK | |
| release_tag | varchar(64) PK | |
| file_path | varchar(1024) PK | |
| function_name | varchar(256) PK | |
| content_hash | varchar(64) | Links to code_chunks via content_hash |

**Primary Key:** (repo, release_tag, file_path, function_name)

**Key queries:**
- Full codebase at version: `WHERE release_tag = 'X'`
- Track function: `WHERE function_name = 'applyBlock' ORDER BY release_tag`
- What changed: diff content_hash sets between two tags
- Get code: join to code_chunks on content_hash

### github_issues

Issues with full discussion threads.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| repo | varchar(256) | |
| issue_number | integer | |
| title | varchar(512) | |
| body | text | First post |
| state | varchar(16) | open, closed |
| labels | varchar[] | |
| created_at / closed_at / updated_at | timestamptz | |
| author | varchar(128) | |
| comment_count | integer | |
| content_combined | text | Title + body + all comments |
| embedding | vector(1536) | |
| linked_prs | varchar[] | |

### github_issue_comments

Individual comments for fine-grained search.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| issue_id | uuid FK | → github_issues |
| comment_id | bigint | GitHub comment ID |
| author | varchar(128) | |
| body | text | |
| embedding | vector(1536) | |

### github_pull_requests

PRs with review discussions, merge status, and branch info.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| repo | varchar(256) | |
| pr_number | integer | |
| title / body / state | | |
| merged | boolean | |
| merge_commit_sha | varchar(40) | |
| base_branch / head_branch | varchar(256) | |
| comment_count / review_comment_count | integer | |
| content_combined | text | Full discussion |
| embedding | vector(1536) | |

### github_pr_comments

General comments, review summaries, and line-level review comments.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| pr_id | uuid FK | → github_pull_requests |
| comment_type | varchar(32) | "comment", "review", "review_comment" |
| file_path | varchar(1024) | For line-level reviews |
| diff_hunk | text | Code context for reviews |
| embedding | vector(1536) | |

## Phase 1: Cross-Referencing Tables

### spec_sections

Atomic unit of spec traceability — one rule, definition, or equation. Produced by the PydanticAI extraction pipeline. More granular than `spec_documents` (which are optimized for search).

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| spec_chunk_id | uuid FK | → spec_documents (parent chunk) |
| section_id | text | Stable ID like `shelley-ledger:rule-utxo-transition` |
| title | text | Human-readable title |
| section_type | text | rule, definition, equation, type, figure, algorithm |
| era | text | byron, shelley, ..., conway |
| subsystem | text | networking, ledger, consensus, etc. |
| verbatim | text | Exact spec text |
| extracted_rule | text | Context-enriched, self-contained description |
| embedding | vector(1536) | Generated from extracted_rule |

Unique constraint: `(spec_chunk_id, title)`

### cross_references

Links any two entities in the knowledge base. 10 relationship types borrowed from W3C PROV-O, Dublin Core, SPDX, OSLC RM. Inverses computed at query time, not stored.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| source_type | text | spec_section, code_chunk, github_issue, github_pr, gap_analysis |
| source_id | uuid | |
| target_type | text | Same enum as source_type |
| target_id | uuid | |
| relationship | text | See vocabulary below |
| confidence | float | 1.0 = manual, 0.5-0.7 = pipeline |
| notes | text | Optional context |
| created_by | text | manual, agent, pipeline |

**Relationship vocabulary:**

| Relationship | Inverse (query-time) | Semantics |
|---|---|---|
| `implements` | `implementedBy` | Code fulfills a spec rule |
| `tests` | `testedBy` | Test verifies an artifact |
| `discusses` | `discussedIn` | Issue/PR discusses an artifact |
| `references` | `referencedBy` | A cites or points to B |
| `contradicts` | `contradictedBy` | A conflicts with B |
| `extends` | `extendedBy` | A adds capability on top of B |
| `derivedFrom` | `derivationOf` | B was produced by transforming A |
| `supersedes` | `supersededBy` | A replaces B |
| `requires` | `requiredBy` | A needs B to function |
| `trackedBy` | `tracks` | B governs resolution of A |

### test_specifications

Test knowledge base — describes what should be tested and how. Not a state tracker.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| spec_section_id | uuid FK | → spec_sections |
| subsystem | text | |
| test_type | text | unit, property, replay, conformance, integration |
| test_name | text | Descriptive name |
| description | text | What the test verifies |
| hypothesis_strategy | text | For property tests: generators, value ranges |
| priority | text | critical, high, medium, low |
| phase | text | phase-2, phase-3, etc. |

Unique constraint: `(spec_section_id, test_name)`

### gap_analysis

Structured spec-vs-implementation divergences. Queryable version of gap analysis entries.

| Column | Type | Description |
|--------|------|-------------|
| id | uuid PK | |
| spec_section_id | uuid FK | → spec_sections |
| subsystem | text | |
| era | text | |
| spec_says | text | What the spec defines |
| haskell_does | text | What the Haskell node does |
| delta | text | The specific difference |
| implications | text | How this affects our implementation |
| discovered_during | text | Which phase/task |
| code_chunk_id | uuid FK | → code_chunks (optional) |
| embedding | vector(1536) | |

Unique constraint: `(spec_section_id, delta)`
