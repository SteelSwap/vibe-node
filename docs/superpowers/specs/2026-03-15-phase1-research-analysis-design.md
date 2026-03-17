# Phase 1: Research & Analysis — Design Spec

**Goal:** Understand the full structure of a Cardano node from specs, map it to the Haskell reference implementation, identify Python libraries, design a test strategy, and produce both public-facing and technical documentation — all before writing any node code.

**Architecture:** Interleaved approach — subsystem decomposition first (establishes vocabulary and structure), then cross-referencing infrastructure (provides tooling), then module-level research populating everything together. Research scales with implementation: Phase 1 covers subsystem + module level; each subsequent implementation phase starts with function-level research for its scope.

**Assumes:** Phase 0 complete, including M0.6 (BM25/HNSW indexes, RRF fusion) and M0.7 (Search MCP, CrystalDB MCP).

---

## 1. Subsystem Decomposition

Break the Cardano node into ~10 major subsystems, each with clear boundaries, governing specs, and inter-subsystem dependencies.

### Subsystems

| # | Subsystem | What It Does | Primary Specs |
|---|-----------|-------------|---------------|
| 1 | **Networking / Multiplexer** | TCP connections, Ouroboros multiplexer, bearer abstraction | ouroboros-network design docs, network spec |
| 2 | **Miniprotocols (Node-to-Node)** | Chain-sync, block-fetch, tx-submission, keep-alive state machines | ouroboros-network miniprotocol specs |
| 3 | **Miniprotocols (Node-to-Client)** | Local chain-sync, local tx-submission, local state-query, local tx-monitor | ouroboros-network local protocol specs |
| 4 | **Consensus / Ouroboros Praos** | Leader election, VRF/KES, tip selection, chain growth | Ouroboros Praos/Genesis papers, ouroboros-consensus design docs |
| 5 | **Ledger Rules** | UTxO transitions, delegation, governance, multi-era support (Byron-Conway) | cardano-ledger formal specs per era, formal-ledger-specs (Agda) |
| 6 | **Plutus / Script Evaluation** | Plutus Core interpreter, cost models, script validation | plutus specs, cost model docs |
| 7 | **CBOR / Serialization** | Binary encoding/decoding for blocks, transactions, protocol messages | CDDL schemas per era |
| 8 | **Mempool** | Transaction staging, validation, capacity management | ouroboros-consensus mempool design docs |
| 9 | **Storage** | Persistent chain state, immutable DB, volatile DB, ledger snapshots | ouroboros-consensus storage layer docs |
| 10 | **Block Production / Forge** | Block assembly, header creation, leader schedule | Consensus + ledger specs combined |

### Inter-Subsystem Dependencies

```
Serialization (7) <- needed by everything
Networking (1) <- Miniprotocols N2N (2) + N2C (3)
Miniprotocols (2) <- Consensus (4), Storage (9)
Ledger Rules (5) <- Plutus (6)
Consensus (4) <- Mempool (8), Block Production (10)
Storage (9) <- Ledger Rules (5), Consensus (4)
```

### Implementation Phase Sequencing

Each phase adds a testable capability against the running Haskell node:

| Phase | Subsystems | Testable Capability |
|-------|-----------|-------------------|
| **Phase 2** | Serialization + Networking + Chain-Sync | Do we decode blocks and sync headers correctly? |
| **Phase 3** | Block Fetch + Storage + Ledger Rules (Byron-Mary only, no Plutus scripts) | Do we validate blocks the same as Haskell? |
| **Phase 4** | Consensus + Mempool + Tx Submission | Do we agree on tip selection? |
| **Phase 5** | Plutus + Block Production + N2C protocols + Alonzo-Conway ledger validation | Do we produce valid blocks? |
| **Phase 6** | Hardening | Power-loss recovery, memory optimization, 10-day soak |

Phase 3 covers pre-Alonzo ledger validation (Byron through Mary eras) where no Plutus script evaluation is needed. Alonzo+ script validation is deferred to Phase 5 when the Plutus subsystem is built.

Each implementation phase begins with function-level research for its subsystems before any code is written.

---

## 2. Cross-Referencing Infrastructure

Three new database tables that make the research queryable and enable spec coverage analysis.

### Migration Strategy

New tables are added to `infra/db/init.sql` using `CREATE TABLE IF NOT EXISTS`, consistent with the existing schema management approach. This is idempotent — safe to re-run on existing databases without data loss. The `vibe-node db status` command must be updated to include the three new tables in its row count output.

### `spec_sections` — Atomic Unit of Traceability

One row = one spec rule, definition, equation, or type declaration. More granular than `spec_documents` chunks (which are optimized for search). Produced by semantic rule extraction during research.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | uuid PK | |
| `spec_chunk_id` | uuid FK -> spec_documents | Parent chunk this was extracted from |
| `section_id` | text | Stable human-readable identifier (e.g., `shelley-ledger:rule-7.3`) |
| `title` | text | Descriptive name (e.g., "UTxO Transition Rule") |
| `section_type` | text | `rule`, `definition`, `equation`, `type`, `figure`, `algorithm` |
| `era` | text | byron, shelley, allegra, mary, alonzo, babbage, conway, cross-era |
| `subsystem` | text | One of the 10 subsystems |
| `verbatim` | text | Exact spec text for attribution and traceability |
| `extracted_rule` | text | Context-enriched semantic extraction — self-contained description including referenced definitions and types needed to understand the rule |
| `embedding` | vector(1536) | Generated from `extracted_rule` via existing `EmbeddingClient` |
| `metadata` | jsonb | Equation numbers, page refs, etc. |

**Expected scale:** Estimated 500-2000 spec rules across all eras and subsystems. Phase 1 aims for comprehensive extraction across all subsystems at the rule level (not every sub-clause or edge case — those are captured during function-level research in implementation phases).

**Extraction process:** A semi-automated pipeline where Agent Millenial reads spec chunks (via Search MCP or `db search`), identifies individual rules/definitions/equations, and produces structured extractions. The pipeline:

1. Queries `spec_documents` by subsystem/era
2. For each chunk, identifies discrete rules/definitions/equations
3. Produces **verbatim** (exact spec text) and **extracted_rule** (context-enriched, self-contained)
4. Generates embedding from `extracted_rule` via existing `EmbeddingClient`
5. Stores in `spec_sections` with stable `section_id`

This is interactive work guided by Agent Millenial, not a fully automated batch job — the extraction requires understanding mathematical notation, cross-references between spec sections, and domain context.

### `cross_references` — Link Table

Connects any two entities in the knowledge base.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | uuid PK | |
| `source_type` | text | `spec_section`, `code_chunk`, `github_issue`, `github_pr`, `gap_analysis` |
| `source_id` | uuid | |
| `target_type` | text | Same enum as source_type |
| `target_id` | uuid | |
| `relationship` | text | See Relationship Vocabulary below |
| `confidence` | float | Manual = 1.0, auto-detected = lower |
| `notes` | text | Optional context |
| `created_by` | text | `manual`, `agent`, `heuristic` |

**Type-to-table mapping:**

| `source_type` / `target_type` | Database Table |
|-------------------------------|---------------|
| `spec_section` | `spec_sections` |
| `code_chunk` | `code_chunks` |
| `github_issue` | `github_issues` |
| `github_pr` | `github_pull_requests` |
| `gap_analysis` | `gap_analysis` |

### Relationship Vocabulary

10 canonical relationship types, borrowing from W3C PROV-O, Dublin Core, SPDX, and OSLC RM where formal semantics exist. Inverses are computed at query time, never stored.

| Relationship | Inverse (query-time) | Source Ontology | Semantics |
|---|---|---|---|
| `implements` | `implementedBy` | — | Code fulfills a spec rule |
| `tests` | `testedBy` | — | A test verifies an artifact |
| `discusses` | `discussedIn` | — | Issue/PR has discussion about an artifact |
| `references` | `referencedBy` | — | A cites or points to B |
| `contradicts` | `contradictedBy` | — | A conflicts with B |
| `extends` | `extendedBy` | — | A adds capability/detail on top of B |
| `derivedFrom` | `derivationOf` | PROV-O | B was produced by transforming A |
| `supersedes` | `supersededBy` | PROV-O + Dublin Core | A replaces B (directional, temporal) |
| `requires` | `requiredBy` | Dublin Core + SPDX | A needs B to function or be understood |
| `trackedBy` | `tracks` | OSLC RM | B governs resolution/evolution of A |

**Canonical direction conventions** (only the canonical direction is stored):

- `implements`: code_chunk → spec_section
- `tests`: test_specification → spec_section or code_chunk
- `discusses`: github_issue/pr → spec_section, code_chunk, or gap_analysis
- `references`: any → any
- `contradicts`: gap_analysis or spec_section → spec_section or code_chunk
- `extends`: spec_section → spec_section (child → parent)
- `derivedFrom`: gap_analysis, code_chunk → spec_section, code_chunk
- `supersedes`: spec_section, code_chunk → spec_section, code_chunk (new → old)
- `requires`: spec_section, code_chunk → spec_section, code_chunk (dependent → dependency)
- `trackedBy`: gap_analysis, spec_section → github_issue, github_pr

### Semantic Search + Relationship Workflow

The knowledge base combines **embedding vectors** (for semantic similarity) with **typed relationships** (for structural connections). This enables two powerful patterns:

**Pattern 1: Code → Spec discovery.** "I wrote this function — which spec rule does it fulfill?" Embed the function's code, vector search against `spec_sections.extracted_rule` embeddings. Top results are candidate spec rules. Agent reviews and stores confirmed links as `cross_references` with relationship `implements`.

**Pattern 2: Spec → Code discovery.** "I need to implement this spec rule — how does Haskell do it?" Embed the `extracted_rule`, vector search against `code_chunks.embed_text`. Top results are the Haskell functions most likely implementing it.

**Pattern 3: Imprecise investigation.** "Our validation disagrees on fee calculation — what's relevant?" Embed the problem description, search across ALL tables (specs, code, issues, gaps). Return results ranked by semantic similarity, grouped by entity type, with known relationships highlighted.

During Phase 1 research, the workflow is:
1. Vector search proposes candidate links (semantic similarity)
2. Agent reviews and confirms matches
3. Confirmed links stored as `cross_references` with appropriate relationship type and `confidence = 1.0`
4. Auto-detected links stored with `confidence = 0.5-0.7` and `created_by = 'agent'`

The MCP Search tool combines both modes: query by text (embedded for vector search), filter by entity type and relationship type, return results with both similarity scores and known relationships.

### `test_specifications` — Test Knowledge Base

Describes *what should be tested* and *how* for each spec rule. This is a knowledge base, not a state tracker — it does not record whether tests are implemented, passing, or failing. That state belongs in CI/pytest.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | uuid PK | |
| `spec_section_id` | uuid FK -> spec_sections | What spec rule this tests |
| `subsystem` | text | Which subsystem |
| `test_type` | text | `unit`, `property`, `replay`, `conformance`, `integration` |
| `test_name` | text | Descriptive name |
| `description` | text | What the test verifies |
| `hypothesis_strategy` | text | For property tests: value ranges, generators, invariants |
| `priority` | text | `critical`, `high`, `medium`, `low` |
| `phase` | text | Which implementation phase this belongs to |
| `metadata` | jsonb | Flexible |

### `gap_analysis` — Spec-vs-Implementation Divergences

Created during Phase 1 cross-referencing when divergences between spec and Haskell implementation are discovered. Structured version of the markdown entries in `docs/specs/gap-analysis.md`, making gaps queryable and cross-referenceable.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | uuid PK | |
| `spec_section_id` | uuid FK -> spec_sections | Which spec rule diverges |
| `subsystem` | text | Which subsystem |
| `era` | text | Which era this applies to |
| `spec_says` | text | What the spec defines |
| `haskell_does` | text | What the Haskell node actually implements |
| `delta` | text | The specific difference |
| `implications` | text | How this affects our implementation |
| `discovered_during` | text | Which phase/task uncovered this |
| `code_chunk_id` | uuid FK -> code_chunks | The Haskell function exhibiting the divergence |
| `metadata` | jsonb | Flexible |

### CLI Additions

| Command | Purpose |
|---------|---------|
| `vibe-node db xref add` | Add a cross-reference |
| `vibe-node db xref query` | Query cross-references by entity |
| `vibe-node db coverage` | Show spec sections with/without tests and implementations |
| `vibe-node db test-specs` | List/filter planned tests |

The **coverage command** is the key analytical tool — it answers "which spec rules are untested?", "which have no matching implementation?", and "where is testing too narrow?" directly.

---

## 3. Library Audit

For each subsystem, evaluate Python library candidates against:

| Criterion | What We Check |
|-----------|--------------|
| **Requirement coverage** | What % of the subsystem's needs does it handle? |
| **Maintenance health** | Last commit, release cadence, open issues, bus factor |
| **License** | Compatible with AGPL-3.0? |
| **Quality** | Test coverage, documentation, type hints, API design |
| **Performance** | Known bottlenecks? Memory profile? |
| **Gaps** | What's missing that we'd need to build or contribute? |

### Decision Framework

1. **Well-maintained + covers majority of needs** -> `USE` as dependency, contribute upstream for gaps
2. **Poorly maintained or partial coverage** -> `FORK` or `REUSE` code with attribution (license permitting)
3. **Nothing suitable** -> `BUILD` from spec
4. **Never compromise quality to reduce work**

### Known Candidates (Starting List)

| Subsystem | Candidates |
|-----------|-----------|
| Serialization | `cbor2`, `pycardano` (CBOR layer) |
| Networking | `asyncio` (stdlib), `trio`, raw sockets |
| Crypto | `PyNaCl`, `cryptography`, `pycardano` (crypto primitives), VRF libraries |
| Ledger | `pycardano` (transaction model, address handling) |
| Plutus | `uplc`, `aiken` (Python bindings?), or build from spec |
| Data Architecture | `duckdb`, `pyarrow`, or traditional KV stores |

M1.6 evaluates libraries at the **subsystem level** using requirements from M1.1's decomposition. Rule-level library mapping (which specific spec rules a library covers) happens during function-level research at the start of each implementation phase.

Research will uncover additional candidates. Each subsystem gets a dedicated evaluation page in the docs.

---

## 4. Data Architecture

Elevated beyond simple "storage library" evaluation. The data architecture determines whether we meet the memory requirement (pass/fail criterion).

### Hypothesis: Arrow/DuckDB/Feather Stack

| Component | Role |
|-----------|------|
| **Apache Arrow** | In-memory columnar format for ledger state (UTxO set, delegation map, stake distribution) |
| **DuckDB** | Query engine over Arrow tables — zero-copy, columnar, embedded |
| **Feather/IPC files** | On-disk format for immutable chain data (append-only, maps to Haskell's ImmutableDB concept) |

### Evaluation Criteria

This stack must be evaluated against the actual data access patterns of a Cardano node:

- UTxO lookups by address and transaction ID
- Stake distribution snapshots at epoch boundaries
- Block append (immutable DB)
- Rollback (volatile DB — revert N blocks)
- Ledger state snapshots for crash recovery
- Memory footprint under steady-state sync

The library audit for storage compares this stack against traditional approaches (LMDB, RocksDB, SQLite) on these specific access patterns.

### Deliverable

A dedicated docs page at `docs/reference/data-architecture.md` with:

- Benchmark results for each access pattern
- Memory profile comparisons
- Build/use/fork decision with rationale
- Cross-references in the DB linking the decision to relevant spec sections (storage layer, crash recovery)

---

## 5. Test Strategy

### Test Taxonomy

| Type | Tool | What It Catches |
|------|------|----------------|
| **Unit** | pytest | Concrete input/output correctness — mirrors Haskell tests |
| **Property** | Hypothesis | Spec invariant violations across value ranges and edge cases |
| **Historical Replay** | pytest + Ogmios/chain data | Regression against real mainnet transaction history |
| **A/B Conformance** | Hypothesis + both nodes | Behavioral divergence on synthetic inputs |
| **Integration** | pytest + Docker Compose | End-to-end subsystem interaction |

### Unit Tests (pytest, mirroring Haskell)

For each Haskell test identified during research, plan a corresponding Python test. Cross-references link: `haskell_test -> spec_section -> planned_python_test`.

Concrete input/output tests: "given this block, validation should succeed/fail for this reason."

### Property-Based Tests (Hypothesis, capturing spec invariants)

For each spec rule, define:

- **The property** — what invariant the spec requires (e.g., "total ADA is conserved across a valid transaction")
- **The strategy** — value ranges and generators for valid/invalid inputs (e.g., "transaction values between 0 and 45B lovelace")
- **The boundary conditions** — where the spec defines edges (e.g., "exactly at max transaction size", "exactly at epoch boundary")

### Historical Replay Tests

Pull actual historical blocks/transactions from the Haskell node (via Ogmios or chain data) and replay through our validation. Every transaction the Haskell node accepted must pass our validation. Provides millions of real-world test cases.

### A/B Conformance Tests

Generate synthetic transactions (valid and intentionally invalid) via Hypothesis and submit to both nodes. Compare results:

- Both accept -> pass
- Both reject with same reason -> pass
- Disagree -> found a divergence (investigate)

Hypothesis shrinks on disagreement to find minimal failing case.

### Coverage Analysis

The `vibe-node db coverage` command serves as the testing dashboard:

- Spec sections with no planned tests -> testing gaps
- Spec sections with planned tests but no Haskell test equivalent -> potential spec-vs-implementation divergence
- Spec sections with Haskell tests but no property tests -> narrow test coverage
- Spec sections with no implementation cross-reference -> untested spec territory

---

## 6. Two-Tier Documentation

### Tier 1: "How a Cardano Node Works" (Non-Technical)

For people who use Cardano but don't write code. Each subsystem gets a page with:

- **SVG infographic** as the primary content — visual-first explanation
- **Plain language description** — what this subsystem does and why it matters
- **Tie-ins to familiar concepts** — where staking, transactions, governance touch the node
- **No code, no spec references** — those belong in Tier 2

Lives under a dedicated section in the docs nav.

### Tier 2: Architecture Blueprint (Technical)

For developers following the build. Each subsystem gets a page with:

- **Spec reference map** — which specs govern this subsystem, specific sections
- **Module decomposition** — components within the subsystem (e.g., Subsystem 7 "Serialization" decomposes into: CBOR codec, CDDL validation, era-specific encoders, block decoder)
- **Data flow diagram** (Mermaid) — how data moves through modules
- **Haskell structure notes** — how the reference implementation organizes this
- **Library recommendations** — build/use/fork decisions with rationale
- **Test strategy summary** — test types, key properties to verify
- **Phase assignment** — when this gets implemented

Both tiers use the same subsystem names so readers can navigate between them.

---

## 7. Gap Analysis Integration

Per CLAUDE.md's Spec Consultation Discipline, when cross-referencing during M1.5 reveals divergences between specs and the Haskell implementation, gap analysis entries are created in `docs/specs/gap-analysis.md` using the standard format:

```markdown
## [Subsystem] — [Brief description of divergence]

**Spec reference:** [Document, section, page/equation number]
**Era:** [Which era this applies to]
**Spec says:** [What the spec defines]
**Haskell does:** [What the Haskell node actually implements]
**Delta:** [The specific difference]
**Implications:** [How this affects our implementation]
**Discovered during:** Phase 1, M1.5 — Haskell Code & Discussion Mapping
```

Gap discovery during research is a valuable Phase 1 output — it identifies where we need to follow the Haskell node's behavior rather than the spec.

---

## 8. Modules & Waves

### Modules

| Module | Name | Description |
|--------|------|-------------|
| **M1.1** | Subsystem Decomposition | Identify 10 subsystems, boundaries, spec sources, dependency graph, phase sequencing |
| **M1.2** | Public-Facing Documentation | Tier 1 "How It Works" pages with SVG infographics for each subsystem |
| **M1.3** | Cross-Referencing Infrastructure | 3 new DB tables (`spec_sections`, `cross_references`, `test_specifications`), CLI commands, `init.sql` update, `db status` update |
| **M1.4** | Spec Rule Extraction | Per-subsystem spec analysis, populate `spec_sections` with verbatim + extracted rules (~500-2000 rules) |
| **M1.5** | Haskell Code & Discussion Mapping | Map spec rules -> Haskell modules -> GitHub issues and PRs, populate `cross_references`, produce gap analysis entries for divergences |
| **M1.6** | Library Audit | Evaluate Python libraries per subsystem at subsystem-level granularity, build/use/fork recommendations |
| **M1.7** | Data Architecture | Arrow/DuckDB/Feather evaluation against node data access patterns, benchmark results, decision doc |
| **M1.8** | Test Strategy & Specifications | Test strategy document, populate `test_specifications` for all identified spec rules |
| **M1.9** | Architecture Blueprint | Tier 2 technical docs per subsystem, synthesis, final phase sequencing, update `docs/development/milestones.md` with Phase 2-6 |

### Waves (Parallel Groupings)

| Wave | Modules | Rationale |
|------|---------|-----------|
| **Wave 1** | M1.1 | Everything depends on subsystem decomposition |
| **Wave 2** | M1.2, M1.3 | Both depend only on M1.1, independent of each other |
| **Wave 3** | M1.4, M1.6, M1.7 | M1.4 needs M1.3 tables; M1.6/M1.7 evaluate at subsystem level from M1.1, benefit from M1.3 for recording findings |
| **Wave 4** | M1.5, M1.8 | Both need M1.4's extracted spec rules to cross-reference and write tests against |
| **Wave 5** | M1.9 | Synthesis of everything into the final architecture blueprint |

### Dependencies

```
M1.1 -> M1.2 (subsystem list needed for infographics)
M1.1 -> M1.3 (subsystem list informs schema design)
M1.3 -> M1.4 (tables needed to store extracted rules)
M1.1 -> M1.6 (subsystem-level requirements for library evaluation)
M1.1 -> M1.7 (subsystem-level requirements for data architecture evaluation)
M1.3 -> M1.6 (tables available for recording findings)
M1.3 -> M1.7 (tables available for recording findings)
M1.4 -> M1.5 (spec rules needed for cross-referencing)
M1.4 -> M1.8 (spec rules needed for test specifications)
M1.2, M1.4, M1.5, M1.6, M1.7, M1.8 -> M1.9 (synthesis)
```

### Exit Criteria

Phase 1 is complete when:

1. Every subsystem is decomposed to module level (e.g., Serialization -> CBOR codec, CDDL validation, era-specific encoders, block decoder)
2. Every identified spec rule has a `spec_sections` row with verbatim + extracted rule
3. All critical and high priority spec rules have at least one planned test in `test_specifications` (lower priority rules may be deferred to implementation phases)
4. Library build/use/fork decisions are made for every subsystem
5. Data architecture is evaluated and decided with benchmark results
6. Implementation phases 2-6 are sequenced with module-level detail and reflected in `docs/development/milestones.md`
7. Both documentation tiers are published
8. `vibe-node db coverage` shows no critical/high priority spec rules without planned tests
9. Any spec-vs-Haskell divergences discovered are documented as gap analysis entries
