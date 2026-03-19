# Monorepo Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the vibe-node repo into a uv workspace monorepo with three packages (`vibe-core`, `vibe-cardano`, `vibe-tools`) matching the documented package structure, then verify nothing is broken via Docker Compose.

**Architecture:** Move all existing tooling code (`db/`, `embed/`, `ingest/`, `mcp/`, `research/`, `export_specs.py`) into `packages/vibe-tools/`. Create empty `vibe-core` and `vibe-cardano` package skeletons for Phase 2 code. Keep `src/vibe_node/` as the node binary (CLI only). Restructure tests into typed directories. All imports change from `vibe_node.X` to `vibe.tools.X` for moved modules.

**Tech Stack:** uv workspaces, Python implicit namespace packages (PEP 420)

**Branch:** `chore/monorepo-restructure`

---

### Task 1: Create branch and package skeletons

**Files:**
- Create: `packages/vibe-core/pyproject.toml`
- Create: `packages/vibe-core/src/vibe/core/__init__.py`
- Create: `packages/vibe-cardano/pyproject.toml`
- Create: `packages/vibe-cardano/src/vibe/cardano/__init__.py`
- Create: `packages/vibe-tools/pyproject.toml`
- Create: `packages/vibe-tools/src/vibe/tools/__init__.py`

- [ ] **Step 1: Create branch**

```bash
git checkout main && git pull origin main
git checkout -b chore/monorepo-restructure
```

- [ ] **Step 2: Create vibe-core skeleton**

```bash
mkdir -p packages/vibe-core/src/vibe/core
```

`packages/vibe-core/pyproject.toml`:
```toml
[project]
name = "vibe-core"
version = "0.1.0"
description = "Protocol-agnostic node abstractions"
requires-python = ">=3.14"
dependencies = []

[build-system]
requires = ["uv_build>=0.8.4,<0.9.0"]
build-backend = "uv_build"
```

`packages/vibe-core/src/vibe/core/__init__.py`:
```python
"""vibe.core — Protocol-agnostic node abstractions."""
```

No `__init__.py` at `packages/vibe-core/src/vibe/` (implicit namespace package).

- [ ] **Step 3: Create vibe-cardano skeleton**

```bash
mkdir -p packages/vibe-cardano/src/vibe/cardano
```

`packages/vibe-cardano/pyproject.toml`:
```toml
[project]
name = "vibe-cardano"
version = "0.1.0"
description = "Cardano-specific node implementation"
requires-python = ">=3.14"
dependencies = [
    "vibe-core",
]

[build-system]
requires = ["uv_build>=0.8.4,<0.9.0"]
build-backend = "uv_build"
```

`packages/vibe-cardano/src/vibe/cardano/__init__.py`:
```python
"""vibe.cardano — Cardano-specific node implementation."""
```

- [ ] **Step 4: Create vibe-tools skeleton**

```bash
mkdir -p packages/vibe-tools/src/vibe/tools
```

`packages/vibe-tools/pyproject.toml` — this gets all the current dependencies that the tooling code uses:
```toml
[project]
name = "vibe-tools"
version = "0.1.0"
description = "Development infrastructure — ingestion, MCP, research pipelines"
requires-python = ">=3.14"
dependencies = [
    "anthropic>=0.85.0",
    "asyncpg>=0.31.0",
    "greenlet>=3.3.2",
    "httpx>=0.28.1",
    "mcp>=1.26.0",
    "pydantic-ai>=1.69.0",
    "rich>=14.3.3",
    "sqlmodel>=0.0.37",
    "tree-sitter>=0.25.2",
    "tree-sitter-haskell>=0.23.1",
]

[build-system]
requires = ["uv_build>=0.8.4,<0.9.0"]
build-backend = "uv_build"
```

`packages/vibe-tools/src/vibe/tools/__init__.py`:
```python
"""vibe.tools — Development infrastructure (ingestion, MCP, research)."""
```

- [ ] **Step 5: Commit skeletons**

```bash
git add packages/
git commit -m "chore: create vibe-core, vibe-cardano, vibe-tools package skeletons"
```

### Task 2: Update root pyproject.toml for uv workspace

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add workspace members and update dependencies**

The root `pyproject.toml` declares the workspace and depends on the three packages. The root package (`vibe-node`) is the CLI/node binary — it depends on `vibe-tools` for current functionality and will later depend on `vibe-cardano` for the actual node.

Add workspace section and update dependencies:
```toml
[tool.uv.workspace]
members = ["packages/*"]

[tool.uv.sources]
vibe-core = { workspace = true }
vibe-cardano = { workspace = true }
vibe-tools = { workspace = true }
```

Update `[project] dependencies` to reference workspace packages instead of listing all deps directly:
```toml
dependencies = [
    "vibe-tools",
    "typer>=0.15",
]
```

The heavy dependencies (asyncpg, httpx, mcp, pydantic-ai, etc.) move to vibe-tools' pyproject.toml.

- [ ] **Step 2: Run `uv sync` to verify workspace resolves**

```bash
uv sync
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: configure uv workspace with three package members"
```

### Task 3: Move tooling code to vibe-tools

**Files:**
- Move: `src/vibe_node/db/` → `packages/vibe-tools/src/vibe/tools/db/`
- Move: `src/vibe_node/embed/` → `packages/vibe-tools/src/vibe/tools/embed/`
- Move: `src/vibe_node/ingest/` → `packages/vibe-tools/src/vibe/tools/ingest/`
- Move: `src/vibe_node/mcp/` → `packages/vibe-tools/src/vibe/tools/mcp/`
- Move: `src/vibe_node/research/` → `packages/vibe-tools/src/vibe/tools/research/`
- Move: `src/vibe_node/export_specs.py` → `packages/vibe-tools/src/vibe/tools/export_specs.py`

- [ ] **Step 1: git mv all tooling directories**

```bash
git mv src/vibe_node/db packages/vibe-tools/src/vibe/tools/db
git mv src/vibe_node/embed packages/vibe-tools/src/vibe/tools/embed
git mv src/vibe_node/ingest packages/vibe-tools/src/vibe/tools/ingest
git mv src/vibe_node/mcp packages/vibe-tools/src/vibe/tools/mcp
git mv src/vibe_node/research packages/vibe-tools/src/vibe/tools/research
git mv src/vibe_node/export_specs.py packages/vibe-tools/src/vibe/tools/export_specs.py
```

- [ ] **Step 2: Commit the move (before import rewrites, so git tracks renames)**

```bash
git commit -m "chore: move tooling code to packages/vibe-tools"
```

### Task 4: Rewrite all imports

**Files:**
- Modify: All `.py` files under `packages/vibe-tools/src/vibe/tools/`
- Modify: `src/vibe_node/cli.py`
- Modify: `src/vibe_node/cli_infra.py`
- Modify: `src/vibe_node/cli_xref.py`

- [ ] **Step 1: Rewrite internal imports in vibe-tools**

All `from vibe_node.X` imports within the moved code become `from vibe.tools.X`:

```bash
# In all files under packages/vibe-tools/
find packages/vibe-tools -name "*.py" -exec sed -i '' 's/from vibe_node\./from vibe.tools./g' {} +
find packages/vibe-tools -name "*.py" -exec sed -i '' 's/import vibe_node\./import vibe.tools./g' {} +
```

- [ ] **Step 2: Rewrite CLI imports**

In `src/vibe_node/cli.py`, `cli_infra.py`, `cli_xref.py` — all `from vibe_node.db` / `from vibe_node.ingest` / etc. become `from vibe.tools.db` / `from vibe.tools.ingest` / etc.

```bash
sed -i '' 's/from vibe_node\.db/from vibe.tools.db/g' src/vibe_node/cli.py src/vibe_node/cli_infra.py src/vibe_node/cli_xref.py
sed -i '' 's/from vibe_node\.embed/from vibe.tools.embed/g' src/vibe_node/cli.py
sed -i '' 's/from vibe_node\.ingest/from vibe.tools.ingest/g' src/vibe_node/cli.py
sed -i '' 's/from vibe_node\.research/from vibe.tools.research/g' src/vibe_node/cli.py
sed -i '' 's/from vibe_node\.export_specs/from vibe.tools.export_specs/g' src/vibe_node/cli.py
sed -i '' 's/from vibe_node\.mcp/from vibe.tools.mcp/g' src/vibe_node/cli.py
```

Keep `from vibe_node import __version__` and `from vibe_node.cli_infra` / `from vibe_node.cli_xref` unchanged — those stay in the root package.

- [ ] **Step 3: Update MCP server module path**

The `.mcp.json` runs `python -m vibe_node.mcp.search_server`. Update to `python -m vibe.tools.mcp.search_server`.

- [ ] **Step 4: Verify imports resolve**

```bash
uv run python -c "from vibe.tools.db.pool import get_pool; print('OK')"
uv run python -c "from vibe.tools.mcp.app import mcp; print('OK')"
uv run python -c "from vibe_node.cli import app; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: rewrite all imports from vibe_node.X to vibe.tools.X"
```

### Task 5: Restructure tests

**Files:**
- Move: `tests/test_haskell_parser.py` → `tests/unit/test_haskell_parser.py`
- Move: `tests/test_search.py` → `tests/unit/test_search.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/property/.gitkeep`
- Create: `tests/conformance/.gitkeep`
- Create: `tests/integration/.gitkeep`

- [ ] **Step 1: Create test directories and move files**

```bash
mkdir -p tests/unit tests/property tests/conformance tests/integration
git mv tests/test_haskell_parser.py tests/unit/test_haskell_parser.py
git mv tests/test_search.py tests/unit/test_search.py
touch tests/unit/__init__.py tests/property/.gitkeep tests/conformance/.gitkeep tests/integration/.gitkeep
```

- [ ] **Step 2: Update test imports if needed**

Check if tests import `vibe_node.X` for moved modules and update to `vibe.tools.X`.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "chore: restructure tests into unit/property/conformance/integration"
```

### Task 6: Verify CLI and Docker Compose

- [ ] **Step 1: Verify CLI help works**

```bash
uv run vibe-node --help
uv run vibe-node db --help
uv run vibe-node ingest --help
uv run vibe-node infra --help
uv run vibe-node research --help
```

- [ ] **Step 2: Verify db status (requires running ParadeDB)**

```bash
uv run vibe-node db status
```

- [ ] **Step 3: Verify Docker Compose services**

```bash
uv run vibe-node infra status
```

If services are down:
```bash
uv run vibe-node infra up
# Wait for services to start
uv run vibe-node infra status
uv run vibe-node db status
```

- [ ] **Step 4: Verify MCP server starts**

```bash
uv run python -m vibe.tools.mcp.search_server &
sleep 2
kill %1
```

- [ ] **Step 5: Verify docs build**

```bash
uv run mkdocs build --strict
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 7: Commit any fixes, push, open PR**

```bash
git push origin chore/monorepo-restructure
gh pr create --title "chore: monorepo restructure — vibe-core/vibe-cardano/vibe-tools workspace" --body "..."
```
