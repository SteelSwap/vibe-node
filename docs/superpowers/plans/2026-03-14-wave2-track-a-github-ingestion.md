# Wave 2 Track A: Shared Infrastructure + GitHub Ingestion

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared embedding/DB infrastructure and the GitHub issues+PRs ingestion pipeline, proving the full ingest→embed→store→query flow end-to-end with real data.

**Architecture:** Native Python modules in the vibe-node package (not separate Docker containers). The CLI commands run the pipelines directly, connecting to ParadeDB and Ollama via their exposed Docker ports. This is simpler, more testable, and avoids building custom Dockerfiles for each pipeline.

**Tech Stack:** httpx (GitHub API + Ollama API), asyncpg/SQLModel (ParadeDB), typer (CLI)

---

## File Structure

```
src/vibe_node/
├── embed/
│   ├── __init__.py
│   └── client.py          # Ollama embedding client
├── db/
│   ├── __init__.py
│   ├── engine.py           # (exists) async engine config
│   ├── init.py             # (exists) db init script
│   ├── models.py           # (exists) SQLModel definitions
│   └── session.py          # async session management
├── ingest/
│   ├── __init__.py
│   ├── github.py           # GitHub issues + PRs ingestion
│   └── config.py           # ingestion configuration (repos, tokens)
├── cli.py                  # (exists) add ingest subcommands
└── __init__.py             # (exists)

tests/
├── __init__.py
├── test_embed_client.py    # embedding client tests
├── test_github_ingest.py   # github ingestion tests
└── conftest.py             # shared fixtures
```

---

## Chunk 1: Shared Infrastructure

### Task 1: Add httpx dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add httpx to dependencies**

Add `httpx>=0.28` to the project dependencies in pyproject.toml.

- [ ] **Step 2: Sync**

Run: `uv sync`
Expected: httpx installs successfully

---

### Task 2: Ollama embedding client

**Files:**
- Create: `src/vibe_node/embed/__init__.py`
- Create: `src/vibe_node/embed/client.py`
- Create: `tests/test_embed_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embed_client.py
"""Tests for the Ollama embedding client."""
import pytest
from unittest.mock import AsyncMock, patch

from vibe_node.embed.client import EmbeddingClient


@pytest.mark.asyncio
async def test_embed_single_text():
    """Embedding a single text returns a list of floats."""
    client = EmbeddingClient(base_url="http://localhost:11434")
    mock_response = {
        "data": [{"embedding": [0.1] * 1536, "index": 0}],
        "model": "test",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }
    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        result = await client.embed("hello world")
        assert len(result) == 1536
        assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_batch():
    """Embedding a batch returns a list of embedding vectors."""
    client = EmbeddingClient(base_url="http://localhost:11434")
    mock_response = {
        "data": [
            {"embedding": [0.1] * 1536, "index": 0},
            {"embedding": [0.2] * 1536, "index": 1},
        ],
        "model": "test",
        "usage": {"prompt_tokens": 10, "total_tokens": 10},
    }
    with patch.object(client._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.json.return_value = mock_response
        mock_post.return_value.status_code = 200
        mock_post.return_value.raise_for_status = lambda: None
        results = await client.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert all(len(v) == 1536 for v in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embed_client.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```python
# src/vibe_node/embed/__init__.py
"""Embedding client for Ollama."""

# src/vibe_node/embed/client.py
"""Ollama-compatible embedding client.

Uses the OpenAI-compatible /v1/embeddings endpoint that Ollama exposes.
"""

import os

import httpx

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "hf.co/jinaai/jina-code-embeddings-1.5b-GGUF:Q8_0",
)


class EmbeddingClient:
    """Async client for generating embeddings via Ollama."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = EMBEDDING_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string. Returns a 1536-dim vector."""
        response = await self._client.post(
            f"{self.base_url}/v1/embeddings",
            json={"model": self.model, "input": text},
        )
        response.raise_for_status()
        return response.json()["data"][0]["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns a list of vectors."""
        response = await self._client.post(
            f"{self.base_url}/v1/embeddings",
            json={"model": self.model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()["data"]
        # Sort by index to ensure order matches input
        data.sort(key=lambda x: x["index"])
        return [d["embedding"] for d in data]

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embed_client.py -v`
Expected: PASS

- [ ] **Step 5: Integration test against live Ollama**

Run manually (requires Docker stack running):
```python
import asyncio
from vibe_node.embed.client import EmbeddingClient

async def test():
    client = EmbeddingClient()
    vec = await client.embed("Ouroboros Praos VRF")
    print(f"Dims: {len(vec)}")
    await client.close()

asyncio.run(test())
```
Expected: `Dims: 1536`

---

### Task 3: Async DB session management

**Files:**
- Create: `src/vibe_node/db/session.py`

- [ ] **Step 1: Write session helper**

```python
# src/vibe_node/db/session.py
"""Async database session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vibe_node.db.engine import get_engine


@asynccontextmanager
async def get_session(url: str | None = None) -> AsyncGenerator[AsyncSession]:
    """Yield an async database session."""
    engine = get_engine(url) if url else get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from vibe_node.db.session import get_session; print('OK')"`
Expected: `OK`

---

## Chunk 2: GitHub Issues & PRs Ingestion

### Task 4: Ingestion config

**Files:**
- Create: `src/vibe_node/ingest/__init__.py`
- Create: `src/vibe_node/ingest/config.py`

- [ ] **Step 1: Write config module**

```python
# src/vibe_node/ingest/__init__.py
"""Ingestion pipelines for the vibe-node knowledge base."""

# src/vibe_node/ingest/config.py
"""Configuration for ingestion pipelines."""

import os

# GitHub API token (required for reasonable rate limits)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Repositories to track for issues and PRs
GITHUB_REPOS = [
    "IntersectMBO/cardano-node",
    "IntersectMBO/cardano-ledger",
    "IntersectMBO/ouroboros-network",
    "IntersectMBO/ouroboros-consensus",
    "IntersectMBO/plutus",
    "IntersectMBO/formal-ledger-specifications",
    "cardano-foundation/CIPs",
]

# Database URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://vibenode:vibenode@localhost:5432/vibenode",
)

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "hf.co/jinaai/jina-code-embeddings-1.5b-GGUF:Q8_0",
)
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from vibe_node.ingest.config import GITHUB_REPOS; print(len(GITHUB_REPOS), 'repos')"`
Expected: `7 repos`

---

### Task 5: GitHub ingestion pipeline

**Files:**
- Create: `src/vibe_node/ingest/github.py`
- Create: `tests/test_github_ingest.py`

- [ ] **Step 1: Write tests for GitHub API fetching**

```python
# tests/test_github_ingest.py
"""Tests for GitHub issues and PRs ingestion."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vibe_node.ingest.github import GitHubIngestor


@pytest.mark.asyncio
async def test_fetch_issues_page():
    """Fetching a page of issues returns parsed issue data."""
    ingestor = GitHubIngestor(token="fake-token")
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "number": 1,
            "title": "Test issue",
            "body": "Issue body",
            "state": "open",
            "labels": [{"name": "bug"}],
            "created_at": "2024-01-01T00:00:00Z",
            "closed_at": None,
            "updated_at": "2024-01-02T00:00:00Z",
            "user": {"login": "testuser"},
            "comments": 2,
            "pull_request": None,
        }
    ]
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.headers = {"X-RateLimit-Remaining": "100"}

    with patch.object(ingestor._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        issues = await ingestor._fetch_issues_page("IntersectMBO/cardano-node", page=1)
        assert len(issues) == 1
        assert issues[0]["number"] == 1
        assert issues[0]["title"] == "Test issue"


@pytest.mark.asyncio
async def test_fetch_issue_comments():
    """Fetching comments returns all comments for an issue."""
    ingestor = GitHubIngestor(token="fake-token")
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "id": 100,
            "body": "This is a comment",
            "created_at": "2024-01-02T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "user": {"login": "reviewer"},
        }
    ]
    mock_response.status_code = 200
    mock_response.raise_for_status = lambda: None
    mock_response.headers = {"X-RateLimit-Remaining": "100"}

    with patch.object(ingestor._client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        comments = await ingestor._fetch_issue_comments(
            "IntersectMBO/cardano-node", issue_number=1
        )
        assert len(comments) == 1
        assert comments[0]["id"] == 100


@pytest.mark.asyncio
async def test_build_content_combined():
    """content_combined concatenates title + body + all comments."""
    ingestor = GitHubIngestor(token="fake-token")
    issue = {
        "title": "Bug in VRF",
        "body": "VRF verification fails",
    }
    comments = [
        {"user": {"login": "alice"}, "created_at": "2024-01-02T00:00:00Z", "body": "Can reproduce"},
        {"user": {"login": "bob"}, "created_at": "2024-01-03T00:00:00Z", "body": "Fixed in PR #42"},
    ]
    combined = ingestor._build_content_combined(issue, comments)
    assert "Bug in VRF" in combined
    assert "VRF verification fails" in combined
    assert "alice" in combined
    assert "Can reproduce" in combined
    assert "Fixed in PR #42" in combined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the GitHub ingestor**

The implementation should:
- Use httpx async client with GitHub API token
- Paginate through all issues and PRs for each repo
- Fetch all comments for each issue/PR
- Build content_combined with separators
- Respect rate limits (check X-RateLimit-Remaining header, sleep when low)
- Support both issues and PRs (PRs are issues with a `pull_request` field on GitHub API)
- Log progress (repo, page, issues processed)

Key methods:
- `_fetch_issues_page(repo, page, state="all")` — fetch one page of issues
- `_fetch_issue_comments(repo, issue_number)` — fetch all comments for an issue
- `_fetch_pr_reviews(repo, pr_number)` — fetch review comments for a PR
- `_fetch_pr_review_comments(repo, pr_number)` — fetch line-level review comments
- `_build_content_combined(issue, comments)` — concatenate into searchable text
- `ingest_repo(repo, session, embed_client)` — ingest all issues+PRs for one repo
- `ingest_all(session, embed_client)` — ingest all configured repos

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_github_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Add pytest and pytest-asyncio dev dependencies**

Run: `uv add --dev pytest pytest-asyncio`

---

### Task 6: CLI ingest commands

**Files:**
- Modify: `src/vibe_node/cli.py`

- [ ] **Step 1: Add ingest subcommand group**

Add to cli.py:
- `ingest_app = typer.Typer(help="Data ingestion commands.")`
- `app.add_typer(ingest_app, name="ingest")`
- `vibe-node ingest issues` — runs GitHub issues+PRs ingestion for all repos
- `vibe-node ingest issues --repo IntersectMBO/cardano-node` — single repo

The command should:
- Check that ParadeDB and Ollama are reachable
- Run the async ingestion pipeline
- Report progress (repos processed, issues/PRs ingested, comments stored)
- Handle keyboard interrupt gracefully

- [ ] **Step 2: Test CLI help renders**

Run: `uv run vibe-node ingest --help`
Expected: Shows `issues` subcommand

---

## Chunk 3: Integration Testing

### Task 7: End-to-end test against live stack

This is NOT an automated test — it's a manual verification against the running Docker Compose stack.

- [ ] **Step 1: Start the stack**

Verify: `docker compose ps` shows paradedb (healthy), ollama (healthy)

- [ ] **Step 2: Reset the database**

Run: `uv run vibe-node db reset --yes` (then confirm)

- [ ] **Step 3: Run ingestion for a single small repo**

Run: `uv run vibe-node ingest issues --repo IntersectMBO/formal-ledger-specifications`

This repo has fewer issues than cardano-node, so it's faster to test with.

Expected:
- Issues fetched from GitHub API
- Comments fetched for each issue
- Embeddings generated via Ollama
- Data stored in ParadeDB
- No errors

- [ ] **Step 4: Verify data in database**

Run: `uv run vibe-node db status`

Expected: `github_issues` and `github_issue_comments` have non-zero row counts.

- [ ] **Step 5: Verify embeddings exist**

```bash
docker compose exec -T paradedb psql -U vibenode -d vibenode -c \
  "SELECT title, embedding IS NOT NULL as has_embedding FROM github_issues LIMIT 5;"
```

Expected: All rows show `has_embedding = t`

- [ ] **Step 6: Test a search query**

```bash
docker compose exec -T paradedb psql -U vibenode -d vibenode -c \
  "SELECT title, left(body, 80) FROM github_issues ORDER BY embedding <-> (
    SELECT embedding FROM github_issues LIMIT 1
  ) LIMIT 5;"
```

Expected: Returns similar issues ranked by vector similarity.

- [ ] **Step 7: Present results to Elder Millenial for review**

Show:
- Number of issues/comments/PRs ingested
- Sample data from the database
- Embedding verification results
- Any errors or warnings encountered

**DO NOT COMMIT until Elder Millenial explicitly approves.**
