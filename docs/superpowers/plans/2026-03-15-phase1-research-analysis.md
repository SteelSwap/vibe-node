# Phase 1: Research & Analysis — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the Cardano node into subsystems, build cross-referencing infrastructure, extract spec rules, audit Python libraries, design tests, and produce two tiers of documentation — all before writing any node code.

**Architecture:** Interleaved approach — subsystem decomposition first, then DB infrastructure, then research populating everything together. Code-heavy work is in M1.3 (new tables + CLI). Research-heavy work (M1.4–M1.8) uses the infrastructure to store findings. Documentation is produced throughout.

**Tech Stack:** Python 3.14, Typer CLI, SQLModel + asyncpg, ParadeDB (pgvector + pg_search), Ollama embeddings, MkDocs Material, SVG infographics

**Spec:** `docs/superpowers/specs/2026-03-15-phase1-research-analysis-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `infra/db/migrate_phase1.sql` | Phase 1 table additions (also added to init.sql) |
| `src/vibe_node/db/xref.py` | Cross-reference CRUD operations (add, query, coverage) |
| `src/vibe_node/db/spec_sections.py` | Spec section CRUD and extraction helpers |
| `src/vibe_node/db/test_specs.py` | Test specification CRUD and filtering |
| `src/vibe_node/cli_xref.py` | CLI commands for xref add/query, coverage, test-specs |
| `src/vibe_node/research/populate_xrefs.py` | Helper script for batch cross-reference population (M1.5) |
| `benchmarks/data_architecture/bench_storage.py` | Storage benchmark: DuckDB/Arrow vs LMDB vs SQLite |
| `tests/test_xref.py` | Tests for cross-referencing operations |
| `tests/test_spec_sections.py` | Tests for spec section operations |
| `tests/test_test_specs.py` | Tests for test specification operations |
| `docs/how-it-works/index.md` | Tier 1: "How a Cardano Node Works" landing page |
| `docs/how-it-works/networking.md` | Tier 1: Networking subsystem explainer |
| `docs/how-it-works/miniprotocols.md` | Tier 1: Miniprotocols explainer |
| `docs/how-it-works/consensus.md` | Tier 1: Consensus explainer |
| `docs/how-it-works/ledger.md` | Tier 1: Ledger rules explainer |
| `docs/how-it-works/plutus.md` | Tier 1: Plutus/scripts explainer |
| `docs/how-it-works/serialization.md` | Tier 1: CBOR/serialization explainer |
| `docs/how-it-works/mempool.md` | Tier 1: Mempool explainer |
| `docs/how-it-works/storage.md` | Tier 1: Storage explainer |
| `docs/how-it-works/block-production.md` | Tier 1: Block production explainer |
| `docs/how-it-works/transaction-lifecycle.md` | Tier 1: "What happens when you submit a tx?" |
| `docs/assets/how-it-works/*.svg` | SVG infographics for each Tier 1 page |
| `docs/reference/subsystems/index.md` | Tier 2: Architecture blueprint landing page |
| `docs/reference/subsystems/networking.md` | Tier 2: Networking technical breakdown |
| `docs/reference/subsystems/miniprotocols-n2n.md` | Tier 2: N2N miniprotocols |
| `docs/reference/subsystems/miniprotocols-n2c.md` | Tier 2: N2C miniprotocols |
| `docs/reference/subsystems/consensus.md` | Tier 2: Consensus technical breakdown |
| `docs/reference/subsystems/ledger.md` | Tier 2: Ledger rules technical breakdown |
| `docs/reference/subsystems/plutus.md` | Tier 2: Plutus technical breakdown |
| `docs/reference/subsystems/serialization.md` | Tier 2: Serialization technical breakdown |
| `docs/reference/subsystems/mempool.md` | Tier 2: Mempool technical breakdown |
| `docs/reference/subsystems/storage.md` | Tier 2: Storage technical breakdown |
| `docs/reference/subsystems/block-production.md` | Tier 2: Block production technical breakdown |
| `docs/reference/data-architecture.md` | Data architecture evaluation (Arrow/DuckDB/Feather) |
| `docs/reference/library-audit.md` | Library audit summary with per-subsystem evaluations |
| `docs/reference/test-strategy.md` | Test strategy document |

### Modified Files

| File | Changes |
|------|---------|
| `infra/db/init.sql` | Add 3 new tables (spec_sections, cross_references, test_specifications) |
| `src/vibe_node/db/models.py` | Add SQLModel models for 3 new tables |
| `src/vibe_node/db/session.py` | Add `get_raw_connection()` context manager for raw asyncpg access |
| `src/vibe_node/cli.py` | Register xref/coverage/test-specs subcommands, update db status |
| `mkdocs.yml` | Add "How It Works" nav section, add subsystems under Reference |
| `docs/development/milestones.md` | Add Phase 1 modules and Phase 2-6 sequencing |
| `docs/specs/gap-analysis.md` | Add entries discovered during M1.5 research |

---

## Chunk 1: Wave 1 — Subsystem Decomposition (M1.1)

### Task 1: Research and document subsystem boundaries

This is primarily research work using the existing knowledge base. The output is documentation.

**Files:**
- Create: `docs/reference/subsystems/index.md`
- Modify: `docs/reference/architecture.md`
- Modify: `docs/development/milestones.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Query the knowledge base for node structure**

Use the Search MCP or CLI to understand how the Haskell node is organized:

```bash
uv run vibe-node db search "ouroboros multiplexer" --table specs
uv run vibe-node db search "chain-sync miniprotocol" --table specs
uv run vibe-node db search "ledger rules transition" --table specs
uv run vibe-node db search "block production forge" --table specs
uv run vibe-node db search "mempool transaction" --table specs
uv run vibe-node db search "immutable database storage" --table specs
```

Read the Haskell node's top-level module structure:

```bash
uv run vibe-node db search "module Ouroboros.Network" --table code --limit 20
uv run vibe-node db search "module Ouroboros.Consensus" --table code --limit 20
uv run vibe-node db search "module Cardano.Ledger" --table code --limit 20
```

- [ ] **Step 2: Create the subsystems index page**

Create `docs/reference/subsystems/index.md` with:
- The 10 subsystems table from the spec (subsystem name, description, primary specs)
- Inter-subsystem dependency diagram (Mermaid)
- Implementation phase sequencing table
- Brief description of what "module-level decomposition" means for each subsystem

```markdown
# Node Subsystems

This page maps the Cardano node into 10 major subsystems, each with clear boundaries,
governing specifications, and inter-subsystem dependencies. This decomposition drives
the implementation phase sequencing.

## Subsystem Map

| # | Subsystem | What It Does | Primary Specs |
|---|-----------|-------------|---------------|
| 1 | **Networking / Multiplexer** | TCP connections, Ouroboros multiplexer, bearer abstraction | ouroboros-network design docs, network spec |
| 2 | **Miniprotocols (Node-to-Node)** | Chain-sync, block-fetch, tx-submission, keep-alive | ouroboros-network miniprotocol specs |
| 3 | **Miniprotocols (Node-to-Client)** | Local chain-sync, local tx-submission, local state-query, local tx-monitor | ouroboros-network local protocol specs |
| 4 | **Consensus / Ouroboros Praos** | Leader election, VRF/KES, tip selection, chain growth | Ouroboros papers, ouroboros-consensus docs |
| 5 | **Ledger Rules** | UTxO transitions, delegation, governance, multi-era (Byron→Conway) | cardano-ledger formal specs, formal-ledger-specs (Agda) |
| 6 | **Plutus / Script Evaluation** | Plutus Core interpreter, cost models, script validation | plutus specs, cost model docs |
| 7 | **CBOR / Serialization** | Binary encoding/decoding for blocks, transactions, protocol messages | CDDL schemas per era |
| 8 | **Mempool** | Transaction staging, validation, capacity management | ouroboros-consensus mempool docs |
| 9 | **Storage** | Persistent chain state, immutable DB, volatile DB, ledger snapshots | ouroboros-consensus storage docs |
| 10 | **Block Production / Forge** | Block assembly, header creation, leader schedule | Consensus + ledger specs combined |

## Dependencies

​```mermaid
graph LR
    SER[7. Serialization] --> NET[1. Networking]
    SER --> N2N[2. N2N Miniprotocols]
    SER --> N2C[3. N2C Miniprotocols]
    SER --> LED[5. Ledger]
    SER --> CON[4. Consensus]
    SER --> STO[9. Storage]
    NET --> N2N
    NET --> N2C
    N2N --> CON
    N2N --> STO
    LED --> PLU[6. Plutus]
    CON --> MEM[8. Mempool]
    CON --> BLK[10. Block Production]
    STO --> LED
    STO --> CON
​```

## Implementation Phases

| Phase | Subsystems | Testable Capability |
|-------|-----------|-------------------|
| **Phase 2** | Serialization + Networking + Chain-Sync | Decode blocks, sync headers |
| **Phase 3** | Block Fetch + Storage + Ledger Rules (Byron–Mary) | Validate blocks (pre-Plutus) |
| **Phase 4** | Consensus + Mempool + Tx Submission | Tip selection agreement |
| **Phase 5** | Plutus + Block Production + N2C + Alonzo–Conway ledger | Produce valid blocks |
| **Phase 6** | Hardening | Power-loss recovery, memory optimization, 10-day soak |

## Module-Level Decomposition

Each subsystem page in this section breaks down into modules — the components
within that subsystem. For example:

- **Serialization** → CBOR codec, CDDL validation, era-specific encoders, block decoder
- **Networking** → TCP bearer, multiplexer, connection manager, peer discovery
- **Ledger** → UTxO rules, delegation, protocol parameters, governance, rewards

Module-level detail is populated during Phase 1 research and refined during
function-level research at the start of each implementation phase.
```

- [ ] **Step 3: Create skeleton pages for each subsystem**

Create 10 skeleton pages under `docs/reference/subsystems/` (one per subsystem). Each follows this template:

```markdown
# [Subsystem Name]

!!! note "Research In Progress"
    This page is populated during Phase 1 research. Module-level detail is added
    as spec rules are extracted and cross-referenced.

## Overview

[Brief description from subsystem table]

## Governing Specs

| Spec Source | Format | Key Sections |
|-------------|--------|-------------|
| [To be populated during M1.4] | | |

## Module Decomposition

[To be populated — list of components within this subsystem]

## Haskell Structure

[To be populated during M1.5 — how the reference implementation organizes this]

## Library Recommendations

[To be populated during M1.6]

## Test Strategy

[To be populated during M1.8]

## Phase Assignment

**Implementation Phase:** [N]
```

- [ ] **Step 4: Update mkdocs.yml nav**

Add the new sections to `mkdocs.yml`:

```yaml
nav:
  - Home: index.md
  - About:
    - Overview: about/index.md
    - The Challenge: about/challenge.md
    - How We Build: about/methodology.md
    - Toolchain: about/toolchain.md
    - Agent Architecture: about/agents.md
    - Coordination: about/coordination.md
  - How It Works:
    - Overview: how-it-works/index.md
    - Networking: how-it-works/networking.md
    - Miniprotocols: how-it-works/miniprotocols.md
    - Consensus: how-it-works/consensus.md
    - Ledger Rules: how-it-works/ledger.md
    - Script Evaluation: how-it-works/plutus.md
    - Serialization: how-it-works/serialization.md
    - Mempool: how-it-works/mempool.md
    - Storage: how-it-works/storage.md
    - Block Production: how-it-works/block-production.md
    - Transaction Lifecycle: how-it-works/transaction-lifecycle.md
  - Specifications:
    - Overview: specs/index.md
    - Gap Analysis: specs/gap-analysis.md
  - Development:
    - Overview: development/index.md
    - Milestones: development/milestones.md
    - Phase 0 Tasks: development/tasks.md
    - Development Log:
      - Journal: development/devlog/index.md
      - "Phase 0, Wave 1 — Foundation": development/devlog/phase0-wave1.md
      - "Phase 0, Wave 2 — Ingestion & CLI": development/devlog/phase0-wave2.md
  - Reference:
    - Overview: reference/index.md
    - CLI Reference: reference/cli-reference.md
    - Database Schema: reference/schema.md
    - Architecture: reference/architecture.md
    - Development Workflow: reference/workflow.md
    - Node Subsystems:
      - Overview: reference/subsystems/index.md
      - Networking: reference/subsystems/networking.md
      - "Miniprotocols (N2N)": reference/subsystems/miniprotocols-n2n.md
      - "Miniprotocols (N2C)": reference/subsystems/miniprotocols-n2c.md
      - Consensus: reference/subsystems/consensus.md
      - Ledger Rules: reference/subsystems/ledger.md
      - Plutus: reference/subsystems/plutus.md
      - Serialization: reference/subsystems/serialization.md
      - Mempool: reference/subsystems/mempool.md
      - Storage: reference/subsystems/storage.md
      - Block Production: reference/subsystems/block-production.md
    - Data Architecture: reference/data-architecture.md
    - Library Audit: reference/library-audit.md
    - Test Strategy: reference/test-strategy.md
    - Pipelines:
      - Spec Ingestion: reference/pipelines/spec-ingestion.md
      - Code Indexing: reference/pipelines/code-indexing.md
      - GitHub Ingestion: reference/pipelines/github-ingestion.md
```

- [ ] **Step 5: Update milestones page**

Update `docs/development/milestones.md` to include Phase 1 modules and Phase 2-6 overview:

```markdown
## Phase 1: Research & Analysis

| Module | Status | Description |
|--------|--------|-------------|
| M1.1 — Subsystem Decomposition | :material-check-circle: Complete | 10 subsystems, boundaries, specs, dependency graph |
| M1.2 — Public-Facing Documentation | :material-clock-outline: Planned | "How It Works" pages with SVG infographics |
| M1.3 — Cross-Referencing Infrastructure | :material-clock-outline: Planned | DB tables, CLI commands for spec traceability |
| M1.4 — Spec Rule Extraction | :material-clock-outline: Planned | Extract rules from specs into spec_sections table |
| M1.5 — Haskell Code & Discussion Mapping | :material-clock-outline: Planned | Cross-reference specs ↔ code ↔ issues |
| M1.6 — Library Audit | :material-clock-outline: Planned | Python library evaluation per subsystem |
| M1.7 — Data Architecture | :material-clock-outline: Planned | Arrow/DuckDB/Feather evaluation |
| M1.8 — Test Strategy & Specifications | :material-clock-outline: Planned | Test taxonomy, planned tests per spec rule |
| M1.9 — Architecture Blueprint | :material-clock-outline: Planned | Technical docs, synthesis, final phase sequencing |

## Phase 2–6: Implementation (Planned)

| Phase | Subsystems | Testable Capability |
|-------|-----------|-------------------|
| **Phase 2** | Serialization, Networking, Chain-Sync | Decode blocks, sync headers |
| **Phase 3** | Block Fetch, Storage, Ledger Rules (Byron–Mary) | Validate blocks (pre-Plutus) |
| **Phase 4** | Consensus, Mempool, Tx Submission | Tip selection agreement |
| **Phase 5** | Plutus, Block Production, N2C, Alonzo–Conway ledger | Produce valid blocks |
| **Phase 6** | Hardening | Power-loss recovery, memory optimization, 10-day soak |
```

- [ ] **Step 6: Verify documentation builds**

```bash
uv run mkdocs serve
```

Open http://localhost:8000 and verify:
- "How It Works" tab appears in nav
- All 10 subsystem pages under Reference → Node Subsystems load without errors
- Mermaid dependency diagram renders on the subsystems index page
- Milestones page shows Phase 1 and Phase 2-6

- [ ] **Step 7: Commit**

```bash
git add docs/reference/subsystems/ docs/development/milestones.md mkdocs.yml
git commit -m "feat(m1.1): subsystem decomposition — 10 subsystems, dependency graph, phase sequencing

Prompt: Decompose the Cardano node into major subsystems with boundaries,
governing specs, and inter-subsystem dependencies. Sequence into testable
implementation phases.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Chunk 2: Wave 2 — Public-Facing Docs + Cross-Referencing Infrastructure (M1.2, M1.3)

### Task 2: Create Tier 1 "How It Works" documentation (M1.2)

**Files:**
- Create: `docs/how-it-works/index.md`
- Create: `docs/how-it-works/networking.md`
- Create: `docs/how-it-works/miniprotocols.md`
- Create: `docs/how-it-works/consensus.md`
- Create: `docs/how-it-works/ledger.md`
- Create: `docs/how-it-works/plutus.md`
- Create: `docs/how-it-works/serialization.md`
- Create: `docs/how-it-works/mempool.md`
- Create: `docs/how-it-works/storage.md`
- Create: `docs/how-it-works/block-production.md`
- Create: `docs/how-it-works/transaction-lifecycle.md`
- Create: `docs/assets/how-it-works/*.svg` (one per page)

- [ ] **Step 1: Create the landing page**

Create `docs/how-it-works/index.md`:

```markdown
# How a Cardano Node Works

This section explains the major components of a Cardano node in plain language.
No code, no spec references — just how the pieces fit together and why they matter.

If you use Cardano — stake, vote, send transactions — this is what's running
behind the scenes on every node in the network.

## The Big Picture

A Cardano node does four things:

1. **Talks to other nodes** to stay in sync with the network
2. **Validates everything** — blocks, transactions, scripts — against the protocol rules
3. **Remembers the chain** — stores block history and current state
4. **Produces blocks** (if you're a stake pool operator)

Each of these is handled by a different subsystem, and they all work together.

[SVG: high-level node overview infographic — 4 quadrants showing the above]

## Subsystems

- **[Networking](networking.md)** — How your node finds and talks to other nodes
- **[Miniprotocols](miniprotocols.md)** — The conversations nodes have with each other
- **[Consensus](consensus.md)** — How the network agrees on what's true
- **[Ledger Rules](ledger.md)** — The rulebook for valid transactions
- **[Script Evaluation](plutus.md)** — Smart contracts and how they run
- **[Serialization](serialization.md)** — The binary language nodes speak
- **[Mempool](mempool.md)** — The waiting room for transactions
- **[Storage](storage.md)** — How the chain is remembered
- **[Block Production](block-production.md)** — How new blocks are made

## Follow a Transaction

Want to see all these pieces in action? Follow a transaction from your wallet
to the blockchain: **[Transaction Lifecycle](transaction-lifecycle.md)**
```

- [ ] **Step 2: Create each subsystem explainer page**

Each page follows this pattern:

1. Opening sentence connecting to something the reader knows
2. SVG infographic as the primary visual
3. 2-3 paragraphs explaining what the subsystem does and why
4. "How it connects" section linking to other subsystems
5. No code, no spec references

Example for `docs/how-it-works/networking.md`:

```markdown
# Networking

Every time you check your wallet balance or submit a transaction, your request
travels through a network of thousands of nodes. Networking is how your node
finds those other nodes and exchanges information with them.

![Networking overview](../assets/how-it-works/networking.svg)

## What It Does

Your node maintains connections to a set of peers — other Cardano nodes around
the world. When it starts up, it discovers peers through a combination of known
relay addresses and peer-to-peer discovery. Each connection is multiplexed,
meaning multiple conversations can happen over a single TCP connection
simultaneously.

Think of it like a phone line that can carry multiple calls at once. Your node
might be syncing block headers on one channel, fetching full blocks on another,
and receiving new transactions on a third — all over the same connection.

## How It Connects

Networking provides the transport layer that everything else builds on:

- **[Miniprotocols](miniprotocols.md)** ride on top of network connections
- **[Consensus](consensus.md)** uses networking to learn about new blocks
- **[Mempool](mempool.md)** receives transactions via the network
```

Create similar pages for all 10 subsystems plus the transaction lifecycle page. Each SVG infographic should follow the SteelSwap brand palette (`#ED458E` pink → `#F48020` orange gradient at 110deg, backgrounds `#1a1b1e`/`#25262b`).

- [ ] **Step 3: Create SVG infographics**

For each page, create an SVG in `docs/assets/how-it-works/` that visually explains the subsystem. SVGs should be:
- Clean, self-contained, readable at documentation width (~800px)
- SteelSwap brand palette
- No text smaller than 12px
- Focus on data flow and relationships, not implementation details

Required SVGs:
- `node-overview.svg` — The 4-quadrant high-level view
- `networking.svg` — Peer connections, multiplexer, TCP
- `miniprotocols.svg` — State machine conversations between nodes
- `consensus.svg` — Leader election, chain selection
- `ledger.svg` — Transaction validation pipeline
- `plutus.svg` — Script evaluation flow
- `serialization.svg` — CBOR encoding/decoding
- `mempool.svg` — Transaction staging
- `storage.svg` — Immutable DB + volatile DB
- `block-production.svg` — Block forging pipeline
- `transaction-lifecycle.svg` — End-to-end tx flow

- [ ] **Step 4: Verify all pages render**

```bash
uv run mkdocs serve
```

Check each page loads, SVGs display, nav is correct.

- [ ] **Step 5: Commit**

```bash
git add docs/how-it-works/ docs/assets/how-it-works/
git commit -m "feat(m1.2): tier 1 'How It Works' documentation with SVG infographics

Prompt: Create public-facing documentation explaining how a Cardano node works
for non-technical Cardano users. SVG infographics as primary visual content,
plain language, no code or spec references.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 3: Add database tables for cross-referencing (M1.3)

**Files:**
- Modify: `infra/db/init.sql`
- Create: `infra/db/migrate_phase1.sql`
- Modify: `src/vibe_node/db/models.py`

- [ ] **Step 1: Write the failing test for spec_sections model**

Create `tests/test_spec_sections.py`:

```python
"""Tests for spec_sections database operations."""
import pytest
from vibe_node.db.models import SpecSection


def test_spec_section_model_exists():
    """SpecSection SQLModel should be importable and have required fields."""
    fields = SpecSection.model_fields
    assert "spec_chunk_id" in fields
    assert "section_id" in fields
    assert "title" in fields
    assert "section_type" in fields
    assert "era" in fields
    assert "subsystem" in fields
    assert "verbatim" in fields
    assert "extracted_rule" in fields


def test_spec_section_valid_types():
    """section_type should accept valid values."""
    section = SpecSection(
        section_id="shelley-ledger:rule-7.3",
        title="UTxO Transition Rule",
        section_type="rule",
        era="shelley",
        subsystem="ledger",
        verbatim="The UTxO transition...",
        extracted_rule="The UTxO transition rule requires...",
    )
    assert section.section_type == "rule"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_spec_sections.py -v
```

Expected: FAIL with `ImportError: cannot import name 'SpecSection'`

- [ ] **Step 3: Write the failing test for cross_references model**

Create `tests/test_xref.py`:

```python
"""Tests for cross_references database operations."""
import pytest
from vibe_node.db.models import CrossReference


def test_cross_reference_model_exists():
    """CrossReference SQLModel should be importable and have required fields."""
    fields = CrossReference.model_fields
    assert "source_type" in fields
    assert "source_id" in fields
    assert "target_type" in fields
    assert "target_id" in fields
    assert "relationship" in fields
    assert "confidence" in fields
    assert "created_by" in fields


def test_cross_reference_defaults():
    """confidence should default to 1.0 and created_by to 'manual'."""
    import uuid
    xref = CrossReference(
        source_type="spec_section",
        source_id=uuid.uuid4(),
        target_type="code_chunk",
        target_id=uuid.uuid4(),
        relationship="implements",
    )
    assert xref.confidence == 1.0
    assert xref.created_by == "manual"
```

- [ ] **Step 4: Write the failing test for test_specifications model**

Create `tests/test_test_specs.py`:

```python
"""Tests for test_specifications database operations."""
import pytest
from vibe_node.db.models import TestSpecification


def test_test_specification_model_exists():
    """TestSpecification SQLModel should be importable and have required fields."""
    fields = TestSpecification.model_fields
    assert "spec_section_id" in fields
    assert "subsystem" in fields
    assert "test_type" in fields
    assert "test_name" in fields
    assert "description" in fields
    assert "priority" in fields
    assert "phase" in fields
    assert "status" in fields


def test_test_specification_defaults():
    """status should default to 'planned'."""
    spec = TestSpecification(
        subsystem="ledger",
        test_type="property",
        test_name="test_utxo_conservation",
        description="Total ADA is conserved across valid transactions",
        priority="critical",
        phase="phase-3",
    )
    assert spec.status == "planned"
```

- [ ] **Step 5: Run all tests to verify they fail**

```bash
uv run pytest tests/test_spec_sections.py tests/test_xref.py tests/test_test_specs.py -v
```

Expected: 6 FAIL (all ImportError)

- [ ] **Step 6: Add SQLModel models**

Add to `src/vibe_node/db/models.py`:

```python
class SpecSection(SQLModel, table=True):
    """Atomic unit of spec traceability — one rule, definition, or equation."""
    __tablename__ = "spec_sections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    spec_chunk_id: uuid.UUID | None = Field(default=None, foreign_key="spec_documents.id")
    section_id: str = Field(description="Stable ID like 'shelley-ledger:rule-7.3'")
    title: str
    section_type: str = Field(description="rule, definition, equation, type, figure, algorithm")
    era: str
    subsystem: str
    verbatim: str = Field(description="Exact spec text")
    extracted_rule: str = Field(description="Context-enriched semantic extraction")
    embedding: list[float] | None = Field(default=None, sa_column=Column(Vector(1536)))
    metadata: dict | None = Field(default=None, sa_column=Column(JSON))


class CrossReference(SQLModel, table=True):
    """Links any two entities in the knowledge base."""
    __tablename__ = "cross_references"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_type: str = Field(description="spec_section, code_chunk, github_issue, github_pr, test_specification")
    source_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    relationship: str = Field(description="implements, tests, discusses, references, contradicts, extends")
    confidence: float = Field(default=1.0)
    notes: str | None = None
    created_by: str = Field(default="manual", description="manual, agent, heuristic")


class TestSpecification(SQLModel, table=True):
    """Planned test — populated during research, executed during implementation."""
    __tablename__ = "test_specifications"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    spec_section_id: uuid.UUID | None = Field(default=None, foreign_key="spec_sections.id")
    subsystem: str
    test_type: str = Field(description="unit, property, replay, conformance, integration")
    test_name: str
    description: str
    hypothesis_strategy: str | None = None
    haskell_test_ref: str | None = None
    priority: str = Field(description="critical, high, medium, low")
    phase: str
    status: str = Field(default="planned", description="planned, implemented, passing, failing, skipped")
    metadata: dict | None = Field(default=None, sa_column=Column(JSON))
```

- [ ] **Step 7: Run tests to verify models pass**

```bash
uv run pytest tests/test_spec_sections.py tests/test_xref.py tests/test_test_specs.py -v
```

Expected: 6 PASS

- [ ] **Step 8: Add tables to init.sql**

Add to `infra/db/init.sql` (after existing table definitions):

```sql
-- Phase 1: Cross-referencing infrastructure
CREATE TABLE IF NOT EXISTS spec_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_chunk_id UUID REFERENCES spec_documents(id) ON DELETE SET NULL,
    section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    section_type TEXT NOT NULL,
    era TEXT NOT NULL,
    subsystem TEXT NOT NULL,
    verbatim TEXT NOT NULL,
    extracted_rule TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB,
    UNIQUE (section_id)
);

CREATE INDEX IF NOT EXISTS idx_spec_sections_era ON spec_sections(era);
CREATE INDEX IF NOT EXISTS idx_spec_sections_subsystem ON spec_sections(subsystem);
CREATE INDEX IF NOT EXISTS idx_spec_sections_type ON spec_sections(section_type);

CREATE TABLE IF NOT EXISTS cross_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type TEXT NOT NULL,
    source_id UUID NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    relationship TEXT NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    notes TEXT,
    created_by TEXT DEFAULT 'manual',
    UNIQUE (source_type, source_id, target_type, target_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_xref_source ON cross_references(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_xref_target ON cross_references(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_xref_relationship ON cross_references(relationship);

CREATE TABLE IF NOT EXISTS test_specifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_section_id UUID REFERENCES spec_sections(id) ON DELETE SET NULL,
    subsystem TEXT NOT NULL,
    test_type TEXT NOT NULL,
    test_name TEXT NOT NULL,
    description TEXT NOT NULL,
    hypothesis_strategy TEXT,
    haskell_test_ref TEXT,
    priority TEXT NOT NULL,
    phase TEXT NOT NULL,
    status TEXT DEFAULT 'planned',
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_test_specs_subsystem ON test_specifications(subsystem);
CREATE INDEX IF NOT EXISTS idx_test_specs_phase ON test_specifications(phase);
CREATE INDEX IF NOT EXISTS idx_test_specs_status ON test_specifications(status);
CREATE INDEX IF NOT EXISTS idx_test_specs_priority ON test_specifications(priority);
```

Also create `infra/db/migrate_phase1.sql` with the same SQL for applying to existing databases:

```sql
-- Phase 1 migration: Cross-referencing infrastructure
-- Safe to run on existing databases (IF NOT EXISTS)
-- Run with: docker compose exec paradedb psql -U vibenode -d vibenode -f /tmp/migrate_phase1.sql

[same SQL as above]
```

- [ ] **Step 9: Apply migration to running database**

```bash
docker compose cp infra/db/migrate_phase1.sql paradedb:/tmp/migrate_phase1.sql
docker compose exec paradedb psql -U vibenode -d vibenode -f /tmp/migrate_phase1.sql
```

- [ ] **Step 10: Commit**

```bash
git add infra/db/init.sql infra/db/migrate_phase1.sql src/vibe_node/db/models.py tests/test_spec_sections.py tests/test_xref.py tests/test_test_specs.py
git commit -m "feat(m1.3): add spec_sections, cross_references, test_specifications tables

Prompt: Add three new database tables for Phase 1 cross-referencing
infrastructure. spec_sections stores extracted spec rules, cross_references
links any two entities, test_specifications tracks planned tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 4: Implement cross-referencing CLI commands (M1.3)

**Files:**
- Create: `src/vibe_node/db/xref.py`
- Create: `src/vibe_node/db/spec_sections.py`
- Create: `src/vibe_node/db/test_specs.py`
- Create: `src/vibe_node/cli_xref.py`
- Modify: `src/vibe_node/cli.py`

- [ ] **Step 1: Implement spec_sections CRUD**

Create `src/vibe_node/db/spec_sections.py`:

```python
"""CRUD operations for spec_sections table."""
import uuid
from typing import Optional


async def add_spec_section(
    conn,
    section_id: str,
    title: str,
    section_type: str,
    era: str,
    subsystem: str,
    verbatim: str,
    extracted_rule: str,
    spec_chunk_id: Optional[uuid.UUID] = None,
    embedding: Optional[list[float]] = None,
    metadata: Optional[dict] = None,
) -> uuid.UUID:
    """Insert a spec section and return its ID."""
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO spec_sections (id, spec_chunk_id, section_id, title, section_type,
            era, subsystem, verbatim, extracted_rule, embedding, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (section_id) DO UPDATE SET
            title = EXCLUDED.title,
            extracted_rule = EXCLUDED.extracted_rule,
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata
        """,
        row_id, spec_chunk_id, section_id, title, section_type,
        era, subsystem, verbatim, extracted_rule, embedding,
        metadata,
    )
    return row_id


async def list_spec_sections(
    conn,
    subsystem: Optional[str] = None,
    era: Optional[str] = None,
    section_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List spec sections with optional filters."""
    conditions = []
    params = []
    idx = 1
    if subsystem:
        conditions.append(f"subsystem = ${idx}")
        params.append(subsystem)
        idx += 1
    if era:
        conditions.append(f"era = ${idx}")
        params.append(era)
        idx += 1
    if section_type:
        conditions.append(f"section_type = ${idx}")
        params.append(section_type)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await conn.fetch(
        f"SELECT id, section_id, title, section_type, era, subsystem FROM spec_sections {where} ORDER BY section_id LIMIT ${idx}",
        *params,
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Implement cross_references CRUD**

Create `src/vibe_node/db/xref.py`:

```python
"""CRUD operations for cross_references table."""
import uuid
from typing import Optional

# Maps source_type values to table names for display
TYPE_TABLE_MAP = {
    "spec_section": "spec_sections",
    "code_chunk": "code_chunks",
    "github_issue": "github_issues",
    "github_pr": "github_pull_requests",
    "test_specification": "test_specifications",
}


async def add_xref(
    conn,
    source_type: str,
    source_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    relationship: str,
    confidence: float = 1.0,
    notes: Optional[str] = None,
    created_by: str = "manual",
) -> uuid.UUID:
    """Insert a cross-reference and return its ID."""
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO cross_references (id, source_type, source_id, target_type, target_id,
            relationship, confidence, notes, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (source_type, source_id, target_type, target_id, relationship)
        DO UPDATE SET confidence = EXCLUDED.confidence, notes = EXCLUDED.notes
        """,
        row_id, source_type, source_id, target_type, target_id,
        relationship, confidence, notes, created_by,
    )
    return row_id


async def query_xrefs(
    conn,
    entity_type: str,
    entity_id: uuid.UUID,
    relationship: Optional[str] = None,
) -> list[dict]:
    """Find all cross-references involving an entity (as source or target)."""
    conditions = "(source_type = $1 AND source_id = $2) OR (target_type = $1 AND target_id = $2)"
    params = [entity_type, entity_id]
    if relationship:
        conditions = f"({conditions}) AND relationship = $3"
        params.append(relationship)

    rows = await conn.fetch(
        f"SELECT * FROM cross_references WHERE {conditions} ORDER BY relationship",
        *params,
    )
    return [dict(r) for r in rows]


async def coverage_report(conn) -> dict:
    """Generate spec coverage report.

    Returns counts of:
    - Total spec sections
    - Spec sections with at least one 'implements' cross-reference
    - Spec sections with at least one 'tests' cross-reference (via test_specifications)
    - Spec sections with neither
    """
    result = await conn.fetchrow("""
        WITH section_coverage AS (
            SELECT
                ss.id,
                ss.section_id,
                ss.subsystem,
                ss.era,
                EXISTS (
                    SELECT 1 FROM cross_references cr
                    WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id
                    AND cr.relationship = 'implements'
                ) AS has_implementation,
                EXISTS (
                    SELECT 1 FROM test_specifications ts
                    WHERE ts.spec_section_id = ss.id
                ) AS has_test
            FROM spec_sections ss
        )
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE has_implementation) AS with_implementation,
            COUNT(*) FILTER (WHERE has_test) AS with_tests,
            COUNT(*) FILTER (WHERE NOT has_implementation AND NOT has_test) AS uncovered
        FROM section_coverage
    """)
    return dict(result)


async def uncovered_sections(
    conn,
    subsystem: Optional[str] = None,
    no_tests: bool = False,
    no_implementation: bool = False,
) -> list[dict]:
    """List spec sections missing tests, implementations, or both."""
    conditions = []
    params = []
    idx = 1

    if subsystem:
        conditions.append(f"ss.subsystem = ${idx}")
        params.append(subsystem)
        idx += 1

    if no_tests:
        conditions.append("NOT EXISTS (SELECT 1 FROM test_specifications ts WHERE ts.spec_section_id = ss.id)")

    if no_implementation:
        conditions.append("""NOT EXISTS (
            SELECT 1 FROM cross_references cr
            WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id
            AND cr.relationship = 'implements'
        )""")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = await conn.fetch(
        f"""SELECT ss.section_id, ss.title, ss.subsystem, ss.era, ss.section_type
        FROM spec_sections ss {where} ORDER BY ss.subsystem, ss.section_id""",
        *params,
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 3: Implement test_specifications CRUD**

Create `src/vibe_node/db/test_specs.py`:

```python
"""CRUD operations for test_specifications table."""
import uuid
from typing import Optional


async def add_test_spec(
    conn,
    subsystem: str,
    test_type: str,
    test_name: str,
    description: str,
    priority: str,
    phase: str,
    spec_section_id: Optional[uuid.UUID] = None,
    hypothesis_strategy: Optional[str] = None,
    haskell_test_ref: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> uuid.UUID:
    """Insert a test specification and return its ID."""
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO test_specifications (id, spec_section_id, subsystem, test_type,
            test_name, description, hypothesis_strategy, haskell_test_ref,
            priority, phase, status, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'planned', $11)
        """,
        row_id, spec_section_id, subsystem, test_type,
        test_name, description, hypothesis_strategy, haskell_test_ref,
        priority, phase, metadata,
    )
    return row_id


async def list_test_specs(
    conn,
    subsystem: Optional[str] = None,
    phase: Optional[str] = None,
    test_type: Optional[str] = None,
    priority: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List test specifications with optional filters."""
    conditions = []
    params = []
    idx = 1

    for col, val in [
        ("subsystem", subsystem), ("phase", phase),
        ("test_type", test_type), ("priority", priority), ("status", status),
    ]:
        if val:
            conditions.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await conn.fetch(
        f"""SELECT id, test_name, subsystem, test_type, priority, phase, status
        FROM test_specifications {where}
        ORDER BY
            CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                          WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
            subsystem, test_name
        LIMIT ${idx}""",
        *params,
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Implement CLI commands**

Create `src/vibe_node/cli_xref.py`:

```python
"""CLI commands for cross-referencing, coverage, and test specifications."""
import asyncio
import uuid

import typer
from rich.console import Console
from rich.table import Table

from vibe_node.db.session import get_raw_connection

console = Console()

xref_app = typer.Typer(help="Cross-reference management")
test_spec_app = typer.Typer(help="Test specification management")


@xref_app.command("add")
def xref_add(
    source_type: str = typer.Argument(help="Source entity type"),
    source_id: str = typer.Argument(help="Source entity UUID"),
    target_type: str = typer.Argument(help="Target entity type"),
    target_id: str = typer.Argument(help="Target entity UUID"),
    relationship: str = typer.Argument(help="Relationship: implements, tests, discusses, references, contradicts, extends"),
    confidence: float = typer.Option(1.0, "--confidence", "-c"),
    notes: str | None = typer.Option(None, "--notes"),
    created_by: str = typer.Option("manual", "--by"),
):
    """Add a cross-reference between two entities."""
    asyncio.run(_xref_add(source_type, uuid.UUID(source_id), target_type, uuid.UUID(target_id),
                          relationship, confidence, notes, created_by))


async def _xref_add(source_type, source_id, target_type, target_id, relationship, confidence, notes, created_by):
    async with get_raw_connection() as conn:
        from vibe_node.db.xref import add_xref
        row_id = await add_xref(conn, source_type, source_id, target_type, target_id,
                                relationship, confidence, notes, created_by)
    console.print(f"[green]Cross-reference added:[/green] {row_id}")


@xref_app.command("query")
def xref_query(
    entity_type: str = typer.Argument(help="Entity type: spec_section, code_chunk, github_issue, github_pr, test_specification"),
    entity_id: str = typer.Argument(help="Entity UUID"),
    relationship: str | None = typer.Option(None, "--rel", "-r", help="Filter by relationship type"),
):
    """Query cross-references for an entity."""
    from vibe_node.db.xref import query_xrefs
    asyncio.run(_xref_query(entity_type, uuid.UUID(entity_id), relationship))


async def _xref_query(entity_type, entity_id, relationship):
    async with get_raw_connection() as conn:
        from vibe_node.db.xref import query_xrefs
        rows = await query_xrefs(conn, entity_type, entity_id, relationship)

    table = Table(title="Cross References")
    table.add_column("Source Type")
    table.add_column("Relationship")
    table.add_column("Target Type")
    table.add_column("Confidence")
    table.add_column("Created By")
    for r in rows:
        table.add_row(r["source_type"], r["relationship"], r["target_type"],
                      f"{r['confidence']:.1f}", r["created_by"])
    console.print(table)


@xref_app.command("coverage")
def coverage():
    """Show spec coverage report — which rules have tests and implementations."""
    asyncio.run(_coverage())


async def _coverage():
    async with get_raw_connection() as conn:
        from vibe_node.db.xref import coverage_report, uncovered_sections
        report = await coverage_report(conn)
        uncovered = await uncovered_sections(conn, no_tests=True, no_implementation=True)

    console.print(f"\n[bold]Spec Coverage Report[/bold]\n")
    console.print(f"  Total spec sections:    {report['total']}")
    console.print(f"  With implementation:    {report['with_implementation']}")
    console.print(f"  With planned tests:     {report['with_tests']}")
    console.print(f"  [red]Uncovered (neither):[/red]  {report['uncovered']}")

    if uncovered:
        console.print(f"\n[bold]Uncovered Sections[/bold] (no tests, no implementation):\n")
        table = Table()
        table.add_column("Section ID")
        table.add_column("Title")
        table.add_column("Subsystem")
        table.add_column("Era")
        for s in uncovered[:20]:
            table.add_row(s["section_id"], s["title"], s["subsystem"], s["era"])
        if len(uncovered) > 20:
            console.print(f"  ... and {len(uncovered) - 20} more")
        console.print(table)


@test_spec_app.command("list")
def test_specs_list(
    subsystem: str | None = typer.Option(None, "--subsystem", "-s"),
    phase: str | None = typer.Option(None, "--phase", "-p"),
    test_type: str | None = typer.Option(None, "--type", "-t"),
    priority: str | None = typer.Option(None, "--priority"),
    status: str | None = typer.Option(None, "--status"),
    limit: int = typer.Option(50, "--limit", "-n"),
):
    """List planned test specifications."""
    asyncio.run(_test_specs_list(subsystem, phase, test_type, priority, status, limit))


async def _test_specs_list(subsystem, phase, test_type, priority, status, limit):
    async with get_raw_connection() as conn:
        from vibe_node.db.test_specs import list_test_specs
        rows = await list_test_specs(conn, subsystem, phase, test_type, priority, status, limit)

    table = Table(title="Test Specifications")
    table.add_column("Name")
    table.add_column("Subsystem")
    table.add_column("Type")
    table.add_column("Priority")
    table.add_column("Phase")
    table.add_column("Status")
    for r in rows:
        table.add_row(r["test_name"], r["subsystem"], r["test_type"],
                      r["priority"], r["phase"], r["status"])
    console.print(table)
```

- [ ] **Step 5: Register CLI commands and update db status**

Modify `src/vibe_node/cli.py` to register the new subcommands:

```python
# Add imports at top
from vibe_node.cli_xref import xref_app, test_spec_app

# Register under db subcommand group
db_app.add_typer(xref_app, name="xref")
db_app.add_typer(test_spec_app, name="test-specs")
```

Update the `db_status` command in `cli.py` to include the 3 new tables. Find the `tables` list in the `status` function and add the new table names:

```python
# In the db_status function, update the tables list:
tables = [
    "spec_documents", "code_chunks", "code_tag_manifest",
    "github_issues", "github_issue_comments",
    "github_pull_requests", "github_pr_comments",
    "spec_sections", "cross_references", "test_specifications",  # Phase 1
]
```

- [ ] **Step 6: Test CLI commands against running database**

```bash
# Verify tables exist
uv run vibe-node db status

# Verify coverage command works (should show 0 for everything)
uv run vibe-node db xref coverage

# Verify test-specs list works (should show empty table)
uv run vibe-node db test-specs list

# Verify help text
uv run vibe-node db xref --help
uv run vibe-node db test-specs --help
```

- [ ] **Step 7: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/vibe_node/db/xref.py src/vibe_node/db/spec_sections.py src/vibe_node/db/test_specs.py src/vibe_node/cli_xref.py src/vibe_node/cli.py
git commit -m "feat(m1.3): cross-referencing CLI — xref query, coverage report, test-specs list

Prompt: Implement CLI commands for cross-reference management, spec coverage
reporting, and test specification listing. Adds xref CRUD, coverage analysis
(which spec rules lack tests/implementations), and test spec filtering.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Chunk 3: Wave 3 — Spec Rule Extraction, Library Audit, Data Architecture (M1.4, M1.6, M1.7)

### Task 5: Spec rule extraction pipeline (M1.4)

This is the most research-intensive task. Agent Millenial reads spec documents from the knowledge base, identifies individual rules/definitions/equations, and produces structured extractions stored in `spec_sections`.

**Files:**
- Create: `src/vibe_node/research/extract_rules.py`
- Modify: `docs/reference/subsystems/*.md` (populated with extracted rules)

- [ ] **Step 1: Create the extraction helper script**

Create `src/vibe_node/research/extract_rules.py` — a CLI helper that queries spec chunks for a subsystem and provides a structured workflow for extraction:

```python
"""Semi-automated spec rule extraction helper.

Usage:
    uv run python -m vibe_node.research.extract_rules --subsystem ledger --era shelley
    uv run python -m vibe_node.research.extract_rules --subsystem serialization

Queries spec_documents for the given subsystem/era, displays chunks, and provides
a structured interface for extracting rules into spec_sections.
"""
import asyncio
import json
import uuid
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from vibe_node.db.session import get_raw_connection
from vibe_node.db.spec_sections import add_spec_section
from vibe_node.embed.client import EmbeddingClient

console = Console()
app = typer.Typer()


async def get_spec_chunks(subsystem: str, era: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Fetch spec document chunks relevant to a subsystem."""
    # Map subsystem names to likely search terms in spec_documents
    subsystem_terms = {
        "networking": ["ouroboros-network", "network"],
        "miniprotocols-n2n": ["chain-sync", "block-fetch", "tx-submission", "keep-alive"],
        "miniprotocols-n2c": ["local-chain-sync", "local-tx", "state-query", "tx-monitor"],
        "consensus": ["ouroboros", "praos", "consensus"],
        "ledger": ["ledger", "utxo", "delegation"],
        "plutus": ["plutus", "script", "cost-model"],
        "serialization": ["cddl", "cbor"],
        "mempool": ["mempool"],
        "storage": ["immutable", "volatile", "storage"],
        "block-production": ["forge", "block production", "leader"],
    }

    terms = subsystem_terms.get(subsystem, [subsystem])
    async with get_raw_connection() as conn:
        chunks = []
        for term in terms:
            conditions = "content_markdown ILIKE $1"
            params = [f"%{term}%"]
            idx = 2
            if era:
                conditions += f" AND era = ${idx}"
                params.append(era)
                idx += 1
            params.append(limit)
            rows = await conn.fetch(
                f"""SELECT id, document_title, section_title, subsection_title,
                    era, source_repo, content_markdown
                FROM spec_documents WHERE {conditions}
                ORDER BY source_repo, document_title LIMIT ${idx}""",
                *params,
            )
            chunks.extend([dict(r) for r in rows])
    return chunks


async def store_extraction(
    section_id: str,
    title: str,
    section_type: str,
    era: str,
    subsystem: str,
    verbatim: str,
    extracted_rule: str,
    spec_chunk_id: Optional[uuid.UUID] = None,
    metadata: Optional[dict] = None,
):
    """Store an extracted spec section with embedding."""
    client = EmbeddingClient()
    embedding = await client.embed(extracted_rule)

    async with get_raw_connection() as conn:
        row_id = await add_spec_section(
            conn, section_id, title, section_type, era, subsystem,
            verbatim, extracted_rule, spec_chunk_id, embedding, metadata,
        )
    return row_id


@app.command()
def extract(
    subsystem: str = typer.Argument(help="Subsystem to extract rules for"),
    era: str | None = typer.Option(None, "--era", "-e"),
    limit: int = typer.Option(100, "--limit", "-n"),
):
    """Interactive spec rule extraction for a subsystem."""
    chunks = asyncio.run(get_spec_chunks(subsystem, era, limit))
    console.print(f"\nFound [bold]{len(chunks)}[/bold] spec chunks for subsystem={subsystem}" +
                  (f", era={era}" if era else ""))

    for i, chunk in enumerate(chunks):
        console.print(Panel(
            f"[bold]{chunk['document_title']}[/bold]\n"
            f"Section: {chunk['section_title'] or 'N/A'}\n"
            f"Subsection: {chunk['subsection_title'] or 'N/A'}\n"
            f"Era: {chunk['era']} | Repo: {chunk['source_repo']}\n\n"
            f"{chunk['content_markdown'][:2000]}{'...' if len(chunk['content_markdown'] or '') > 2000 else ''}",
            title=f"Chunk {i+1}/{len(chunks)}",
        ))
    console.print(f"\n[dim]Use this output to identify rules and produce extractions.[/dim]")
    console.print(f"[dim]Store extractions via store_extraction() in this module.[/dim]")


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Create `__init__.py` for research package**

```bash
touch src/vibe_node/research/__init__.py
```

- [ ] **Step 3: Run extraction for each subsystem**

Execute the extraction process subsystem by subsystem. For each subsystem:

1. Run the extraction helper to view relevant spec chunks
2. Identify individual rules, definitions, equations
3. For each, produce verbatim + extracted_rule
4. Store via `store_extraction()`

```bash
# Start with serialization (smallest, most concrete)
uv run python -m vibe_node.research.extract_rules serialization

# Then networking
uv run python -m vibe_node.research.extract_rules networking

# Continue through all subsystems...
uv run python -m vibe_node.research.extract_rules consensus
uv run python -m vibe_node.research.extract_rules ledger --era shelley
uv run python -m vibe_node.research.extract_rules ledger --era alonzo
uv run python -m vibe_node.research.extract_rules ledger --era conway
# ... etc for all subsystems and eras
```

This is interactive, research-intensive work. Expect 500-2000 `spec_sections` rows across all subsystems.

- [ ] **Step 4: Verify extraction coverage**

```bash
uv run vibe-node db status  # Check spec_sections row count
uv run vibe-node db xref coverage  # Check coverage (tests/implementations will be 0 at this point)
```

- [ ] **Step 5: Update subsystem pages with extracted rules**

For each `docs/reference/subsystems/*.md` page, populate the "Governing Specs" section with the extracted rules for that subsystem. Include the `section_id` for traceability.

- [ ] **Step 6: Commit**

```bash
git add src/vibe_node/research/ docs/reference/subsystems/
git commit -m "feat(m1.4): spec rule extraction — extracted rules for all subsystems

Prompt: Extract individual rules, definitions, and equations from spec
documents into spec_sections table. Semi-automated pipeline: query spec
chunks, identify rules, produce verbatim + context-enriched extractions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 6: Library audit (M1.6)

**Files:**
- Create: `docs/reference/library-audit.md`
- Modify: `docs/reference/subsystems/*.md` (add library recommendations)

- [ ] **Step 1: Research Python libraries per subsystem**

For each subsystem, research candidates using web search and PyPI. Evaluate against the 6 criteria from the spec (requirement coverage, maintenance health, license, quality, performance, gaps).

Key searches to perform:
```
# Serialization
pip index versions cbor2
pip index versions pycardano

# Crypto
pip index versions pynacl
pip index versions cryptography

# Plutus
pip index versions uplc
pip search "cardano plutus python"

# Networking
# asyncio is stdlib — evaluate trio as alternative

# Storage candidates covered by M1.7
```

- [ ] **Step 2: Write the library audit document**

Create `docs/reference/library-audit.md` with:

```markdown
# Library Audit

Evaluation of Python libraries for each node subsystem. Each candidate is assessed
against requirement coverage, maintenance health, license compatibility (AGPL-3.0),
quality, performance, and gaps.

## Decision Framework

| Decision | Criteria |
|----------|---------|
| **USE** | Well-maintained, covers majority of needs. Contribute upstream for gaps. |
| **FORK** | Good code but poorly maintained. Fork and maintain ourselves. |
| **REUSE** | Extract specific code with attribution, license permitting. |
| **BUILD** | Nothing suitable. Implement from spec. |

## Summary

| Subsystem | Recommendation | Library | Rationale |
|-----------|---------------|---------|-----------|
| Serialization | [USE/BUILD/...] | [library] | [brief] |
| Networking | [USE/BUILD/...] | [library] | [brief] |
| Crypto | [USE/BUILD/...] | [library] | [brief] |
| Ledger | [USE/BUILD/...] | [library] | [brief] |
| Plutus | [USE/BUILD/...] | [library] | [brief] |
| Mempool | BUILD | — | No existing libraries |
| Consensus | BUILD | — | Protocol-specific logic |
| Block Production | BUILD | — | Protocol-specific logic |

## Detailed Evaluations

### Serialization
[Full evaluation per criteria for cbor2, pycardano CBOR layer, etc.]

### Crypto
[Full evaluation for PyNaCl, cryptography, VRF options]

[... one section per subsystem ...]
```

- [ ] **Step 3: Update subsystem pages**

For each subsystem page in `docs/reference/subsystems/`, populate the "Library Recommendations" section with the audit findings.

- [ ] **Step 4: Commit**

```bash
git add docs/reference/library-audit.md docs/reference/subsystems/
git commit -m "feat(m1.6): library audit — Python library evaluation per subsystem

Prompt: Evaluate Python library candidates for each node subsystem against
requirement coverage, maintenance health, license, quality, performance, and
gaps. Build/use/fork recommendation for each.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 7: Data architecture evaluation (M1.7)

**Files:**
- Create: `docs/reference/data-architecture.md`
- Modify: `docs/reference/subsystems/storage.md`

- [ ] **Step 1: Research Arrow/DuckDB/Feather stack**

Evaluate against the 6 data access patterns from the spec:
1. UTxO lookups by address and transaction ID
2. Stake distribution snapshots at epoch boundaries
3. Block append (immutable DB)
4. Rollback (volatile DB — revert N blocks)
5. Ledger state snapshots for crash recovery
6. Memory footprint under steady-state sync

Also evaluate traditional alternatives: LMDB, RocksDB, SQLite.

- [ ] **Step 2: Write proof-of-concept benchmarks**

Create `benchmarks/data_architecture/bench_storage.py`:

```python
"""Storage benchmark: DuckDB/Arrow vs LMDB vs SQLite for Cardano node access patterns.

Usage:
    uv run python benchmarks/data_architecture/bench_storage.py

Outputs a comparison table with latency and memory measurements.
"""
import time
import os
import uuid
import tempfile
from dataclasses import dataclass

# Simulate UTxO-like records
@dataclass
class FakeUTxO:
    tx_id: str
    output_index: int
    address: str
    value: int


def generate_utxos(n: int) -> list[FakeUTxO]:
    """Generate N fake UTxO records."""
    return [
        FakeUTxO(
            tx_id=uuid.uuid4().hex,
            output_index=i % 4,
            address=f"addr_{i % 1000:04d}",
            value=1_000_000 + (i * 1000),
        )
        for i in range(n)
    ]


def bench_duckdb(utxos: list[FakeUTxO], tmpdir: str) -> dict:
    """Benchmark DuckDB + Arrow."""
    import duckdb
    import pyarrow as pa

    db = duckdb.connect(os.path.join(tmpdir, "bench.duckdb"))

    # Insert
    t0 = time.perf_counter()
    table = pa.table({
        "tx_id": [u.tx_id for u in utxos],
        "output_index": [u.output_index for u in utxos],
        "address": [u.address for u in utxos],
        "value": [u.value for u in utxos],
    })
    db.execute("CREATE TABLE utxos AS SELECT * FROM table")
    insert_ms = (time.perf_counter() - t0) * 1000

    # Point lookup
    target = utxos[len(utxos) // 2].tx_id
    t0 = time.perf_counter()
    for _ in range(1000):
        db.execute("SELECT * FROM utxos WHERE tx_id = ?", [target]).fetchall()
    lookup_us = (time.perf_counter() - t0) * 1000  # avg per lookup

    # Range scan
    t0 = time.perf_counter()
    db.execute("SELECT * FROM utxos WHERE address = 'addr_0042'").fetchall()
    scan_ms = (time.perf_counter() - t0) * 1000

    db.close()
    return {"engine": "DuckDB", "insert_ms": insert_ms, "lookup_us": lookup_us, "scan_ms": scan_ms}


def bench_sqlite(utxos: list[FakeUTxO], tmpdir: str) -> dict:
    """Benchmark SQLite."""
    import sqlite3

    db = sqlite3.connect(os.path.join(tmpdir, "bench.sqlite"))
    db.execute("CREATE TABLE utxos (tx_id TEXT, output_index INT, address TEXT, value INT)")
    db.execute("CREATE INDEX idx_tx ON utxos(tx_id)")
    db.execute("CREATE INDEX idx_addr ON utxos(address)")

    t0 = time.perf_counter()
    db.executemany("INSERT INTO utxos VALUES (?,?,?,?)",
                   [(u.tx_id, u.output_index, u.address, u.value) for u in utxos])
    db.commit()
    insert_ms = (time.perf_counter() - t0) * 1000

    target = utxos[len(utxos) // 2].tx_id
    t0 = time.perf_counter()
    for _ in range(1000):
        db.execute("SELECT * FROM utxos WHERE tx_id = ?", [target]).fetchall()
    lookup_us = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    db.execute("SELECT * FROM utxos WHERE address = 'addr_0042'").fetchall()
    scan_ms = (time.perf_counter() - t0) * 1000

    db.close()
    return {"engine": "SQLite", "insert_ms": insert_ms, "lookup_us": lookup_us, "scan_ms": scan_ms}


if __name__ == "__main__":
    N = 100_000
    print(f"Generating {N} fake UTxOs...")
    utxos = generate_utxos(N)

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        results.append(bench_duckdb(utxos, tmpdir))
        results.append(bench_sqlite(utxos, tmpdir))
        # Add bench_lmdb, bench_rocksdb as needed

    print(f"\n{'Engine':<12} {'Insert (ms)':<14} {'Lookup (us/1k)':<16} {'Scan (ms)':<12}")
    print("-" * 54)
    for r in results:
        print(f"{r['engine']:<12} {r['insert_ms']:<14.1f} {r['lookup_us']:<16.1f} {r['scan_ms']:<12.2f}")
```

Run with expected output:
```bash
uv run python benchmarks/data_architecture/bench_storage.py
```

Expected output format:
```
Engine       Insert (ms)    Lookup (us/1k)   Scan (ms)
------------------------------------------------------
DuckDB       XX.X           XX.X             X.XX
SQLite       XX.X           XX.X             X.XX
```

Focus on:
- Insert throughput (block append)
- Point lookup latency (UTxO by tx ID)
- Range scan (all UTxOs for an address)
- Memory footprint (measure via `tracemalloc` or `/proc/self/status`)

- [ ] **Step 3: Write the data architecture document**

Create `docs/reference/data-architecture.md`:

```markdown
# Data Architecture

The data architecture determines whether vibe-node can meet the memory
requirement — matching or beating the Haskell node's average memory usage
across 10 days. This is a pass/fail criterion, not an optimization target.

## Access Patterns

A Cardano node's data layer must support these patterns efficiently:

| Pattern | Frequency | Latency Target |
|---------|-----------|---------------|
| UTxO lookup by tx ID | Per-transaction | < 1ms |
| UTxO scan by address | Per-query | < 10ms |
| Block append | Per-block (~20s) | < 50ms |
| Rollback N blocks | Rare | < 1s |
| Epoch snapshot | Per-epoch (~5 days) | < 30s |
| Crash recovery | Rare | < 60s |

## Candidates Evaluated

### Arrow + DuckDB + Feather
[Evaluation with benchmark results]

### LMDB
[Evaluation with benchmark results]

### RocksDB
[Evaluation with benchmark results]

### SQLite
[Evaluation with benchmark results]

## Decision

[Recommendation with rationale, linking to spec sections for storage requirements]
```

- [ ] **Step 4: Update storage subsystem page**

Populate `docs/reference/subsystems/storage.md` with the data architecture findings.

- [ ] **Step 5: Commit**

```bash
git add docs/reference/data-architecture.md docs/reference/subsystems/storage.md
git commit -m "feat(m1.7): data architecture evaluation — Arrow/DuckDB/Feather vs alternatives

Prompt: Evaluate Arrow/DuckDB/Feather stack against traditional storage
approaches (LMDB, RocksDB, SQLite) for Cardano node data access patterns.
Benchmark results for insert throughput, lookup latency, and memory footprint.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Chunk 4: Wave 4 — Haskell Mapping + Test Strategy (M1.5, M1.8)

### Task 8: Haskell code and discussion mapping (M1.5)

**Files:**
- Create: `src/vibe_node/research/populate_xrefs.py`
- Modify: `docs/reference/subsystems/*.md` (Haskell structure sections)
- Modify: `docs/specs/gap-analysis.md` (new entries)

- [ ] **Step 1: Create cross-reference population helper**

Create `src/vibe_node/research/populate_xrefs.py` — a helper for batch cross-reference population:

```python
"""Cross-reference population helper for M1.5.

Usage:
    uv run python -m vibe_node.research.populate_xrefs --subsystem ledger
    uv run python -m vibe_node.research.populate_xrefs --subsystem networking --type discusses
"""
import asyncio
import uuid
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from vibe_node.db.session import get_raw_connection
from vibe_node.db.xref import add_xref

console = Console()
app = typer.Typer()


async def find_implementing_code(conn, spec_section_id: uuid.UUID, search_terms: list[str]) -> list[dict]:
    """Search code_chunks for functions that likely implement a spec rule."""
    results = []
    for term in search_terms:
        rows = await conn.fetch(
            """SELECT id, repo, function_name, module_name, file_path, release_tag
            FROM code_chunks WHERE content ILIKE $1 ORDER BY release_tag DESC LIMIT 10""",
            f"%{term}%",
        )
        results.extend([dict(r) for r in rows])
    return results


async def find_related_discussions(conn, search_terms: list[str]) -> list[dict]:
    """Search issues and PRs for discussions of a spec rule."""
    results = []
    for term in search_terms:
        issues = await conn.fetch(
            """SELECT id, repo, issue_number, title, 'github_issue' as type
            FROM github_issues WHERE content_combined ILIKE $1 LIMIT 10""",
            f"%{term}%",
        )
        prs = await conn.fetch(
            """SELECT id, repo, pr_number, title, 'github_pr' as type
            FROM github_pull_requests WHERE content_combined ILIKE $1 LIMIT 10""",
            f"%{term}%",
        )
        results.extend([dict(r) for r in issues])
        results.extend([dict(r) for r in prs])
    return results


async def populate_for_subsystem(subsystem: str, relationship: Optional[str] = None):
    """Find and create cross-references for all spec sections in a subsystem."""
    async with get_raw_connection() as conn:
        sections = await conn.fetch(
            "SELECT id, section_id, title, extracted_rule FROM spec_sections WHERE subsystem = $1",
            subsystem,
        )
        console.print(f"Found {len(sections)} spec sections for subsystem={subsystem}")

        for section in sections:
            console.print(f"\n[bold]{section['section_id']}[/bold]: {section['title']}")

            # Extract key terms from the extracted rule for searching
            rule_words = section['title'].split()
            search_terms = [section['title']] + [w for w in rule_words if len(w) > 4]

            if not relationship or relationship == "implements":
                code_matches = await find_implementing_code(conn, section['id'], search_terms)
                for match in code_matches:
                    console.print(f"  [green]implements[/green] {match['function_name']} ({match['module_name']})")
                    await add_xref(conn, "spec_section", section['id'],
                                   "code_chunk", match['id'], "implements",
                                   confidence=0.7, created_by="agent")

            if not relationship or relationship == "discusses":
                discussions = await find_related_discussions(conn, search_terms)
                for disc in discussions:
                    label = f"#{disc.get('issue_number', disc.get('pr_number', '?'))}"
                    console.print(f"  [blue]discusses[/blue] {disc['type']} {label}: {disc['title']}")
                    await add_xref(conn, "spec_section", section['id'],
                                   disc['type'], disc['id'], "discusses",
                                   confidence=0.5, created_by="agent")


@app.command()
def populate(
    subsystem: str = typer.Argument(help="Subsystem to populate cross-references for"),
    relationship: str | None = typer.Option(None, "--type", "-t", help="Only populate this relationship type"),
):
    """Populate cross-references for a subsystem's spec sections."""
    asyncio.run(populate_for_subsystem(subsystem, relationship))


if __name__ == "__main__":
    app()
```

- [ ] **Step 2: Map spec rules to Haskell modules**

For each subsystem, run the population helper and review/refine matches:

```bash
# Run for each subsystem
uv run python -m vibe_node.research.populate_xrefs serialization --type implements
uv run python -m vibe_node.research.populate_xrefs networking --type implements
uv run python -m vibe_node.research.populate_xrefs ledger --type implements
# ... etc for all subsystems
```

Review the output. For high-confidence matches, the auto-detected links (confidence=0.7) are kept. For uncertain matches, manually add or remove via CLI:

```bash
# Add a manual cross-reference
uv run vibe-node db xref add spec_section <spec-uuid> code_chunk <code-uuid> implements --confidence 1.0

# Query what's linked to a spec section
uv run vibe-node db xref query spec_section <spec-uuid>
```

- [ ] **Step 3: Map spec rules to GitHub discussions**

```bash
uv run python -m vibe_node.research.populate_xrefs ledger --type discusses
uv run python -m vibe_node.research.populate_xrefs consensus --type discusses
# ... etc
```

- [ ] **Step 4: Document divergences as gap analysis entries**

When cross-referencing reveals differences between what the spec says and what the Haskell code does, create entries in `docs/specs/gap-analysis.md` using the standard format from CLAUDE.md.

- [ ] **Step 5: Update subsystem pages**

Populate the "Haskell Structure" section in each `docs/reference/subsystems/*.md` with:
- Key Haskell modules and their roles
- How the reference implementation organizes this subsystem
- Notable design decisions from GitHub discussions

- [ ] **Step 6: Verify cross-reference coverage**

```bash
uv run vibe-node db xref coverage
```

Check that the majority of critical/high priority spec sections now have `implements` cross-references.

- [ ] **Step 7: Commit**

```bash
git add docs/reference/subsystems/ docs/specs/gap-analysis.md
git commit -m "feat(m1.5): Haskell code and discussion mapping — spec ↔ code cross-references

Prompt: Map spec rules to implementing Haskell functions and relevant GitHub
discussions. Populate cross_references table. Document spec-vs-Haskell
divergences as gap analysis entries.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

### Task 9: Test strategy and specifications (M1.8)

**Files:**
- Create: `docs/reference/test-strategy.md`
- Modify: `docs/reference/subsystems/*.md` (test strategy sections)

- [ ] **Step 1: Write the test strategy document**

Create `docs/reference/test-strategy.md`:

```markdown
# Test Strategy

vibe-node uses five types of tests, each catching different classes of bugs.
Unlike the Haskell node, we have the advantage of testing against a running
reference implementation — the Haskell node is our oracle.

## Test Taxonomy

| Type | Tool | What It Catches |
|------|------|----------------|
| **Unit** | pytest | Concrete input/output correctness |
| **Property** | Hypothesis | Spec invariant violations across value ranges |
| **Historical Replay** | pytest + Ogmios | Regression against real mainnet history |
| **A/B Conformance** | Hypothesis + both nodes | Behavioral divergence on synthetic inputs |
| **Integration** | pytest + Docker Compose | End-to-end subsystem interaction |

## Unit Tests (pytest)

For each Haskell test identified during research, we plan a corresponding
Python test. These are concrete tests: given this input, expect this output.

### Pattern

​```python
def test_utxo_valid_transfer():
    """Spec: shelley-ledger:rule-7.3 — UTxO transition."""
    tx = build_transfer_tx(from_addr, to_addr, amount=1_000_000)
    utxo_state = UTxOState(initial_utxos)
    result = apply_tx(utxo_state, tx)
    assert result.is_valid
    assert result.consumed == {tx.inputs[0]}
    assert result.produced == set(tx.outputs)
​```

## Property-Based Tests (Hypothesis)

For each spec rule, we define the invariant and the value ranges.

### Pattern

​```python
from hypothesis import given, strategies as st

@given(
    amount=st.integers(min_value=0, max_value=45_000_000_000_000_000),
    fee=st.integers(min_value=MIN_FEE, max_value=MAX_LOVELACE),
)
def test_utxo_conservation(amount, fee):
    """Spec: shelley-ledger:rule-7.3 — Total ADA conserved."""
    tx = build_simple_tx(input_value=amount + fee, output_value=amount, fee=fee)
    utxo_before = UTxOState(...)
    utxo_after = apply_tx(utxo_before, tx)
    assert total_lovelace(utxo_before) == total_lovelace(utxo_after)
​```

## Historical Replay Tests

Pull blocks from the Haskell node and replay through our validation.

​```python
@pytest.fixture
def mainnet_blocks():
    """Fetch N blocks from Ogmios starting at a known slot."""
    return ogmios_client.fetch_blocks(start_slot=100_000_000, count=1000)

def test_replay_mainnet_blocks(mainnet_blocks):
    for block in mainnet_blocks:
        result = validate_block(ledger_state, block)
        assert result.is_valid, f"Block {block.slot} failed: {result.error}"
        ledger_state = result.new_state
​```

## A/B Conformance Tests

Generate synthetic transactions and submit to both nodes.

​```python
@given(tx=cardano_transaction_strategy())
def test_ab_conformance(tx, haskell_node, vibe_node):
    """Both nodes must agree on validity."""
    haskell_result = haskell_node.validate(tx)
    vibe_result = vibe_node.validate(tx)
    assert haskell_result.is_valid == vibe_result.is_valid, (
        f"Disagreement on tx {tx.id}: "
        f"haskell={haskell_result}, vibe={vibe_result}"
    )
​```

## Integration Tests

End-to-end tests using the Docker Compose stack.

​```python
@pytest.mark.integration
async def test_chain_sync_follows_tip(docker_compose):
    """vibe-node syncs to the same tip as the Haskell node."""
    haskell_tip = await ogmios.query_tip()
    vibe_tip = await vibe_node.query_tip()
    assert abs(haskell_tip.slot - vibe_tip.slot) < 2160
​```

## Coverage Dashboard

Run `vibe-node db coverage` to see which spec rules have planned tests:

​```bash
$ vibe-node db coverage
Spec Coverage Report

  Total spec sections:    847
  With implementation:    312
  With planned tests:     623
  Uncovered (neither):    89
​```
```

- [ ] **Step 2: Populate test_specifications for all spec rules**

For each `spec_sections` row (especially critical and high priority), create corresponding `test_specifications` entries. Use the cross-references from M1.5 to identify Haskell tests to mirror.

```bash
# Check how many spec sections exist
uv run vibe-node db status

# Start populating test specs per subsystem
# This is interactive research work — for each spec rule, determine:
# 1. What test type(s) apply
# 2. What Haskell test mirrors it (if any)
# 3. For property tests: what Hypothesis strategy and value ranges
# 4. Priority and phase assignment
```

- [ ] **Step 3: Update subsystem pages with test strategy**

For each `docs/reference/subsystems/*.md`, populate the "Test Strategy" section with the planned tests for that subsystem.

- [ ] **Step 4: Verify coverage**

```bash
uv run vibe-node db xref coverage
uv run vibe-node db test-specs list --priority critical
uv run vibe-node db test-specs list --priority high
```

Verify: all critical/high priority spec sections have at least one planned test.

- [ ] **Step 5: Commit**

```bash
git add docs/reference/test-strategy.md docs/reference/subsystems/
git commit -m "feat(m1.8): test strategy and specifications — 5-type taxonomy, planned tests per spec rule

Prompt: Design test strategy covering unit, property, historical replay,
A/B conformance, and integration tests. Populate test_specifications for
all critical/high priority spec rules with type, strategy, and phase.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Chunk 5: Wave 5 — Architecture Blueprint Synthesis (M1.9)

### Task 10: Synthesize architecture blueprint (M1.9)

**Files:**
- Modify: `docs/reference/subsystems/*.md` (finalize all sections)
- Modify: `docs/reference/architecture.md` (update with full blueprint)
- Modify: `docs/development/milestones.md` (finalize Phase 2-6)
- Modify: `mkdocs.yml` (any final nav adjustments)

- [ ] **Step 1: Finalize all subsystem pages**

Review each `docs/reference/subsystems/*.md` and ensure all sections are populated:
- Governing Specs (from M1.4)
- Module Decomposition (from M1.1 + M1.4)
- Haskell Structure (from M1.5)
- Library Recommendations (from M1.6)
- Test Strategy (from M1.8)
- Phase Assignment

- [ ] **Step 2: Update the main architecture page**

Update `docs/reference/architecture.md` to replace the placeholder with the full architecture overview:
- Updated high-level component diagram reflecting all 10 subsystems
- Data flow overview showing how a block moves through the system
- Link to each subsystem's detailed page
- Link to data architecture decision
- Link to test strategy

- [ ] **Step 3: Finalize phase sequencing in milestones**

Update `docs/development/milestones.md` with module-level detail for Phase 2-6. Each phase should list:
- Which subsystem modules are included
- Key deliverables
- Entry criteria (what research must be complete)
- Exit criteria (what tests must pass)

- [ ] **Step 4: Run final coverage check**

```bash
uv run vibe-node db xref coverage
uv run vibe-node db test-specs list --status planned | wc -l
uv run vibe-node db status
```

Verify exit criteria:
1. All subsystems decomposed to module level
2. All identified spec rules have `spec_sections` rows
3. All critical/high priority rules have planned tests
4. Library decisions made for every subsystem
5. Data architecture decided
6. Phases 2-6 sequenced with module detail
7. Both documentation tiers published
8. Coverage shows no critical/high gaps
9. Gap analysis entries documented

- [ ] **Step 5: Full documentation build verification**

```bash
uv run mkdocs build --strict
```

Fix any warnings or broken links.

- [ ] **Step 6: Commit**

```bash
git add docs/ mkdocs.yml
git commit -m "feat(m1.9): architecture blueprint synthesis — finalized subsystem docs, phase sequencing

Prompt: Synthesize all Phase 1 research into the final architecture blueprint.
Finalize subsystem documentation, phase sequencing, and verify all exit criteria.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1 Complete Checklist

- [ ] M1.1: 10 subsystems identified with boundaries, specs, dependencies
- [ ] M1.2: "How It Works" pages with SVG infographics published
- [ ] M1.3: `spec_sections`, `cross_references`, `test_specifications` tables live with CLI
- [ ] M1.4: Spec rules extracted (target: 500-2000 rows in `spec_sections`)
- [ ] M1.5: Cross-references linking specs ↔ code ↔ discussions populated
- [ ] M1.6: Library audit complete with build/use/fork per subsystem
- [ ] M1.7: Data architecture decided with benchmark results
- [ ] M1.8: Test strategy document + all critical/high spec rules have planned tests
- [ ] M1.9: Architecture blueprint synthesized, phases 2-6 sequenced
- [ ] Gap analysis entries documented for all spec-vs-Haskell divergences found
- [ ] `vibe-node db coverage` shows no critical/high priority gaps
- [ ] `uv run mkdocs build --strict` passes
- [ ] All changes committed and pushed
