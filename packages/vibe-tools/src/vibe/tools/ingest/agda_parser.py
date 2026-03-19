"""Text-based Agda parser for function-level code chunking.

Extracts top-level definitions from .agda and .lagda files.
Uses regex/line-based parsing since there's no tree-sitter-agda
for Python.
"""

import re
from dataclasses import dataclass


@dataclass
class AgdaChunkData:
    """A single parsed code chunk from an Agda source file."""
    file_path: str
    module_name: str
    function_name: str
    line_start: int
    line_end: int
    content: str
    signature: str | None


def _extract_module_name(lines: list[str], file_path: str) -> str:
    """Extract module name from 'module ... where' line."""
    for line in lines:
        match = re.match(r'^module\s+([\w.]+)\s+where', line)
        if match:
            return match.group(1)
    # Fallback: derive from file path
    name = file_path.replace("/", ".").replace("\\", ".")
    for suffix in (".agda", ".lagda", ".lagda.md"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
    # Strip common prefixes
    for prefix in ("src.", "lib."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


def _is_top_level_def(line: str) -> bool:
    """Check if a line starts a top-level definition (column 0, not a comment)."""
    if not line or line[0].isspace():
        return False
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("--") or stripped.startswith("{-"):
        return False
    if stripped.startswith("module ") or stripped.startswith("open ") or stripped.startswith("import "):
        return False
    if stripped in ("private", "abstract", "instance", "where"):
        return False
    # Must contain an identifier-like start
    if not (stripped[0].isalpha() or stripped[0] == '_' or stripped[0] == '∀'):
        return False
    return True


def _extract_def_name(line: str) -> str:
    """Extract the definition name from a top-level line."""
    # data Name ...
    match = re.match(r'^(data|record)\s+(\S+)', line)
    if match:
        return match.group(2)
    # name : Type  (signature)
    match = re.match(r'^(\S+)\s*:', line)
    if match:
        return match.group(1)
    # name args = ...  (definition)
    match = re.match(r'^(\S+)\s', line)
    if match:
        return match.group(1)
    return line.split()[0] if line.split() else "<unknown>"


def _extract_def_kind(line: str) -> str:
    """Determine if the line is a signature, data, record, or function."""
    if re.match(r'^data\s', line):
        return "data"
    if re.match(r'^record\s', line):
        return "record"
    # Signature: "name : Type" where there's no = before the :
    if re.match(r'^[\w_∀]+\s*:', line):
        before_colon = line.split(":")[0].strip()
        if "=" not in before_colon:
            return "signature"
    return "function"


def _extract_code_from_lagda(content: str) -> tuple[list[str], dict[int, int]]:
    """Extract code lines from literate Agda, mapping output lines to original lines.

    Returns (code_lines, line_map) where line_map[output_idx] = original_line_number.
    Strips common leading indentation from each code block.
    """
    lines = content.split("\n")
    code_lines: list[str] = []
    line_map: dict[int, int] = {}
    in_code = False
    hidden = False
    block_lines: list[tuple[str, int]] = []  # (line, original_line_number)

    def flush_block():
        """Dedent a code block and add to output."""
        if not block_lines:
            return
        # Find minimum indentation (ignoring blank lines)
        min_indent = float("inf")
        for bl, _ in block_lines:
            stripped = bl.lstrip()
            if stripped:
                indent = len(bl) - len(stripped)
                min_indent = min(min_indent, indent)
        if min_indent == float("inf"):
            min_indent = 0
        for bl, orig_ln in block_lines:
            dedented = bl[int(min_indent):] if len(bl) >= min_indent else bl
            line_map[len(code_lines)] = orig_ln
            code_lines.append(dedented)
        block_lines.clear()

    for i, line in enumerate(lines):
        if re.match(r'\\begin\{code\}\[hide\]', line):
            flush_block()
            in_code = True
            hidden = True
            continue
        elif re.match(r'\\begin\{code\}', line):
            flush_block()
            in_code = True
            hidden = False
            continue
        elif re.match(r'\\end\{code\}', line):
            if not hidden:
                flush_block()
            else:
                block_lines.clear()
            in_code = False
            hidden = False
            continue

        if in_code and not hidden:
            block_lines.append((line, i + 1))

    flush_block()
    return code_lines, line_map


class AgdaParser:
    """Parse Agda source files into function-level code chunks."""

    def parse_file(self, source: bytes | str, file_path: str) -> list[AgdaChunkData]:
        """Parse an Agda file and return code chunks.

        Handles both .agda (pure Agda) and .lagda (literate Agda) files.
        """
        if isinstance(source, bytes):
            content = source.decode("utf-8", errors="replace")
        else:
            content = source

        is_literate = file_path.endswith(".lagda") or file_path.endswith(".lagda.md")

        if is_literate:
            code_lines, line_map = _extract_code_from_lagda(content)
        else:
            code_lines = content.split("\n")
            line_map = {i: i + 1 for i in range(len(code_lines))}

        module_name = _extract_module_name(code_lines, file_path)

        # Find top-level definitions
        chunks: list[AgdaChunkData] = []
        signatures: dict[str, tuple[str, int]] = {}  # name -> (text, original_line)

        i = 0
        while i < len(code_lines):
            line = code_lines[i]

            if not _is_top_level_def(line):
                i += 1
                continue

            name = _extract_def_name(line)
            kind = _extract_def_kind(line)

            # Find the extent of this definition (until next top-level def or blank line after content)
            start_idx = i
            i += 1
            while i < len(code_lines):
                next_line = code_lines[i]
                # Next top-level definition
                if _is_top_level_def(next_line):
                    break
                i += 1

            end_idx = i - 1
            # Trim trailing blank lines
            while end_idx > start_idx and not code_lines[end_idx].strip():
                end_idx -= 1

            content_text = "\n".join(code_lines[start_idx:end_idx + 1])
            orig_start = line_map.get(start_idx, start_idx + 1)
            orig_end = line_map.get(end_idx, end_idx + 1)

            if kind == "signature":
                signatures[name] = (content_text, orig_start)
                continue

            # Skip trivially small chunks
            if end_idx - start_idx < 1:
                continue

            sig_text = None
            if name in signatures:
                sig_text = signatures[name][0]

            chunks.append(AgdaChunkData(
                file_path=file_path,
                module_name=module_name,
                function_name=name,
                line_start=orig_start,
                line_end=orig_end,
                content=content_text,
                signature=sig_text,
            ))

        return chunks
