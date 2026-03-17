# Development Log

The development log captures the journey — what we built, what we tried, what failed, and what we learned. Radical transparency means the dead ends get documented too.

Each entry is organized by phase and wave, with specific module and work item details.

---

## Phase 0: Development Architecture

- **[Wave 1 — Foundation](phase0-wave1.md)** (M0.1, M0.2, M0.9)
    - Docker Compose stack, git submodules, database schema, documentation site
- **[Wave 2 — Ingestion & CLI](phase0-wave2.md)** (M0.3, M0.4, M0.5, M0.8)
    - Spec ingestion, code indexing, GitHub issues/PRs, CLI commands, refinements & fixes
- **[Wave 3 — Search Infrastructure & MCP](phase0-wave3.md)** (M0.6, M0.7)
    - BM25/HNSW indexes, composable search templates (BM25/vector/RRF), cross-table fusion, 6-tool FastMCP server, CrystalDB integration
