# Phase 0, Wave 2 — Ingestion & CLI

**Date:** 2026-03-14 — 2026-03-15
**Status:** Complete
**PRs:** #4, #6, #7

Wave 2 built the three ingestion pipelines (specs, code, GitHub issues/PRs), the full CLI, and proved the end-to-end ingest → embed → store → query flow.

---

## M0.3 — Spec Ingestion Pipeline

**Work Items:** 9/10 complete (remaining: write specs to docs/specs/ for mkdocs browsing)

### What We Built

A pipeline that converts Cardano specifications from 5 formats across 6 submodules into chunked, embedded, searchable documents in ParadeDB.

### Converters

| Format | Converter | Source |
|--------|-----------|--------|
| Markdown | Direct passthrough, strip frontmatter | Consensus design docs, CIPs |
| CDDL | Direct passthrough, chunk by rule definition | Binary schemas per era |
| LaTeX | pandoc with `--katex` flag | Formal specs (Shelley, Byron, Alonzo, network) |
| Literate Agda | Custom extractor (prose + code blocks) | Conway/Dijkstra specs |
| PDF | pymupdf4llm | Ouroboros academic papers |

### Schema Enhancements

- **Hierarchical titles:** `document_title`, `section_title`, `subsection_title` — not just a flat `title`
- **Reading order:** `prev_chunk_id` / `next_chunk_id` linked list within each document
- **Embed context:** `embed_text` field includes `Source: / File: / Document: / Section: / Subsection:` prefix for better embedding quality
- **Version tracking:** `commit_hash` and `commit_date` on every row; `--history` flag walks git log for versioned ingestion
- **Conversion cache:** `data/specs/` stores converted markdown keyed by `(repo, path, commit_hash)` — skip expensive re-conversions

### Issues Encountered

- **PaddleOCR doesn't support Python 3.14.** Replaced with pymupdf4llm — less accurate for complex equations but works everywhere.
- **pandoc HTML math wrappers.** Default `--to=markdown` wraps math in `<span class="math display">` with HTML entities (`&amp;` for `&`). Fixed with `--to=markdown-raw_html+tex_math_dollars --katex`.
- **`@{}` column specs in array environments** — unsupported by KaTeX. Post-processor strips them.
- **cardano-ledger pin uses old directory layout** (`shelley/chain-and-ledger/` not `eras/shelley/`). Source config maps actual paths at the pinned commit.
- **`--source` filter only matched `source_repo`**, missing era-based filtering. Fixed to match repo, era, and glob path.
- **Formal specs are under-tagged** — only 2 releases since 2023. Built commit-based version tracking via `git log` + `git show` (no checkout needed).

### CLI

```
vibe-node ingest specs [--format F] [--source S] [--limit N] [--history]
```

Research papers are auto-downloaded to `data/pdf/` on first `ingest specs` run.

---

## M0.4 — Code Indexing Pipeline

**Work Items:** 5/6 complete (remaining: Agda code indexing — built but not yet tested at scale)

### What We Built

A pipeline that walks release tags across 6 submodules, parses Haskell/Agda source with tree-sitter, embeds function-level chunks, and stores in ParadeDB.

### Parser Details

- **tree-sitter-haskell** for AST-aware parsing
- Extracts: `function`, `bind`, `signature`, `data_type`, `newtype`, `type_synomym` (grammar typo), `type_family`, `class`, `instance`, `deriving_instance`, `foreign_import`, `pattern_synonym`
- Groups multi-equation functions by name
- Associates type signatures with the following definition
- Module name from `header` node, fallback to file path
- **Agda parser** — regex-based extraction for `.agda` and `.lagda` files, handles literate code blocks with dedenting

### Era Inference

Maps module paths to Cardano eras:

| Pattern | Era |
|---------|-----|
| `Cardano.Ledger.Byron.*` | byron |
| `Cardano.Ledger.Shelley.*` | shelley |
| `Cardano.Ledger.Allegra.*` | allegra |
| `Cardano.Ledger.Mary.*` | mary |
| `Cardano.Ledger.Alonzo.*` | alonzo |
| `Cardano.Ledger.Babbage.*` | babbage |
| `Cardano.Ledger.Conway.*` | conway |
| `Ouroboros.Consensus.*` | consensus |
| `Ouroboros.Network.*` | network |
| `PlutusCore.*` | plutus |
| File path fallback | generic |

### Tag Filtering

| Repo | Pattern | Example Tags |
|------|---------|-------------|
| cardano-node | `^\d+\.\d+\.\d+$` | 1.0.0, 10.6.2 |
| cardano-ledger | `^cardano-ledger-spec-\|^release/` | release/1.19.0 |
| ouroboros-network | `^ouroboros-network-\d` | ouroboros-network-0.22.6.0 |
| plutus | `^\d+\.\d+\.\d+\.\d+$` | 1.59.0.0 |
| formal-ledger-specs | `^conway-v` | conway-v1.0 |

Excludes dev, pre-release, RC, sanchonet, and docker-specific tags.

### Issues Encountered

- **tree-sitter declarations node.** Top-level declarations are children of a `declarations` wrapper node, not direct children of root. Fixed by unwrapping.
- **Git checkout fails on dirty submodule.** After checking out old tags, the working tree is "dirty" relative to the pinned commit. Fixed with `--force` checkout.
- **Embed context for code.** Added `Codebase: / File: / Module: / Function:` prefix to `embed_text` for better retrieval quality.

### CLI

```
vibe-node ingest code [--repo R] [--limit N]
```

---

## M0.5 — Issues & PRs Ingestion

**Work Items:** 5/5 complete

### What We Built

GraphQL-based GitHub ingestion that fetches issues, PRs, and all discussion threads in bulk. ~100x fewer API calls than the original REST approach.

### Design Decisions

- **GraphQL over REST.** REST requires 1 API call per issue to get comments (14,000+ calls for cardano-node). GraphQL fetches 50 items with nested comments in one call (~100 calls total).
- **Full discussion threads.** The first post describes the problem; the comments contain the root cause analysis, workarounds, and design decisions. Capturing only the first post loses most of the value.
- **Three PR comment types.** `comment` (general), `review` (summary), `review_comment` (line-level with `file_path` and `diff_hunk`).
- **GITHUB_TOKEN required.** GraphQL API doesn't support unauthenticated access. CLI checks and fails early with clear instructions.

### Repos Tracked

IntersectMBO/cardano-node, cardano-ledger, ouroboros-network, ouroboros-consensus, plutus, formal-ledger-specifications, cardano-foundation/CIPs

### CLI

```
vibe-node ingest issues [--repo R] [--limit N]
```

---

## M0.8 — CLI Commands

**Work Items:** 4/4 complete

### Full Command Set

| Command | Description |
|---------|-------------|
| `vibe-node` | Show help |
| `vibe-node serve` | Start the node (stub) |
| `vibe-node infra up/down/status/logs` | Docker Compose management |
| `vibe-node ingest issues` | GitHub issues + PRs |
| `vibe-node ingest specs` | Spec documents (5 formats) |
| `vibe-node ingest code` | Haskell/Agda source |
| `vibe-node ingest fetch-papers` | Download Ouroboros papers |
| `vibe-node db status` | Table row counts |
| `vibe-node db reset` | Drop and recreate schema |
| `vibe-node db snapshot` | pg_dump to snapshots/ |
| `vibe-node db restore` | Restore from dump |
| `vibe-node db search` | Keyword search across all tables |

### Features

- **Rich progress bars** with ETA on all ingestion commands
- **`--limit` flag** on all ingest commands for fast testing
- **`--force` flag** on db reset for scripting
- **`.env` auto-loading** via dotenv
- **Help on bare commands** — `vibe-node`, `vibe-node db`, `vibe-node ingest`, `vibe-node infra` all show help instead of errors
- **`--rescan` flag** on `ingest issues` for updating existing items with new comments
- **`--history` flag** on `ingest specs` for versioned spec ingestion via git history
- **`db rebuild-manifest`** command to backfill code tag manifest from existing data

---

## Refinements After Initial Deployment

After completing the core pipelines, extensive refinement work addressed quality, performance, and completeness issues discovered during full-scale ingestion runs.

### Schema Improvements

- **Hierarchical titles for specs:** Replaced flat `title` with `document_title`, `section_title`, `subsection_title` plus `prev_chunk_id`/`next_chunk_id` for reading order
- **Embed text with context:** Added `embed_text` field that prepends structural context (Source/File/Document/Section for specs, Codebase/File/Module/Function for code)
- **Content-hash dedup for code:** Before embedding, checks if identical content exists at any previous tag — reuses embedding if so. Changed unique constraint from `(repo, tag, file, function, line_start)` to `(repo, tag, file, function, content_hash)` to avoid false duplicates when functions shift line positions
- **Code tag manifest:** New `code_tag_manifest` table records `(repo, tag, file, function, content_hash)` for every function at every tag. Enables versioned codebase queries: "what existed at version X", "when was function Y removed"

### GitHub Ingestion Optimizations

- Page size increased from 50 to 100 (halved API calls)
- In-memory set of ingested issue/PR numbers loaded upfront in one query
- `--rescan` mode: re-fetches everything but skips re-embedding if comment count unchanged
- All INSERTs use `ON CONFLICT DO UPDATE` for safe upserts
- HTTP timeout increased to 120s for large Plutus PR responses

### Additional Capabilities

- **Spec version tracking** via `--history` flag — walks git log for commits touching spec files, reads content via `git show` (no checkout)
- **Agda code indexing** — regex-based parser for `.agda`/`.lagda` files integrated into code ingestor
- **Research paper auto-download** — Ouroboros papers fetched from IACR ePrint on first `ingest specs` run
- **PaddleOCR Docker sidecar** — PDF-to-Mathpix-markdown via Python 3.13 container (PaddleOCR lacks 3.14 wheels)
- **Conversion cache** at `data/specs/` — skip expensive re-conversions on re-runs
- **Embedding retry** — 300s timeout + 2 retries on ReadTimeout for CPU Ollama

---

## Issues Encountered & Fixed

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| LaTeX KaTeX render errors | pandoc HTML math wrappers + escaped entities | `--katex` flag, `--to=markdown-raw_html`, post-processor |
| `section_index` error in CDDL chunker | Leftover field after schema change | Removed stale reference |
| Duplicate progress bar labels | Multiple sources share same repo+format | Added era to label |
| `--source shelley` matched nothing | Filter only checked `source_repo` | Extended to match era and glob |
| tree-sitter `declarations` wrapper | Functions inside wrapper node, not root children | Unwrap before iterating |
| Git checkout fails on dirty submodule | Working tree dirty from previous tag checkout | `--force` checkout |
| PaddleOCR Python 3.14 incompatible | No wheels for 3.14 | Docker sidecar with Python 3.13 |
| PaddleOCR OOM on full PDF | Loading all pages at once | Page-by-page processing via PyMuPDF |
| PaddleOCR deprecated API | `use_angle_cls`, `use_gpu`, `ocr()` all deprecated | Updated to `predict()` API |
| Embedding ReadTimeout | CPU Ollama slow on large code chunks | 300s timeout + 2 retries |
| Code duplicate rows on line shifts | Unique constraint included `line_start` | Changed to `content_hash` |
| `rebuild-manifest` duplicate key error | Same function name at different lines in one file | `ROW_NUMBER` dedup before insert |
| GitHub re-scan slow on ingested repos | Per-item SQL check for thousands of items | In-memory set loaded upfront |
| Tesseract OCR warning | pymupdf4llm tried OCR by default | Replaced with PaddleOCR sidecar |
