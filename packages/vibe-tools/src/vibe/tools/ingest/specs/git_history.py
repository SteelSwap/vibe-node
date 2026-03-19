"""Git history walker for spec version tracking.

Discovers commits that modified spec files and yields them in
chronological order. This gives us a full historical record of
how each spec evolved — not just the current state.
"""

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SpecCommit:
    """A commit that modified spec files."""
    commit_hash: str
    commit_date: datetime
    files_changed: list[str]
    message: str


def discover_spec_commits(
    submodule_path: str,
    spec_glob: str,
    limit: int | None = None,
) -> list[SpecCommit]:
    """Find all commits that modified files matching the spec glob.

    Args:
        submodule_path: Path to the git submodule
        spec_glob: Glob pattern for spec files (e.g. "shelley/chain-and-ledger/formal-spec/*.tex")
        limit: Max commits to return (most recent first, then reversed to chronological)

    Returns:
        List of SpecCommit in chronological order (oldest first).
    """
    path = Path(submodule_path)
    if not path.exists():
        logger.warning("Submodule path does not exist: %s", submodule_path)
        return []

    # Convert glob to a directory path for git log.
    # Take the first concrete directory before any glob wildcards.
    parts = spec_glob.split("/")
    concrete_parts = []
    for part in parts:
        if "*" in part or "?" in part:
            break
        concrete_parts.append(part)
    spec_dir = "/".join(concrete_parts) if concrete_parts else "."

    # Get commits that touched files in the spec directory
    cmd = [
        "git", "log",
        "--format=%H|%aI|%s",
        "--diff-filter=AMRC",  # Added, Modified, Renamed, Copied
        "--", spec_dir,
    ]

    result = subprocess.run(
        cmd,
        cwd=submodule_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.warning(
            "git log failed for %s/%s: %s",
            submodule_path, spec_dir, result.stderr[:200],
        )
        return []

    commits: list[SpecCommit] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue

        commit_hash, date_str, message = parts
        try:
            commit_date = datetime.fromisoformat(date_str)
        except ValueError:
            continue

        # Get the specific files changed in this commit
        files_result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash, "--", spec_dir],
            cwd=submodule_path,
            capture_output=True,
            text=True,
        )
        files_changed = [
            f.strip() for f in files_result.stdout.strip().split("\n")
            if f.strip()
        ]

        commits.append(SpecCommit(
            commit_hash=commit_hash,
            commit_date=commit_date,
            files_changed=files_changed,
            message=message,
        ))

    # Reverse to chronological order (oldest first)
    commits.reverse()

    if limit:
        # Take the most recent N commits
        commits = commits[-limit:]

    logger.info(
        "Found %d commits touching %s in %s",
        len(commits), spec_dir, submodule_path,
    )

    return commits


def get_file_at_commit(
    submodule_path: str,
    commit_hash: str,
    file_path: str,
) -> str | None:
    """Get the content of a file at a specific commit without checking out.

    Uses git show to read the file directly — avoids checkout thrashing.
    """
    result = subprocess.run(
        ["git", "show", f"{commit_hash}:{file_path}"],
        cwd=submodule_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.debug(
            "File %s not found at commit %s: %s",
            file_path, commit_hash[:8], result.stderr[:100],
        )
        return None

    return result.stdout
