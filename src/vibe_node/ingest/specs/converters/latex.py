"""LaTeX converter — uses pandoc for LaTeX → markdown conversion."""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def pandoc_available() -> bool:
    """Check if pandoc is installed."""
    return shutil.which("pandoc") is not None


def convert_latex(content: str, source_dir: Path | None = None) -> str:
    """Convert LaTeX to markdown via pandoc.

    Args:
        content: LaTeX source text
        source_dir: directory for resolving \\input{} paths
    """
    if not pandoc_available():
        logger.warning("pandoc not installed — returning raw LaTeX")
        return content

    cmd = [
        "pandoc",
        "--from=latex",
        "--to=markdown",
        "--wrap=none",
    ]
    if source_dir:
        cmd.extend(["--resource-path", str(source_dir)])

    result = subprocess.run(
        cmd,
        input=content,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        logger.warning("pandoc failed: %s", result.stderr[:500])
        return content

    return result.stdout
