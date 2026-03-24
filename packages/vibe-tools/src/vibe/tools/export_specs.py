"""Export pre-converted spec markdown from data/specs/ to docs/specs/ organized by era.

Uses the database to determine the era for each file, then copies and organizes
the pre-converted markdown files into browsable docs/specs/{era}/ directories
with index pages for each era.
"""

import hashlib
import shutil
from collections import defaultdict
from pathlib import Path

# Map multi-era source repos to their output directory names
REPO_DIR_MAP = {
    "ouroboros-consensus": "consensus",
    "ouroboros-network": "networking",
    "ouroboros-papers": "papers",
}

# Human-readable labels for era directories
ERA_LABELS = {
    "byron": "Byron",
    "shelley": "Shelley",
    "shelley-ma": "Mary / Allegra",
    "alonzo": "Alonzo",
    "conway": "Conway",
    "plutus": "Plutus",
    "consensus": "Consensus",
    "networking": "Networking",
    "papers": "Papers",
}


def _cache_path(source_repo: str, rel_path: str, commit_hash: str) -> str:
    """Reproduce the cache filename used by the ingestion pipeline.

    Must match packages/vibe-tools/src/vibe/tools/ingest/specs/pipeline.py::_cache_path exactly.
    """
    key = f"{source_repo}/{rel_path}@{commit_hash}"
    safe_name = hashlib.md5(key.encode()).hexdigest()
    repo_dir = source_repo.replace("/", "_")
    orig_ext = Path(rel_path).suffix
    ext = f"{orig_ext}.md" if orig_ext != ".md" else ".md"
    return f"{repo_dir}/{Path(rel_path).stem}_{safe_name[:8]}{ext}"


def _resolve_output_dir(era: str, source_repo: str) -> str:
    """Determine which docs/specs/ subdirectory a document belongs in."""
    if era == "multi-era":
        for repo_key, dir_name in REPO_DIR_MAP.items():
            if repo_key in source_repo:
                return dir_name
        return "multi-era"
    return era


def _clean_filename(basename: str, seen: dict[str, int]) -> str:
    """Generate a clean filename, appending -N for duplicates within an era."""
    if basename in seen:
        seen[basename] += 1
        return f"{basename}-{seen[basename]}.md"
    else:
        seen[basename] = 1
        return f"{basename}.md"


def export_specs(
    dsn: str = "postgresql://vibenode:vibenode@localhost:5432/vibenode",
    data_dir: str | None = None,
    docs_dir: str | None = None,
) -> dict[str, int]:
    """Export all spec documents to docs/specs/ markdown files.

    Queries the database for era metadata, then copies pre-converted markdown
    from data/specs/ to docs/specs/{era}/ with clean filenames and index pages.

    Returns a dict mapping era directory names to document counts.
    """
    import subprocess

    project_root = Path(__file__).resolve().parents[5]
    if data_dir is None:
        data_dir = str(project_root / "data" / "specs")
    if docs_dir is None:
        docs_dir = str(project_root / "docs" / "specs")

    data_base = Path(data_dir)
    docs_base = Path(docs_dir)

    # Query the database for (era, source_repo, source_path, document_title, commit_hash)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "paradedb",
            "psql",
            "-U",
            "vibenode",
            "-d",
            "vibenode",
            "-t",
            "-A",
            "-F",
            "\t",
            "-c",
            "SELECT DISTINCT era, source_repo, source_path, document_title, commit_hash "
            "FROM spec_documents ORDER BY era, source_repo, source_path",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Error querying database: {result.stderr}")
        return {}

    # Parse the DB rows and build a mapping from cache filename -> metadata
    cache_to_meta: dict[str, dict] = {}
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        era, source_repo, source_path, document_title, commit_hash = parts[:5]
        cache_rel = _cache_path(source_repo, source_path, commit_hash)
        if cache_rel not in cache_to_meta:
            cache_to_meta[cache_rel] = {
                "era": era,
                "source_repo": source_repo,
                "source_path": source_path,
                "document_title": document_title,
                "commit_hash": commit_hash,
            }

    if not cache_to_meta:
        print("No spec documents found in database.")
        return {}

    print(f"Found {len(cache_to_meta)} documents in database.")

    # Walk data/specs/ and match each file to its DB metadata
    # Group by (output_dir, basename) for copying
    # Structure: {era_dir: [(source_file, clean_name, title, meta), ...]}
    era_docs: dict[str, list[tuple[Path, str, str, dict]]] = defaultdict(list)
    unmatched = []

    for repo_dir in sorted(data_base.iterdir()):
        if not repo_dir.is_dir():
            continue
        for md_file in sorted(repo_dir.iterdir()):
            if not md_file.name.endswith(".md"):
                continue
            cache_rel = f"{repo_dir.name}/{md_file.name}"
            meta = cache_to_meta.get(cache_rel)
            if meta is None:
                unmatched.append(cache_rel)
                continue

            out_dir = _resolve_output_dir(meta["era"], meta["source_repo"])
            basename = md_file.name
            # Remove hash suffix: "address_5983d88a.tex.md" -> "address"
            # Format: {stem}_{hash8}.{orig_ext}.md
            name_no_md = basename.removesuffix(".md")  # "address_5983d88a.tex"
            # Find the last underscore before the hash
            parts = name_no_md.rsplit("_", 1)
            if len(parts) == 2:
                clean_base = parts[0]  # "address"
            else:
                clean_base = name_no_md

            era_docs[out_dir].append((md_file, clean_base, meta["document_title"], meta))

    if unmatched:
        print(f"  Warning: {len(unmatched)} files not matched to database records")

    # Clean out existing era directories (remove stale files from previous exports)
    # but preserve gap-analysis.md and the top-level index.md
    era_dirs_to_clean = set(era_docs.keys())
    for era_dir in era_dirs_to_clean:
        era_path = docs_base / era_dir
        if era_path.exists():
            shutil.rmtree(era_path)

    # Copy files and build indexes
    stats: dict[str, int] = {}

    for era_dir, docs in sorted(era_docs.items()):
        era_path = docs_base / era_dir
        era_path.mkdir(parents=True, exist_ok=True)

        # Track used basenames for deduplication within this era
        seen: dict[str, int] = {}
        doc_entries: list[tuple[str, str]] = []  # (title, filename)

        for source_file, clean_base, title, meta in docs:
            filename = _clean_filename(clean_base, seen)
            dest = era_path / filename

            # Copy the pre-converted markdown
            shutil.copy2(source_file, dest)
            doc_entries.append((title, filename))

        # Write era index page
        label = ERA_LABELS.get(era_dir, era_dir.title())
        index_lines = [
            f"# {label} Specifications",
            "",
            f"**{len(doc_entries)} documents**",
            "",
        ]
        for title, fname in sorted(doc_entries, key=lambda x: x[0]):
            index_lines.append(f"- [{title}]({fname})")

        (era_path / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

        stats[era_dir] = len(doc_entries)
        print(f"  {era_dir}: {len(doc_entries)} documents")

    total = sum(stats.values())
    print(f"\nExport complete: {total} documents across {len(stats)} categories.")
    return stats


def main() -> None:
    """CLI entry point for standalone execution."""
    import os

    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://vibenode:vibenode@localhost:5432/vibenode",
    )
    print("Exporting spec documents to docs/specs/...")
    export_specs(dsn)


if __name__ == "__main__":
    main()
