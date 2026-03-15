"""Tree-sitter based Haskell parser for function-level code chunking.

Parses ``.hs`` files into structured chunks suitable for embedding and
storage in the ``code_chunks`` table. Each chunk represents a single
top-level declaration (function, data type, class, instance, etc.)
together with its preceding type signature when present.
"""

from __future__ import annotations

from dataclasses import dataclass

import tree_sitter_haskell as tshaskell
from tree_sitter import Language, Parser


@dataclass
class CodeChunkData:
    """A single parsed code chunk extracted from a Haskell source file."""

    file_path: str
    module_name: str
    function_name: str
    line_start: int
    line_end: int
    content: str
    signature: str | None


# Node types that represent top-level declarations we want to index.
# Discovered from the tree-sitter-haskell grammar's node-types.json.
_DECLARATION_TYPES = frozenset({
    "function",
    "bind",
    "data_type",
    "newtype",
    "type_synomym",      # sic — typo in the tree-sitter-haskell grammar
    "type_family",
    "data_family",
    "class",
    "instance",
    "deriving_instance",
    "foreign_import",
    "foreign_export",
    "pattern_synonym",
    "kind_signature",
})


def _node_name(node, source: bytes) -> str:
    """Extract the declared name from a tree-sitter node.

    Looks for the ``name`` field first, then falls back to reading the
    first named child that looks like an identifier.
    """
    # Most declaration nodes have an explicit "name" field
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return source[name_node.start_byte:name_node.end_byte].decode(
            "utf-8", errors="replace"
        )

    # Fallback: grab the first named child that is a variable/constructor
    for child in node.named_children:
        if child.type in ("variable", "prefix_id", "name", "constructor"):
            return source[child.start_byte:child.end_byte].decode(
                "utf-8", errors="replace"
            )

    # Last resort: first token-ish content
    text = source[node.start_byte:min(node.start_byte + 60, node.end_byte)]
    first_line = text.decode("utf-8", errors="replace").split("\n", 1)[0]
    # Try to grab the first word after any keyword
    parts = first_line.split()
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else "<unknown>"


def _extract_module_name(root_node, source: bytes) -> str:
    """Extract the module name from the AST root.

    The tree-sitter-haskell grammar places the module declaration in a
    ``header`` node (or occasionally ``module``).
    """
    for child in root_node.children:
        if child.type in ("header", "module"):
            # The module name lives in a "module" field or as a child
            mod_node = child.child_by_field_name("module")
            if mod_node is not None:
                return source[mod_node.start_byte:mod_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
            # Fallback: look for a qualified name child
            for sub in child.named_children:
                if sub.type in ("module", "qualified", "name"):
                    return source[sub.start_byte:sub.end_byte].decode(
                        "utf-8", errors="replace"
                    )
    return "<unknown>"


class HaskellParser:
    """Parse Haskell source files into function-level code chunks."""

    def __init__(self) -> None:
        self._language = Language(tshaskell.language())
        self._parser = Parser(self._language)

    def parse_file(self, source: bytes, file_path: str) -> list[CodeChunkData]:
        """Parse a Haskell source file and return a list of code chunks.

        Each top-level declaration becomes one chunk. Type signatures are
        associated with the immediately following function definition
        rather than stored as separate chunks.
        """
        tree = self._parser.parse(source)
        root = tree.root_node
        module_name = _extract_module_name(root, source)

        chunks: list[CodeChunkData] = []

        # Declarations may be direct children of root or inside a
        # 'declarations' wrapper node — handle both layouts.
        children: list = []
        for child in root.children:
            if child.type == "declarations":
                children.extend(child.children)
            else:
                children.append(child)

        # First pass: collect signatures keyed by name so we can attach
        # them to the corresponding function definition.
        signatures: dict[str, str] = {}
        for node in children:
            if node.type == "signature":
                sig_name = _node_name(node, source)
                sig_text = source[node.start_byte:node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                signatures[sig_name] = sig_text

        # Second pass: collect declarations and group multi-equation
        # functions (consecutive ``function`` nodes with the same name).
        i = 0
        while i < len(children):
            node = children[i]

            # Skip non-declaration nodes (comments, pragmas, imports, etc.)
            if node.type not in _DECLARATION_TYPES:
                i += 1
                continue

            # Skip standalone signatures — they'll be attached to funcs
            if node.type == "signature":
                i += 1
                continue

            name = _node_name(node, source)

            # Group consecutive function/bind equations with the same name
            if node.type in ("function", "bind"):
                start_node = node
                end_node = node
                j = i + 1
                while j < len(children):
                    next_node = children[j]
                    if next_node.type == node.type:
                        next_name = _node_name(next_node, source)
                        if next_name == name:
                            end_node = next_node
                            j += 1
                            continue
                    break

                line_start = start_node.start_point[0] + 1
                line_end = end_node.end_point[0] + 1
                content = source[
                    start_node.start_byte:end_node.end_byte
                ].decode("utf-8", errors="replace")
                sig = signatures.get(name)

                # Skip trivially small chunks (< 2 lines)
                if line_end - line_start + 1 >= 2 or sig is not None:
                    chunks.append(CodeChunkData(
                        file_path=file_path,
                        module_name=module_name,
                        function_name=name,
                        line_start=line_start,
                        line_end=line_end,
                        content=content,
                        signature=sig,
                    ))

                i = j
                continue

            # Non-function declaration (data, class, instance, etc.)
            line_start = node.start_point[0] + 1
            line_end = node.end_point[0] + 1
            content = source[node.start_byte:node.end_byte].decode(
                "utf-8", errors="replace"
            )

            if line_end - line_start + 1 >= 2:
                chunks.append(CodeChunkData(
                    file_path=file_path,
                    module_name=module_name,
                    function_name=name,
                    line_start=line_start,
                    line_end=line_end,
                    content=content,
                    signature=signatures.get(name),
                ))

            i += 1

        return chunks
