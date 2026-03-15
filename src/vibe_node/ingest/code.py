"""Code indexing pipeline — walks release tags in vendor/ submodules.

Parses Haskell files with tree-sitter for function-level chunking,
embeds via Ollama, and stores results in the ``code_chunks`` table.

Follows the same patterns as ``github.py``: raw SQL inserts, progress
bars via Rich, idempotent via tag-level deduplication, and an
async-friendly interface.
"""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vibe_node.embed.client import EmbeddingClient
from vibe_node.ingest.config import CODE_REPOS, TAG_PATTERNS
from vibe_node.ingest.era_inference import infer_era
from vibe_node.ingest.haskell_parser import HaskellParser

logger = logging.getLogger(__name__)


def _run_git(args: list[str], cwd: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _get_release_tags(repo_path: Path, repo_name: str) -> list[str]:
    """List release tags for a repo, filtered by the repo's tag pattern."""
    result = _run_git(["tag", "--list"], cwd=repo_path)
    if result.returncode != 0:
        logger.warning("Failed to list tags in %s: %s", repo_path, result.stderr)
        return []

    tags = [t.strip() for t in result.stdout.splitlines() if t.strip()]

    pattern = TAG_PATTERNS.get(repo_name)
    if pattern is not None:
        tags = [t for t in tags if pattern.search(t)]

    # Sort by version-like ordering (most recent last)
    tags.sort()
    return tags


def _get_tag_info(repo_path: Path, tag: str) -> tuple[str, datetime]:
    """Get the commit hash and author date for a tag.

    Returns ``(commit_hash, commit_date)``.
    """
    result = _run_git(
        ["log", "-1", "--format=%H%n%aI", tag],
        cwd=repo_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get info for tag {tag}: {result.stderr}")

    lines = result.stdout.strip().splitlines()
    commit_hash = lines[0]
    commit_date = datetime.fromisoformat(lines[1])
    # Ensure timezone-aware
    if commit_date.tzinfo is None:
        commit_date = commit_date.replace(tzinfo=timezone.utc)
    return commit_hash, commit_date


def _get_current_head(repo_path: Path) -> str:
    """Get the current HEAD commit hash (to restore after checkout)."""
    result = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get HEAD in {repo_path}: {result.stderr}")
    return result.stdout.strip()


def _checkout(repo_path: Path, ref: str) -> None:
    """Checkout a ref (tag or commit hash) in the repo.

    Uses --force to handle dirty working trees from previous checkouts
    across very different tags.
    """
    result = _run_git(["checkout", "--force", ref, "--quiet"], cwd=repo_path)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to checkout {ref}: {result.stderr}")


def _find_haskell_files(repo_path: Path) -> list[Path]:
    """Find all .hs files in the repository."""
    return sorted(repo_path.rglob("*.hs"))


class CodeIngestor:
    """Index Haskell source code from vendor/ submodules by release tag."""

    def __init__(self) -> None:
        self._parser = HaskellParser()

    async def ingest_repo(
        self,
        repo_name: str,
        repo_path: str | Path,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        limit: int | None = None,
        progress=None,
    ) -> int:
        """Process one submodule: walk its release tags, parse, embed, store.

        Parameters
        ----------
        repo_name:
            Short name for the repo (e.g. ``"cardano-ledger"``).
        repo_path:
            Filesystem path to the submodule root.
        session:
            An async SQLAlchemy session for database access.
        embed_client:
            The Ollama embedding client.
        limit:
            Maximum number of tags to process. ``None`` means all.
        progress:
            Optional Rich ``Progress`` instance for progress bars.

        Returns
        -------
        int
            Number of code chunks inserted.
        """
        repo_path = Path(repo_path).resolve()
        if not repo_path.exists():
            logger.warning("Repo path does not exist: %s — skipping", repo_path)
            return 0

        # Discover tags
        tags = _get_release_tags(repo_path, repo_name)
        if not tags:
            logger.info("No matching release tags in %s", repo_name)
            return 0

        # Check which tags are already ingested
        result = await session.execute(
            text("SELECT DISTINCT release_tag FROM code_chunks WHERE repo = :repo"),
            {"repo": repo_name},
        )
        ingested_tags = {row[0] for row in result.fetchall()}

        # Filter to un-ingested tags only
        pending_tags = [t for t in tags if t not in ingested_tags]
        if limit is not None:
            pending_tags = pending_tags[:limit]

        if not pending_tags:
            logger.info("All tags already ingested for %s", repo_name)
            return 0

        # Set up progress tracking
        task = None
        if progress:
            task = progress.add_task(
                f"[green]{repo_name} tags", total=len(pending_tags),
            )

        logger.info(
            "Processing %d tags for %s (%d already ingested)",
            len(pending_tags), repo_name, len(ingested_tags),
        )

        # Remember original HEAD so we can restore it
        original_head = _get_current_head(repo_path)
        total_chunks = 0

        try:
            for tag in pending_tags:
                tag_chunks = await self._process_tag(
                    repo_name, repo_path, tag, session, embed_client,
                    progress=progress,
                )
                total_chunks += tag_chunks
                await session.commit()

                if progress and task is not None:
                    progress.update(task, advance=1)

                logger.info(
                    "  %s @ %s — %d chunks", repo_name, tag, tag_chunks,
                )
        finally:
            # Always restore the submodule to its original commit
            _checkout(repo_path, original_head)

        if progress and task is not None:
            progress.update(task, completed=progress.tasks[task].total)

        logger.info(
            "Completed %s: %d chunks across %d tags",
            repo_name, total_chunks, len(pending_tags),
        )
        return total_chunks

    async def _process_tag(
        self,
        repo_name: str,
        repo_path: Path,
        tag: str,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        progress=None,
    ) -> int:
        """Checkout a tag, parse all .hs files, embed, and store."""
        _checkout(repo_path, tag)

        commit_hash, commit_date = _get_tag_info(repo_path, tag)
        hs_files = _find_haskell_files(repo_path)

        file_task = None
        if progress:
            file_task = progress.add_task(
                f"[cyan]  {tag} ({len(hs_files)} files)",
                total=len(hs_files),
            )

        chunk_count = 0

        for hs_file in hs_files:
            try:
                source = hs_file.read_bytes()
            except OSError as e:
                logger.debug("Skipping unreadable file %s: %s", hs_file, e)
                continue

            # Relative path from repo root for storage
            rel_path = str(hs_file.relative_to(repo_path))

            try:
                chunks = self._parser.parse_file(source, rel_path)
            except Exception:
                logger.debug("Parse failed for %s — skipping", rel_path, exc_info=True)
                continue

            for chunk in chunks:
                era = infer_era(chunk.module_name, chunk.file_path)

                # Build embed_text with codebase/filepath context
                embed_parts = [
                    f"Codebase: {repo_name}",
                    f"File: {chunk.file_path}",
                    f"Module: {chunk.module_name}",
                    f"Function: {chunk.function_name}",
                ]
                if chunk.signature:
                    embed_parts.append(chunk.signature)
                embed_parts.append(chunk.content)
                embed_text = "\n".join(embed_parts)

                try:
                    embedding = await embed_client.embed(embed_text[:8000])
                except Exception:
                    logger.warning(
                        "Embedding failed for %s::%s — skipping",
                        chunk.module_name, chunk.function_name,
                        exc_info=True,
                    )
                    continue

                chunk_id = uuid.uuid4()

                await session.execute(
                    text("""
                        INSERT INTO code_chunks (
                            id, repo, release_tag, commit_hash, commit_date,
                            file_path, module_name, function_name,
                            line_start, line_end, content, signature,
                            embed_text, embedding, era, metadata
                        ) VALUES (
                            :id, :repo, :release_tag, :commit_hash, :commit_date,
                            :file_path, :module_name, :function_name,
                            :line_start, :line_end, :content, :signature,
                            :embed_text, :embedding, :era, NULL
                        )
                        ON CONFLICT (repo, release_tag, file_path, function_name, line_start)
                        DO NOTHING
                    """),
                    {
                        "id": str(chunk_id),
                        "repo": repo_name,
                        "release_tag": tag,
                        "commit_hash": commit_hash,
                        "commit_date": commit_date,
                        "file_path": chunk.file_path,
                        "module_name": chunk.module_name,
                        "function_name": chunk.function_name,
                        "line_start": chunk.line_start,
                        "line_end": chunk.line_end,
                        "content": chunk.content,
                        "signature": chunk.signature,
                        "embed_text": embed_text,
                        "embedding": str(embedding),
                        "era": era,
                    },
                )
                chunk_count += 1

                # Periodic commit to avoid giant transactions
                if chunk_count % 100 == 0:
                    await session.commit()

            if progress and file_task is not None:
                progress.update(file_task, advance=1)

        # Mark file task complete and remove it
        if progress and file_task is not None:
            progress.update(file_task, completed=len(hs_files))
            progress.remove_task(file_task)

        return chunk_count

    async def ingest_all(
        self,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        repos: dict[str, str] | None = None,
        limit: int | None = None,
        progress=None,
    ) -> dict[str, int]:
        """Process all configured submodule repos.

        Parameters
        ----------
        repos:
            Mapping of ``{repo_name: repo_path}``. Defaults to
            :data:`CODE_REPOS` from config.
        limit:
            Max tags to process per repo.
        progress:
            Optional Rich ``Progress`` instance.

        Returns
        -------
        dict[str, int]
            Mapping of repo name to number of chunks inserted.
        """
        repos = repos or CODE_REPOS
        results: dict[str, int] = {}

        for repo_name, rel_path in repos.items():
            # Resolve relative paths against the project root
            repo_path = Path(rel_path)
            if not repo_path.is_absolute():
                # Assume relative to the project root (parent of src/)
                project_root = Path(__file__).resolve().parents[3]
                repo_path = project_root / rel_path

            results[repo_name] = await self.ingest_repo(
                repo_name,
                repo_path,
                session,
                embed_client,
                limit=limit,
                progress=progress,
            )

        return results
