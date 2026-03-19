# Phase 1 — Research & Analysis

**Date:** 2026-03-17 — 2026-03-19
**Status:** Complete
**Version:** v0.1.0

Phase 1 used the knowledge base from Phase 0 to perform deep research into the Cardano specs and Haskell codebase. The output: a complete architectural design for the Python node, backed by 2,046 extracted spec rules, 1,567 QA-validated gaps, and 17,453 auto-generated test specifications.

---

## M1.1 — Subsystem Decomposition

Identified 10 node subsystems with boundaries, governing specs, inter-subsystem dependencies, and a phase-sequenced implementation plan.

| Subsystem | Haskell Package | Implementation Phase |
|-----------|----------------|---------------------|
| Serialization | cardano-ledger-binary | 2 |
| Networking / Multiplexer | network-mux, ouroboros-network-framework | 2 |
| Miniprotocols (N2N) | ouroboros-network-protocols | 2 |
| Miniprotocols (N2C) | ouroboros-network-protocols | 5 |
| Consensus | ouroboros-consensus | 4 |
| Ledger Rules | cardano-ledger eras/* | 3–4 |
| Plutus | plutus-core | 4 |
| Mempool | ouroboros-consensus (Mempool) | 5 |
| Storage | ouroboros-consensus (Storage) | 3 |
| Block Production | ouroboros-consensus + cardano-ledger | 5 |

---

## M1.2 — Public-Facing Documentation

Created 11 "How It Works" pages with custom SVG infographics explaining how a Cardano node works for non-technical audiences. Dual-audience approach: visuals for newcomers, surrounding text for developers.

---

## M1.3 — Cross-Referencing Infrastructure

Built the research pipeline infrastructure:

- **4 new database tables:** `spec_sections`, `cross_references`, `gap_analysis`, `test_specifications`
- **PydanticAI extraction pipeline:** 4-stage agent pipeline (extract rules → search code → evaluate links → analyze gaps) using Bedrock Opus for extraction and Sonnet for linking
- **QA validation pipeline:** Validates gaps by git-grepping vendor repos, categorizes severity (critical/important/informational/false_positive), runs concurrently with pool-per-task
- **CLI commands:** `vibe-node research extract-rules`, `vibe-node research qa-validate`
- **10-type relationship vocabulary:** implements, references, supersedes, derives_from, tests, documents, depends_on, related_to, part_of, version_of

### Issues Encountered

| Issue | Fix |
|-------|-----|
| PydanticAI API breaking changes (`result_type` → `output_type`) | Updated all agent definitions |
| FK violation on spec_sections upsert | Added `RETURNING id` to get actual DB ID |
| AWS Bedrock auth failures | Required `bedrock-runtime:*` IAM policy (separate from `bedrock:*`) |
| QA pipeline asyncpg "another operation in progress" | Changed from single connection to pool-per-task |
| QA pipeline UTF-8 decode crash on vendor repos | `errors="replace"` instead of `text=True` |
| Progress bars cross-contaminated between gap/xref phases | Pass explicit `task_id` instead of `task_ids[0]` |

---

## M1.4 — Spec Rule Extraction

Extracted 2,046 spec rules across all 10 subsystems using the PydanticAI pipeline:

| Subsystem | Rules |
|-----------|-------|
| Ledger | 490 |
| Storage | 345 |
| Networking | 337 |
| Serialization | 222 |
| Plutus | 182 |
| Block Production | 173 |
| Consensus | 149 |
| Mempool | 76 |
| Miniprotocols (N2N) | 71 |
| Miniprotocols (N2C) | 1 |

---

## M1.5 — Haskell Code & Discussion Mapping

The extraction pipeline simultaneously produced cross-references and gap analysis entries:

- **7,152 cross-references** linking spec rules to Haskell functions and GitHub discussions
- **1,567 gap analysis entries** documenting spec-vs-Haskell divergences
- **All gaps QA-validated:** 425 critical, 427 important, 693 informational, 22 false positives

### Key Findings from Gap Analysis

- **Duplicate PlutusMap keys:** Haskell preserves duplicates, Python cbor2 drops them. Consensus-critical (VNODE-151).
- **CBOR indefinite-length encoding:** Spec doesn't mention it, Haskell handles it. Must support for block decode.
- **Bimap for delegation:** Haskell enforces injectivity (one-to-one) where spec allows many-to-one.
- **Per-era type differences:** Haskell uses concrete tuples where spec uses abstract types.

---

## M1.6 — Library Audit

Evaluated Python libraries for each subsystem:

| Library | Verdict | Use For |
|---------|---------|---------|
| **pycardano** | USE | CBOR serialization, transaction types, Ed25519 crypto |
| **uplc** | USE | Plutus Core evaluation, cost model, flat encoding (87 builtins, 811 conformance tests) |
| **PyArrow** | USE | Hot storage (Arrow tables + dict index) |
| **DuckDB** | USE | Analytics layer (zero-copy over Arrow) |
| **cryptography** | USE | Blake2b hashing, KES primitives |
| **asyncio** | USE | Networking (stdlib) |

**Key decision:** Promoted pycardano from REUSE to USE — it already wraps cbor2 and PyNaCl with Cardano-specific logic. Contribute back improvements rather than reimplementing.

**uplc discovery:** Initially assessed as BUILD. Research revealed it implements all 87 builtins through Conway/PlutusV3 with full cost model and 811 conformance tests. Promoted to USE with performance acceleration plan (Cython → Rust if needed).

---

## M1.7 — Data Architecture

Benchmarked 5 storage candidates at 1M UTxOs:

| Engine | Lookup (μs/op) | Block Apply (ms/block) | Disk |
|--------|---------------|------------------------|------|
| **Arrow+Dict** | **0.23** | **0.37** | **176 MiB** |
| Arrow+NumPy | 1.74 | 1.12 | 176 MiB |
| LMDB | 2.12 | 31.85 | 322 MiB |
| SQLite | 3.88 | 38.37 | 274 MiB |

**Selected:** Arrow+Dict — 9x faster lookups and 86x faster block apply vs LMDB (Haskell's approach). DuckDB queries Arrow tables with zero copy for analytics.

**Mainnet projection:** ~4.4 GiB total vs Haskell's 24 GiB recommended.

Also designed: Mithril snapshot import pipeline, crash recovery via Arrow IPC snapshots + diff replay log, rollback mechanics with bounded diff deque.

---

## M1.8 — Test Strategy & Specifications

Defined a 5-type test taxonomy with 17,453 auto-generated test specifications:

| Type | Count | Tooling | When |
|------|-------|---------|------|
| Unit | 10,921 | pytest | Every commit |
| Property | 3,670 | Hypothesis | Every commit |
| Conformance | 1,047 | pytest + Ogmios | Pre-merge + nightly |
| Integration | 354 | Docker Compose | Pre-merge |
| Replay | 17 | Mithril snapshots | Weekly + release |

Three parallel test tracks matching the implementation roadmap. Antithesis/Moog integration planned for property tests.

---

## M1.9 — Architecture Blueprint

Synthesized all Phase 1 research into a Phase 2–6 implementation roadmap:

- **3 parallel tracks:** Networking (A), Ledger (B), Storage (C) — converging at integration points
- **Per-subsystem implementation plans** with library choices, critical gap counts, and risk levels
- **Acceptance criteria mapping:** all 9 challenge criteria traced to specific phase deliverables
- **Risk register:** 8 top risks including Plutus performance, CBOR fidelity, memory at 15M UTxOs
- **Dependency risk table** for all external libraries with mitigations

---

## Monorepo Restructure

Restructured the repo into a uv workspace monorepo:

```
packages/
  vibe-core/      → vibe.core (protocol-agnostic abstractions)
  vibe-cardano/   → vibe.cardano (Cardano-specific implementations)
  vibe-tools/     → vibe.tools (development infrastructure)
src/vibe_node/    → Node binary (CLI only)
tests/
  unit/           → 12 tests passing
  property/       → (Phase 2)
  conformance/    → (Phase 2)
  integration/    → (Phase 2)
```

All imports rewritten from `vibe_node.X` to `vibe.tools.X`. Uses hatchling build backend for implicit namespace packages (PEP 420).

---

## Documentation Reorganization

Reorganized the MkDocs nav:

- **Development tab:** Architecture blueprint, data architecture, library audit, package structure, test strategy, test matrix, subsystem pages, devlog
- **Reference tab:** CLI reference, database schema, development workflow, pipelines

Rule: Development = design decisions and plans. Reference = how to use things.

Merged Phase 0 devlog waves (1, 2, 3) into a single page.
