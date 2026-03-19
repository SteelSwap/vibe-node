"""Tests for the tree-sitter Haskell parser.

Run with: uv run pytest tests/test_haskell_parser.py -v

These tests verify that the parser correctly identifies top-level
declarations, groups multi-equation functions, associates type
signatures, and extracts module names from real Haskell source.
"""

from pathlib import Path

import pytest

from vibe.tools.ingest.haskell_parser import CodeChunkData, HaskellParser

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "vendor"


@pytest.fixture(scope="module")
def parser() -> HaskellParser:
    return HaskellParser()


# ---------------------------------------------------------------------------
# Synthetic source tests
# ---------------------------------------------------------------------------

SAMPLE_HASKELL = b"""\
module Test.Sample (foo, bar) where

import Data.Maybe

-- | A type signature followed by a multi-equation function
foo :: Int -> Int -> Int
foo 0 y = y
foo x y = x + y

-- | A simple data type
data Color
  = Red
  | Green
  | Blue
  deriving (Show, Eq)

-- | A type class
class Printable a where
  prettyPrint :: a -> String

-- | An instance
instance Printable Color where
  prettyPrint Red   = "red"
  prettyPrint Green = "green"
  prettyPrint Blue  = "blue"

-- | A newtype
newtype Wrapper a = MkWrapper { unwrap :: a }

-- | A type alias (uses type_synomym in tree-sitter)
type Name = String

bar :: String -> String
bar s = "hello " ++ s
"""


def test_parse_synthetic(parser: HaskellParser) -> None:
    """Parser extracts expected chunks from synthetic Haskell source."""
    chunks = parser.parse_file(SAMPLE_HASKELL, "Test/Sample.hs")

    names = [c.function_name for c in chunks]

    # Should have the multi-equation function 'foo'
    assert "foo" in names, f"Expected 'foo' in {names}"

    # Should have the data type
    assert "Color" in names, f"Expected 'Color' in {names}"

    # Should have bar
    assert "bar" in names, f"Expected 'bar' in {names}"


def test_module_name_extracted(parser: HaskellParser) -> None:
    """Parser extracts the module name from the header."""
    chunks = parser.parse_file(SAMPLE_HASKELL, "Test/Sample.hs")
    assert len(chunks) > 0
    # Module name should contain "Test.Sample" or "Test" at minimum
    assert "Test" in chunks[0].module_name


def test_signature_attached(parser: HaskellParser) -> None:
    """Type signatures are attached to their function chunks."""
    chunks = parser.parse_file(SAMPLE_HASKELL, "Test/Sample.hs")
    foo_chunks = [c for c in chunks if c.function_name == "foo"]
    assert len(foo_chunks) == 1
    assert foo_chunks[0].signature is not None
    assert "Int -> Int -> Int" in foo_chunks[0].signature


def test_multi_equation_grouped(parser: HaskellParser) -> None:
    """Consecutive function equations with the same name are grouped."""
    chunks = parser.parse_file(SAMPLE_HASKELL, "Test/Sample.hs")
    foo_chunks = [c for c in chunks if c.function_name == "foo"]
    assert len(foo_chunks) == 1
    # Content should contain both equations
    assert "foo 0 y = y" in foo_chunks[0].content
    assert "foo x y = x + y" in foo_chunks[0].content


def test_small_chunks_skipped(parser: HaskellParser) -> None:
    """Chunks smaller than 2 lines are skipped (unless they have a sig)."""
    source = b"""\
module Tiny where

x = 1
"""
    chunks = parser.parse_file(source, "Tiny.hs")
    # x = 1 is a single line with no signature, so should be skipped
    one_liners = [c for c in chunks if c.function_name == "x"]
    assert len(one_liners) == 0


# ---------------------------------------------------------------------------
# AST node type discovery test
# ---------------------------------------------------------------------------

def test_discover_real_node_types(parser: HaskellParser) -> None:
    """Print AST node types from a real vendor .hs file.

    This test is primarily for development — it prints the node types
    so we can verify the grammar produces what we expect. It passes
    as long as tree-sitter can parse the file without crashing.
    """
    hs_file = (
        VENDOR_ROOT
        / "ouroboros-consensus"
        / "sop-extras"
        / "src"
        / "Data"
        / "SOP"
        / "Match.hs"
    )
    if not hs_file.exists():
        pytest.skip("vendor/ouroboros-consensus not checked out")

    source = hs_file.read_bytes()
    chunks = parser.parse_file(source, str(hs_file))
    assert len(chunks) > 0, "Expected at least one chunk from Match.hs"

    # Print for manual inspection
    print(f"\n--- Chunks from {hs_file.name} ({len(chunks)} total) ---")
    for c in chunks[:10]:
        print(
            f"  {c.function_name:30s}  L{c.line_start}-{c.line_end}  "
            f"sig={'yes' if c.signature else 'no'}"
        )
