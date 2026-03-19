"""Spec ingestion pipeline orchestrator.

Walks spec sources, converts to markdown, chunks, embeds, and stores
in ParadeDB's spec_documents table.

Converted files are cached to data/specs/ so expensive conversions
(PDF OCR, LaTeX pandoc) are not repeated on re-runs. The cache is
keyed by (source_repo, source_path, commit_hash).
"""

import hashlib
import logging
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vibe_node.embed.client import EmbeddingClient
from vibe_node.ingest.specs.chunker import chunk_cddl, chunk_markdown
from vibe_node.ingest.specs.git_history import discover_spec_commits, get_file_at_commit
from vibe_node.ingest.specs.converters.agda import convert_agda
from vibe_node.ingest.specs.converters.cddl import convert_cddl
from vibe_node.ingest.specs.converters.latex import convert_latex
from vibe_node.ingest.specs.converters.markdown import convert_markdown
from vibe_node.ingest.specs.converters.pdf import convert_pdf
from vibe_node.ingest.specs.sources import SPEC_SOURCES, SpecSource

logger = logging.getLogger(__name__)

CONVERTERS = {
    "markdown": convert_markdown,
    "cddl": convert_cddl,
    "agda": convert_agda,
}


def _get_submodule_head(submodule_path: str) -> tuple[str, str]:
    """Get commit hash and ISO date of the submodule's current HEAD."""
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H%n%aI"],
        cwd=submodule_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ("unknown", "1970-01-01T00:00:00+00:00")
    lines = result.stdout.strip().split("\n")
    return (lines[0], lines[1])


def _resolve_files(submodule_path: str, spec_glob: str) -> list[Path]:
    """Resolve a glob pattern to actual files in the submodule."""
    base = Path(submodule_path)
    return sorted(base.glob(spec_glob))


# ── Conversion cache ────────────────────────────────────────────────

CACHE_DIR = Path("data/specs")


def _cache_path(source_repo: str, rel_path: str, commit_hash: str) -> Path:
    """Build the cache file path for a converted spec document."""
    # Use a hash of the full key to avoid path length issues
    key = f"{source_repo}/{rel_path}@{commit_hash}"
    safe_name = hashlib.md5(key.encode()).hexdigest()
    # Keep human-readable directory structure
    repo_dir = source_repo.replace("/", "_")
    orig_ext = Path(rel_path).suffix
    ext = f"{orig_ext}.md" if orig_ext != ".md" else ".md"
    return CACHE_DIR / repo_dir / f"{Path(rel_path).stem}_{safe_name[:8]}{ext}"


def _read_cache(cache_file: Path) -> str | None:
    """Read from cache if it exists."""
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    return None


def _write_cache(cache_file: Path, content: str) -> None:
    """Write converted content to cache."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(content, encoding="utf-8")
    logger.debug("Cached: %s", cache_file)


def _ensure_papers_downloaded() -> None:
    """Auto-download research papers if data/pdf/ is empty or missing."""
    pdf_dir = Path("data/pdf")
    if pdf_dir.exists() and any(pdf_dir.glob("*.pdf")):
        return

    logger.info("No PDFs found in data/pdf/ — downloading research papers...")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    try:
        import httpx
        from vibe_node.ingest.papers import PAPERS

        for paper in PAPERS:
            dest = pdf_dir / paper.filename
            if dest.exists():
                continue
            logger.info("  Downloading %s", paper.filename)
            resp = httpx.get(paper.url, follow_redirects=True, timeout=60.0)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
    except Exception as e:
        logger.warning("Failed to download papers: %s", e)


class SpecIngestor:
    """Ingests spec documents from configured sources."""

    async def ingest_source(
        self,
        source: SpecSource,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        limit: int | None = None,
        progress=None,
    ) -> int:
        """Ingest all files from a single spec source. Returns chunk count."""
        files = _resolve_files(source.submodule_path, source.spec_glob)
        if not files:
            logger.warning("No files found for %s/%s", source.source_repo, source.spec_glob)
            return 0

        commit_hash, commit_date_str = _get_submodule_head(source.submodule_path)
        from datetime import datetime
        commit_date = datetime.fromisoformat(commit_date_str)

        if limit:
            files = files[:limit]

        task = None
        if progress:
            task = progress.add_task(
                f"[green]{source.source_repo} ({source.format}/{source.era})",
                total=len(files),
            )

        total_chunks = 0
        for file_path in files:
            rel_path = str(file_path.relative_to(source.submodule_path))

            # Check idempotency
            existing = await session.execute(
                text(
                    "SELECT id FROM spec_documents "
                    "WHERE source_repo = :repo AND source_path = :path AND commit_hash = :hash "
                    "LIMIT 1"
                ),
                {"repo": source.source_repo, "path": rel_path, "hash": commit_hash},
            )
            if existing.first():
                if progress and task is not None:
                    progress.update(task, advance=1)
                continue

            # Check conversion cache first
            cache_file = _cache_path(source.source_repo, rel_path, commit_hash)
            cached = _read_cache(cache_file)

            if cached is not None:
                converted = cached
            else:
                # Convert based on format
                if source.format == "pdf":
                    # PDFs are binary — pass file path, not text
                    converted = convert_pdf(file_path)
                    if not converted:
                        if progress and task is not None:
                            progress.update(task, advance=1)
                        continue
                else:
                    # Text-based formats
                    try:
                        raw_content = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception as e:
                        logger.warning("Failed to read %s: %s", file_path, e)
                        if progress and task is not None:
                            progress.update(task, advance=1)
                        continue

                    if source.format == "latex":
                        converted = convert_latex(raw_content, source_dir=file_path.parent)
                    elif source.format in CONVERTERS:
                        converted = CONVERTERS[source.format](raw_content)
                    else:
                        logger.warning("Unknown format: %s", source.format)
                        converted = raw_content

                # Cache the conversion
                _write_cache(cache_file, converted)

            # Chunk
            if source.format == "cddl":
                chunks = chunk_cddl(converted, rel_path)
            else:
                chunks = chunk_markdown(converted, rel_path)

            if not chunks:
                if progress and task is not None:
                    progress.update(task, advance=1)
                continue

            # Determine chunk type override for specific formats
            chunk_type_override = None
            if source.format == "agda":
                chunk_type_override = "agda"
            elif source.format == "cddl":
                chunk_type_override = "schema"

            # Embed and store chunks with prev/next linking
            chunk_ids: list[str] = []
            for chunk in chunks:
                embedding = await embed_client.embed(chunk.embed_text[:8000])

                ct = chunk_type_override or chunk.chunk_type
                chunk_id = str(uuid.uuid4())
                chunk_ids.append(chunk_id)

                await session.execute(
                    text("""
                        INSERT INTO spec_documents (
                            id, document_title, section_title, subsection_title,
                            source_repo, source_path, era,
                            spec_version, commit_hash, commit_date,
                            content_markdown, content_plain, embed_text, embedding,
                            chunk_type, metadata, content_hash
                        ) VALUES (
                            :id, :doc_title, :sec_title, :subsec_title,
                            :repo, :path, :era,
                            :version, :commit_hash, :commit_date,
                            :md, :plain, :embed_text, :embedding,
                            :chunk_type, NULL, :content_hash
                        )
                    """),
                    {
                        "id": chunk_id,
                        "doc_title": chunk.document_title,
                        "sec_title": chunk.section_title,
                        "subsec_title": chunk.subsection_title,
                        "repo": source.source_repo,
                        "path": rel_path,
                        "era": source.era,
                        "version": "HEAD",
                        "commit_hash": commit_hash,
                        "commit_date": commit_date,
                        "md": chunk.content_markdown,
                        "plain": chunk.content_plain,
                        "embed_text": chunk.embed_text,
                        "embedding": str(embedding),
                        "chunk_type": ct,
                        "content_hash": chunk.content_hash,
                    },
                )
                total_chunks += 1

            # Link prev/next chunks within this file
            for i in range(len(chunk_ids)):
                updates = {}
                if i > 0:
                    updates["prev"] = chunk_ids[i - 1]
                if i < len(chunk_ids) - 1:
                    updates["next"] = chunk_ids[i + 1]
                if updates:
                    set_clauses = []
                    if "prev" in updates:
                        set_clauses.append("prev_chunk_id = :prev")
                    if "next" in updates:
                        set_clauses.append("next_chunk_id = :next")
                    await session.execute(
                        text(f"UPDATE spec_documents SET {', '.join(set_clauses)} WHERE id = :id"),
                        {"id": chunk_ids[i], **updates},
                    )

            await session.commit()
            if progress and task is not None:
                progress.update(task, advance=1)

        if progress and task is not None:
            progress.update(task, completed=len(files))
        logger.info(
            "Completed %s (%s): %d chunks from %d files",
            source.source_repo, source.format, total_chunks, len(files),
        )
        return total_chunks

    async def ingest_all(
        self,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        format_filter: str | None = None,
        source_filter: str | None = None,
        limit: int | None = None,
        progress=None,
    ) -> dict[str, int]:
        """Ingest all configured spec sources.

        Args:
            format_filter: Only ingest sources of this format (markdown, cddl, latex, agda)
            source_filter: Only ingest sources matching this substring in source_repo
            limit: Max files per source (for testing)
            progress: Rich Progress instance
        """
        # Auto-download research papers if needed
        _ensure_papers_downloaded()

        sources = SPEC_SOURCES

        if format_filter:
            sources = [s for s in sources if s.format == format_filter]
        if source_filter:
            sf = source_filter.lower()
            sources = [
                s for s in sources
                if sf in s.source_repo.lower() or sf in s.era.lower() or sf in s.spec_glob.lower()
            ]

        results: dict[str, int] = {}
        for source in sources:
            key = f"{source.source_repo} ({source.format}/{source.era})"
            results[key] = await self.ingest_source(
                source, session, embed_client,
                limit=limit, progress=progress,
            )

        return results

    async def ingest_history(
        self,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        format_filter: str | None = None,
        source_filter: str | None = None,
        limit: int | None = None,
        progress=None,
    ) -> dict[str, int]:
        """Ingest historical versions of specs by walking git commit history.

        For each spec source, discovers commits that modified spec files
        and ingests the spec at each commit using git show (no checkout).

        Args:
            limit: Max commits per source to process
        """
        sources = SPEC_SOURCES

        if format_filter:
            sources = [s for s in sources if s.format == format_filter]
        if source_filter:
            sf = source_filter.lower()
            sources = [
                s for s in sources
                if sf in s.source_repo.lower() or sf in s.era.lower() or sf in s.spec_glob.lower()
            ]

        # Skip PDF sources (no git history) and sources without submodules
        sources = [s for s in sources if s.format != "pdf"]

        results: dict[str, int] = {}
        for source in sources:
            key = f"{source.source_repo} ({source.format}/{source.era})"
            commits = discover_spec_commits(
                source.submodule_path,
                source.spec_glob,
                limit=limit,
            )

            if not commits:
                results[key] = 0
                continue

            task = None
            if progress:
                task = progress.add_task(
                    f"[yellow]{source.source_repo} history ({source.era})",
                    total=len(commits),
                )

            total_chunks = 0
            for commit in commits:
                for file_path in commit.files_changed:
                    # Check idempotency
                    existing = await session.execute(
                        text(
                            "SELECT id FROM spec_documents "
                            "WHERE source_repo = :repo AND source_path = :path "
                            "AND commit_hash = :hash LIMIT 1"
                        ),
                        {
                            "repo": source.source_repo,
                            "path": file_path,
                            "hash": commit.commit_hash,
                        },
                    )
                    if existing.first():
                        continue

                    # Get file content at this commit (no checkout needed)
                    content = get_file_at_commit(
                        source.submodule_path,
                        commit.commit_hash,
                        file_path,
                    )
                    if not content:
                        continue

                    # Convert
                    if source.format == "latex":
                        from vibe_node.ingest.specs.converters.latex import convert_latex
                        converted = convert_latex(content)
                    elif source.format in CONVERTERS:
                        converted = CONVERTERS[source.format](content)
                    else:
                        converted = content

                    # Chunk
                    if source.format == "cddl":
                        chunks = chunk_cddl(converted, file_path, source.source_repo)
                    else:
                        chunks = chunk_markdown(converted, file_path, source.source_repo)

                    if not chunks:
                        continue

                    chunk_type_override = None
                    if source.format == "agda":
                        chunk_type_override = "agda"

                    for chunk in chunks:
                        embedding = await embed_client.embed(chunk.embed_text[:8000])
                        ct = chunk_type_override or chunk.chunk_type

                        await session.execute(
                            text("""
                                INSERT INTO spec_documents (
                                    id, document_title, section_title, subsection_title,
                                    source_repo, source_path, era,
                                    spec_version, commit_hash, commit_date,
                                    content_markdown, content_plain, embed_text, embedding,
                                    chunk_type, metadata, content_hash
                                ) VALUES (
                                    :id, :doc_title, :sec_title, :subsec_title,
                                    :repo, :path, :era,
                                    :version, :commit_hash, :commit_date,
                                    :md, :plain, :embed_text, :embedding,
                                    :chunk_type, NULL, :content_hash
                                )
                            """),
                            {
                                "id": str(uuid.uuid4()),
                                "doc_title": chunk.document_title,
                                "sec_title": chunk.section_title,
                                "subsec_title": chunk.subsection_title,
                                "repo": source.source_repo,
                                "path": file_path,
                                "era": source.era,
                                "version": commit.commit_hash[:12],
                                "commit_hash": commit.commit_hash,
                                "commit_date": commit.commit_date,
                                "md": chunk.content_markdown,
                                "plain": chunk.content_plain,
                                "embed_text": chunk.embed_text,
                                "embedding": str(embedding),
                                "chunk_type": ct,
                                "content_hash": chunk.content_hash,
                            },
                        )
                        total_chunks += 1

                await session.commit()
                if progress and task is not None:
                    progress.update(task, advance=1)

            if progress and task is not None:
                progress.update(task, completed=len(commits))

            results[key] = total_chunks
            logger.info(
                "History %s: %d chunks from %d commits",
                key, total_chunks, len(commits),
            )

        return results
