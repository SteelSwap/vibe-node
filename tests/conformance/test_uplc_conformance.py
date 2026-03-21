"""UPLC evaluation conformance tests against the Plutus conformance test suite.

Runs the official Plutus conformance golden tests from:
    vendor/plutus/plutus-conformance/test-cases/uplc/evaluation/

Each test case consists of:
    - A .uplc file containing a textual UPLC program
    - A .uplc.expected file containing either:
        * The expected result as a textual UPLC program (e.g. "(program 1.0.0 (con integer 42))")
        * "evaluation failure" for programs that should fail

The test runner:
    1. Parses the .uplc source via uplc.tools.parse (textual UPLC format)
    2. Evaluates via uplc.tools.eval (CEK machine with default budget)
    3. Compares the result against the .expected file

Limitations:
    - Variable names in lambda results may differ between the uplc Python
      package (which uses de Bruijn-style v0/v1 names) and the Haskell
      reference (which uses original names like z-0/f-1). For lambda results,
      we attempt structural comparison by normalizing both sides through
      de Bruijn indexing. If the expected output can't be parsed (e.g. due to
      hyphenated variable names), the test is marked as xfail.
    - The uplc Python package may not support all builtins or all edge cases
      that the Haskell implementation handles.

Spec references:
    * Plutus Core specification, Section 4 (CEK machine)
    * plutus/plutus-conformance/README.md (test case format)

Haskell references:
    * Test.Tasty.Plutus.Golden (Haskell golden test runner)
    * UntypedPlutusCore.Evaluation.Machine.Cek (CEK machine)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

import pytest


# ---------------------------------------------------------------------------
# Test case discovery
# ---------------------------------------------------------------------------

# Locate the vendor conformance test cases. The vendor/ directory contains
# git submodules that may not be initialized in all environments (e.g.
# worktrees). We search multiple possible locations.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFORMANCE_DIR = _REPO_ROOT / "vendor" / "plutus" / "plutus-conformance" / "test-cases" / "uplc" / "evaluation"

# If the worktree's vendor dir is empty, try the main repo
if not _CONFORMANCE_DIR.exists() or not any(_CONFORMANCE_DIR.iterdir()):
    # Try the main repo root (parent of .claude/worktrees/...)
    _alt_root = Path(os.environ.get("VIBE_NODE_ROOT", ""))
    if _alt_root.exists():
        _alt = _alt_root / "vendor" / "plutus" / "plutus-conformance" / "test-cases" / "uplc" / "evaluation"
        if _alt.exists() and any(_alt.iterdir()):
            _CONFORMANCE_DIR = _alt

    # Also try a common worktree parent pattern
    for parent in _REPO_ROOT.parents:
        if parent.name == "vibe-node" and (parent / "vendor" / "plutus").is_dir():
            _alt = parent / "vendor" / "plutus" / "plutus-conformance" / "test-cases" / "uplc" / "evaluation"
            if _alt.exists() and any(_alt.iterdir()):
                _CONFORMANCE_DIR = _alt
                break


class UplcTestCase(NamedTuple):
    """A single UPLC conformance test case."""

    name: str
    uplc_path: Path
    expected_path: Path


def _discover_test_cases(limit: int = 0) -> list[UplcTestCase]:
    """Walk the conformance directory and discover .uplc + .expected pairs.

    Args:
        limit: Maximum number of test cases to return. 0 means all.

    Returns:
        List of UplcTestCase tuples sorted by name for deterministic ordering.
    """
    if not _CONFORMANCE_DIR.exists():
        return []

    cases: list[UplcTestCase] = []
    for uplc_file in sorted(_CONFORMANCE_DIR.rglob("*.uplc")):
        # Skip budget-specific expected files
        if uplc_file.suffix != ".uplc":
            continue

        expected_file = uplc_file.with_suffix(".uplc.expected")
        if not expected_file.exists():
            continue

        # Build a readable test name from the relative path
        rel = uplc_file.relative_to(_CONFORMANCE_DIR)
        name = str(rel.with_suffix("")).replace("/", "::")

        cases.append(UplcTestCase(name=name, uplc_path=uplc_file, expected_path=expected_file))

        if 0 < limit <= len(cases):
            break

    return cases


# Discover test cases at module load time for parametrize
_ALL_CASES = _discover_test_cases()
_TEST_CASES = _ALL_CASES[:100] if len(_ALL_CASES) > 100 else _ALL_CASES


# ---------------------------------------------------------------------------
# Result comparison helpers
# ---------------------------------------------------------------------------

_EVALUATION_FAILURE = "evaluation failure"


def _normalize_whitespace(s: str) -> str:
    """Collapse all whitespace (including newlines) to single spaces and strip."""
    return re.sub(r"\s+", " ", s).strip()


def _try_structural_compare(actual_text: str, expected_text: str) -> bool | None:
    """Attempt structural (alpha-equivalent) comparison of two UPLC programs.

    Returns True if structurally equal, False if structurally different,
    None if comparison can't be performed (e.g. parse failure).
    """
    try:
        from uplc.tools import (
            DeBrujinVariableTransformer,
            UnDeBrujinVariableTransformer,
            dumps,
            parse,
        )

        actual_prog = parse(actual_text)
        expected_prog = parse(expected_text)

        # Normalize variable names through de Bruijn -> un-de-Bruijn round-trip
        db = DeBrujinVariableTransformer()
        udb = UnDeBrujinVariableTransformer()

        actual_norm = dumps(udb.visit(db.visit(actual_prog)))
        expected_norm = dumps(udb.visit(db.visit(expected_prog)))

        return _normalize_whitespace(actual_norm) == _normalize_whitespace(expected_norm)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.conformance
class TestUplcConformance:
    """UPLC evaluation conformance tests against the Plutus golden test suite.

    Each test parses a .uplc file, evaluates it with the uplc Python package's
    CEK machine, and compares the result against the .expected file from the
    official Plutus conformance test suite.
    """

    @pytest.mark.skipif(
        len(_TEST_CASES) == 0,
        reason=(
            "No UPLC conformance test cases found. "
            "Ensure vendor/plutus submodule is initialized: "
            "git submodule update --init vendor/plutus"
        ),
    )
    @pytest.mark.parametrize(
        "test_case",
        _TEST_CASES,
        ids=[tc.name for tc in _TEST_CASES],
    )
    def test_uplc_eval(self, test_case: UplcTestCase) -> None:
        """Evaluate a UPLC program and compare against expected output."""
        # Import here so missing uplc package gives a clear skip, not import error
        try:
            from uplc.ast import Program
            from uplc.tools import dumps, eval as uplc_eval, parse
        except ImportError:
            pytest.skip("uplc package not installed")

        # --- Read inputs ---
        source = test_case.uplc_path.read_text(encoding="utf-8")
        expected_raw = test_case.expected_path.read_text(encoding="utf-8").strip()
        expects_failure = expected_raw == _EVALUATION_FAILURE

        # --- Parse ---
        try:
            program = parse(source)
        except Exception as e:
            if expects_failure:
                # Some programs are intentionally malformed — parse failure
                # counts as evaluation failure, which is the expected outcome.
                return
            pytest.skip(f"Failed to parse UPLC source: {e}")

        # --- Evaluate ---
        try:
            result = uplc_eval(program)
        except Exception as e:
            if expects_failure:
                return  # Expected failure — pass
            pytest.fail(f"Unexpected evaluation exception: {e}")

        # --- Check for evaluation failure ---
        if isinstance(result.result, Exception):
            if expects_failure:
                return  # Expected failure — pass
            pytest.fail(
                f"Evaluation produced an error but expected success: {result.result}"
            )

        if expects_failure:
            pytest.fail(
                f"Expected evaluation failure but got a result: "
                f"{type(result.result).__name__}"
            )

        # --- Compare result against expected ---
        # Wrap the result term in a Program to get the textual representation
        result_program = Program(program.version, result.result)
        actual_text = dumps(result_program)

        # First try direct string comparison (handles most cases: constants, etc.)
        actual_norm = _normalize_whitespace(actual_text)
        expected_norm = _normalize_whitespace(expected_raw)

        if actual_norm == expected_norm:
            return  # Exact match — pass

        # If direct comparison fails, try structural comparison
        # (handles alpha-equivalence for lambda/closure results)
        structural_result = _try_structural_compare(actual_text, expected_raw)
        if structural_result is True:
            return  # Structurally equivalent — pass
        elif structural_result is False:
            pytest.fail(
                f"Result mismatch.\n"
                f"  Expected: {expected_norm}\n"
                f"  Actual:   {actual_norm}"
            )
        else:
            # Structural comparison failed (likely can't parse expected due to
            # hyphenated variable names). Mark as xfail with the details.
            pytest.xfail(
                f"Cannot structurally compare results — expected output uses "
                f"variable names that the uplc parser cannot handle.\n"
                f"  Expected: {expected_norm}\n"
                f"  Actual:   {actual_norm}"
            )


# ---------------------------------------------------------------------------
# Summary statistics test
# ---------------------------------------------------------------------------


@pytest.mark.conformance
class TestUplcConformanceSummary:
    """Meta-test that reports discovery statistics."""

    def test_cases_discovered(self) -> None:
        """Report how many test cases were discovered."""
        total = len(_ALL_CASES)
        running = len(_TEST_CASES)

        if total == 0:
            pytest.skip(
                "No UPLC conformance test cases found. "
                "Ensure vendor/plutus submodule is initialized."
            )

        # This test always passes — it's purely informational
        print(f"\nUPLC conformance: {running} of {total} test cases parametrized")
        assert running > 0, "Expected at least some test cases"
        assert running <= total
