"""LaTeX converter — uses pandoc for LaTeX → markdown conversion.

Post-processes pandoc output to clean up math formatting:
- Strips HTML span wrappers around math blocks
- Simplifies unsupported LaTeX array column specs for KaTeX compatibility
- Normalizes math delimiters to clean $...$ and $$...$$ format
"""

import logging
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def pandoc_available() -> bool:
    """Check if pandoc is installed."""
    return shutil.which("pandoc") is not None


def _clean_math(text: str) -> str:
    """Post-process pandoc math output for KaTeX compatibility."""
    # Remove <span class="math display/inline">...</span> wrappers
    # but keep the content (including $$...$$ delimiters)
    text = re.sub(r'<span class="math display">\s*', "", text)
    text = re.sub(r'<span class="math inline">\s*', "", text)
    text = re.sub(r"</span>", "", text)

    # Remove <p> tags around math
    text = re.sub(r"<p>\s*(\$\$)", r"\1", text)
    text = re.sub(r"(\$\$)\s*</p>", r"\1", text)

    # Unescape HTML entities inside math blocks
    def unescape_math(match):
        content = match.group(0)
        content = content.replace("&amp;", "&")
        content = content.replace("&lt;", "<")
        content = content.replace("&gt;", ">")
        content = content.replace("&#39;", "'")
        return content

    text = re.sub(r"\$\$[\s\S]*?\$\$", unescape_math, text)
    text = re.sub(r"\$[^$]+\$", unescape_math, text)

    # Simplify array column specs that KaTeX doesn't support
    # @{~\in~} → nothing (KaTeX uses basic column specs)
    text = re.sub(r"@\{[^}]*\}", "", text)

    # Remove \ensuremath{} wrappers
    text = re.sub(r"\\ensuremath\{([^}]*)\}", r"\1", text)

    # Clean up multiple blank lines inside math blocks
    def collapse_math_blanks(match):
        content = match.group(0)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content

    text = re.sub(r"\$\$[\s\S]*?\$\$", collapse_math_blanks, text)

    return text


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
        "--to=markdown-raw_html+tex_math_dollars",
        "--wrap=none",
        "--katex",
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

    output = result.stdout

    # Post-process for KaTeX compatibility
    output = _clean_math(output)

    return output
