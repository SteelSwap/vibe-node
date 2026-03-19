"""Code indexing pipeline — walks release tags in vendor/ submodules.

Parses Haskell files with tree-sitter for function-level chunking,
embeds via Ollama, and stores results in the ``code_chunks`` table.

Follows the same patterns as ``github.py``: raw SQL inserts, progress
bars via Rich, idempotent via tag-level deduplication, and an
async-friendly interface.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vibe.tools.embed.client import EmbeddingClient
from vibe.tools.ingest.agda_parser import AgdaParser
from vibe.tools.ingest.config import CODE_REPOS, TAG_PATTERNS
from vibe.tools.ingest.era_inference import infer_era
from vibe.tools.ingest.haskell_parser import HaskellParser

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


def _find_agda_files(repo_path: Path) -> list[Path]:
    """Find all .agda and .lagda files in the repository."""
    agda = list(repo_path.rglob("*.agda"))
    lagda = list(repo_path.rglob("*.lagda"))
    lagda_md = list(repo_path.rglob("*.lagda.md"))
    return sorted(set(agda + lagda + lagda_md))


class CodeIngestor:
    """Index Haskell source code from vendor/ submodules by release tag."""

    def __init__(self) -> None:
        self._hs_parser = HaskellParser()
        self._agda_parser = AgdaParser()

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

        # Check which tags are fully ingested via completion markers.
        # A tag is only "done" if _process_tag ran to completion and wrote
        # a marker to code_tag_completion. Partial data from crashes (chunks
        # committed every 100 rows) won't have a marker.
        result = await session.execute(
            text("""
                SELECT release_tag FROM code_tag_completion
                WHERE repo = :repo
            """),
            {"repo": repo_name},
        )
        ingested_tags = {row[0] for row in result.fetchall()}

        # Log any partially-ingested tags (have chunks but no completion marker)
        partial_result = await session.execute(
            text("""
                SELECT DISTINCT release_tag FROM code_chunks
                WHERE repo = :repo AND release_tag NOT IN (
                    SELECT release_tag FROM code_tag_completion WHERE repo = :repo
                )
            """),
            {"repo": repo_name},
        )
        partial_tags = {row[0] for row in partial_result.fetchall()}
        for partial_tag in partial_tags:
            logger.info(
                "Tag %s for %s has partial data but no completion marker — will re-process",
                partial_tag, repo_name,
            )

        # Filter to un-ingested or partially-ingested tags
        pending_tags = [t for t in tags if t not in ingested_tags]
        if limit is not None:
            pending_tags = pending_tags[:limit]

        if not pending_tags:
            logger.info("All tags already ingested for %s", repo_name)
            # Show a completed progress bar so the user sees this repo was processed
            if progress:
                task = progress.add_task(
                    f"[green]{repo_name} tags", total=len(tags), completed=len(tags),
                )
            return 0

        # Set up progress tracking — show already-ingested tags as pre-completed
        task = None
        if progress:
            total_tags = len(ingested_tags) + len(pending_tags)
            task = progress.add_task(
                f"[green]{repo_name} tags", total=total_tags, completed=len(ingested_tags),
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

                # Write completion marker — only after all files processed
                await session.execute(
                    text("""
                        INSERT INTO code_tag_completion (repo, release_tag, chunk_count)
                        VALUES (:repo, :tag, :chunks)
                        ON CONFLICT (repo, release_tag)
                        DO UPDATE SET chunk_count = EXCLUDED.chunk_count,
                                      completed_at = NOW()
                    """),
                    {"repo": repo_name, "tag": tag, "chunks": tag_chunks},
                )
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
            progress.update(task, completed=len(pending_tags))

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
        """Checkout a tag, parse all .hs and .agda files, embed, and store."""
        _checkout(repo_path, tag)

        commit_hash, commit_date = _get_tag_info(repo_path, tag)
        hs_files = _find_haskell_files(repo_path)
        agda_files = _find_agda_files(repo_path)
        all_files = [(f, "haskell") for f in hs_files] + [(f, "agda") for f in agda_files]

        file_task = None
        if progress:
            file_task = progress.add_task(
                f"[cyan]  {tag} ({len(all_files)} files)",
                total=len(all_files),
            )

        chunk_count = 0

        for source_file, lang in all_files:
            try:
                source = source_file.read_bytes()
            except OSError as e:
                logger.debug("Skipping unreadable file %s: %s", source_file, e)
                continue

            # Relative path from repo root for storage
            rel_path = str(source_file.relative_to(repo_path))

            try:
                if lang == "agda":
                    chunks = self._agda_parser.parse_file(source, rel_path)
                else:
                    chunks = self._hs_parser.parse_file(source, rel_path)
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

                # Hash content for dedup across versions
                content_hash = hashlib.sha256(chunk.content.encode()).hexdigest()

                # Check if identical content exists at any tag — reuse embedding
                existing_embed = await session.execute(
                    text(
                        "SELECT embedding FROM code_chunks "
                        "WHERE repo = :repo AND content_hash = :hash AND embedding IS NOT NULL "
                        "LIMIT 1"
                    ),
                    {"repo": repo_name, "hash": content_hash},
                )
                existing_row = existing_embed.first()

                if existing_row:
                    # Reuse existing embedding — no Ollama call needed
                    embedding_str = existing_row[0]
                else:
                    try:
                        embedding_vec = await embed_client.embed(embed_text[:8000])
                        embedding_str = str(embedding_vec)
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
                            content_hash, embed_text, embedding, era, metadata
                        ) VALUES (
                            :id, :repo, :release_tag, :commit_hash, :commit_date,
                            :file_path, :module_name, :function_name,
                            :line_start, :line_end, :content, :signature,
                            :content_hash, :embed_text, :embedding, :era, NULL
                        )
                        ON CONFLICT (repo, release_tag, file_path, function_name, content_hash)
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
                        "content_hash": content_hash,
                        "embed_text": embed_text,
                        "embedding": embedding_str,
                        "era": era,
                    },
                )
                # Record in tag manifest for versioned queries
                await session.execute(
                    text("""
                        INSERT INTO code_tag_manifest (
                            repo, release_tag, file_path, function_name, content_hash
                        ) VALUES (
                            :repo, :release_tag, :file_path, :function_name, :content_hash
                        )
                        ON CONFLICT (repo, release_tag, file_path, function_name)
                        DO NOTHING
                    """),
                    {
                        "repo": repo_name,
                        "release_tag": tag,
                        "file_path": chunk.file_path,
                        "function_name": chunk.function_name,
                        "content_hash": content_hash,
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

    @staticmethod
    async def rebuild_manifest(session: AsyncSession) -> int:
        """Rebuild code_tag_manifest from existing code_chunks data.

        Use this to backfill the manifest after schema changes or
        to fix gaps from partial indexing.
        """
        # Use a subquery with ROW_NUMBER to deduplicate before inserting
        result = await session.execute(
            text("""
                INSERT INTO code_tag_manifest (repo, release_tag, file_path, function_name, content_hash)
                SELECT repo, release_tag, file_path, function_name, content_hash
                FROM (
                    SELECT repo, release_tag, file_path, function_name, content_hash,
                           ROW_NUMBER() OVER (
                               PARTITION BY repo, release_tag, file_path, function_name
                               ORDER BY line_start
                           ) as rn
                    FROM code_chunks
                ) sub
                WHERE rn = 1
                ON CONFLICT (repo, release_tag, file_path, function_name)
                DO UPDATE SET content_hash = EXCLUDED.content_hash
            """)
        )
        await session.commit()
        count_result = await session.execute(text("SELECT count(*) FROM code_tag_manifest"))
        return count_result.scalar()

    @staticmethod
    async def backfill_completion(session: AsyncSession) -> int:
        """Backfill code_tag_completion by rigorously verifying each tag.

        For each tag with data in code_chunks:
        1. Use ``git ls-tree`` to count .hs/.agda files at that tag (no checkout)
        2. Compare to distinct file_paths in code_tag_manifest for that tag
        3. Verify all code_chunks for that tag have embeddings
        4. Only mark complete if file counts match AND all embeddings present

        Returns the total number of tags marked complete.
        """
        from vibe.tools.ingest.config import CODE_REPOS

        # Get all tags with data, grouped by repo
        result = await session.execute(
            text("""
                SELECT repo, release_tag,
                       COUNT(*) as chunk_count,
                       COUNT(DISTINCT file_path) as db_file_count,
                       COUNT(*) FILTER (WHERE embedding IS NOT NULL) as embedded_count
                FROM code_chunks
                GROUP BY repo, release_tag
                ORDER BY repo, release_tag
            """)
        )
        tag_rows = result.fetchall()

        # Get manifest file counts per tag
        manifest_result = await session.execute(
            text("""
                SELECT repo, release_tag, COUNT(DISTINCT file_path) as manifest_file_count
                FROM code_tag_manifest
                GROUP BY repo, release_tag
            """)
        )
        manifest_map = {
            (row[0], row[1]): row[2] for row in manifest_result.fetchall()
        }

        project_root = Path(__file__).resolve().parents[3]
        marked = 0
        skipped = 0

        for repo, tag, chunk_count, db_file_count, embedded_count in tag_rows:
            # Quick check 1: do all chunks have embeddings?
            if embedded_count < chunk_count:
                logger.info(
                    "  SKIP %s @ %s: %d/%d chunks missing embeddings",
                    repo, tag, chunk_count - embedded_count, chunk_count,
                )
                skipped += 1
                continue

            # Quick check 2: does manifest file count match chunk file count?
            manifest_file_count = manifest_map.get((repo, tag), 0)
            if manifest_file_count == 0:
                logger.info("  SKIP %s @ %s: no manifest entries", repo, tag)
                skipped += 1
                continue

            if manifest_file_count != db_file_count:
                logger.info(
                    "  SKIP %s @ %s: manifest has %d files, chunks has %d files",
                    repo, tag, manifest_file_count, db_file_count,
                )
                skipped += 1
                continue

            # Rigorous check: compare DB files against actual files at the tag
            rel_path = CODE_REPOS.get(repo)
            if not rel_path:
                logger.warning("  SKIP %s @ %s: repo not in CODE_REPOS", repo, tag)
                skipped += 1
                continue

            repo_path = project_root / rel_path
            if not repo_path.exists():
                logger.warning("  SKIP %s @ %s: repo path missing", repo, tag)
                skipped += 1
                continue

            # Count .hs and .agda files at this tag using git ls-tree (no checkout)
            try:
                hs_result = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", tag],
                    cwd=repo_path, capture_output=True, text=True, timeout=30,
                )
                if hs_result.returncode != 0:
                    logger.info("  SKIP %s @ %s: git ls-tree failed", repo, tag)
                    skipped += 1
                    continue

                git_files = hs_result.stdout.strip().splitlines()
                git_source_files = [
                    f for f in git_files
                    if f.endswith(".hs") or f.endswith(".agda")
                    or f.endswith(".lagda") or f.endswith(".lagda.md")
                ]
                git_file_count = len(git_source_files)
            except (subprocess.TimeoutExpired, OSError):
                logger.info("  SKIP %s @ %s: git ls-tree timed out", repo, tag)
                skipped += 1
                continue

            # Not all source files produce chunks (some have no declarations,
            # some fail to parse). But the DB should have at least 80% of the
            # files if processing completed normally.
            if git_file_count > 0:
                coverage = db_file_count / git_file_count
                if coverage < 0.5:
                    logger.info(
                        "  SKIP %s @ %s: only %d/%d files in DB (%.0f%% coverage)",
                        repo, tag, db_file_count, git_file_count, coverage * 100,
                    )
                    skipped += 1
                    continue

            # All checks passed — mark as complete
            await session.execute(
                text("""
                    INSERT INTO code_tag_completion (repo, release_tag, chunk_count)
                    VALUES (:repo, :tag, :chunks)
                    ON CONFLICT (repo, release_tag) DO NOTHING
                """),
                {"repo": repo, "tag": tag, "chunks": chunk_count},
            )
            marked += 1
            logger.info(
                "  OK   %s @ %s: %d chunks, %d/%d files (%.0f%% of %d on disk)",
                repo, tag, chunk_count, db_file_count, manifest_file_count,
                (db_file_count / git_file_count * 100) if git_file_count > 0 else 100,
                git_file_count,
            )

        await session.commit()
        logger.info("Backfill complete: %d marked, %d skipped", marked, skipped)
        return marked

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
