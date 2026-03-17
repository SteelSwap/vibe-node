# Database Schema

!!! info "License: CC-BY-SA-4.0"
    The **contents** of the database (spec extractions, cross-references, test specifications, embeddings, and all other data produced by the ingestion pipelines) are licensed under [Creative Commons Attribution-ShareAlike 4.0 International](../LICENSE-DATA). If you redistribute or build upon the database contents, you must provide attribution to SteelSwap and share under the same or a compatible license. The database schema definitions and source code remain under [AGPL-3.0](../LICENSE).

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
