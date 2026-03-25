"""QA Validation pipeline for extracted rules and gaps.

Runs after the extraction pipeline to validate and categorize results:
1. Verify "missing implementation" gaps by searching vendor repos directly
2. Categorize gaps (perf optimization, post-spec addition, representation mismatch, etc.)
3. Assess severity for our implementation
4. Verify cross-reference accuracy
5. Deduplicate and validate test specifications

Usage:
    vibe-node research qa-validate --subsystem networking
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent

logger = logging.getLogger(__name__)

QA_MODEL = os.environ.get("QA_MODEL", "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0")


class GapCategory(str, Enum):
    performance_optimization = "performance_optimization"
    post_spec_addition = "post_spec_addition"
    representation_mismatch = "representation_mismatch"
    calculation_difference = "calculation_difference"
    evaluation_order = "evaluation_order"
    genuine_spec_violation = "genuine_spec_violation"
    unimplemented_spec_rule = "unimplemented_spec_rule"
    search_failure = "search_failure"


class GapSeverity(str, Enum):
    critical = "critical"  # Must match Haskell behavior exactly
    important = "important"  # Affects correctness, needs careful handling
    informational = "informational"  # Good to know, can use spec approach initially
    false_positive = "false_positive"  # Not a real gap


class GapValidation(BaseModel):
    """QA agent's assessment of a gap entry."""

    category: GapCategory
    severity: GapSeverity
    verified: bool = Field(description="True if the gap was verified against source code")
    code_found: bool = Field(description="True if implementing code was found via git grep")
    code_location: str | None = Field(default=None, description="File path if code was found")
    assessment: str = Field(description="Brief explanation of the validation result")
    implementation_note: str = Field(description="What this means for our Python implementation")


class XrefValidation(BaseModel):
    """QA agent's assessment of a cross-reference."""

    is_accurate: bool = Field(description="True if the cross-reference is genuinely correct")
    confidence_adjustment: float = Field(description="New confidence score 0.0-1.0")
    notes: str | None = None


def _get_qa_model():
    """Create the QA model lazily."""
    bearer_token = os.environ.get("AWS_BEARER_TOKEN") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    base_url = os.environ.get("BEDROCK_BASE_URL")

    if bearer_token and QA_MODEL.startswith("bedrock:"):
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider

        model_name = QA_MODEL.removeprefix("bedrock:")
        provider = BedrockProvider(api_key=bearer_token, region_name=region, base_url=base_url)
        return BedrockConverseModel(model_name, provider=provider)

    return QA_MODEL


_gap_qa_agent: Agent | None = None
_xref_qa_agent: Agent | None = None


def get_gap_qa_agent() -> Agent:
    global _gap_qa_agent
    if _gap_qa_agent is None:
        _gap_qa_agent = Agent(
            model=_get_qa_model(),
            output_type=GapValidation,
            system_prompt="""You are a QA validator for a Cardano node specification analysis.

You are given a gap entry (spec vs Haskell implementation divergence) along with
context from TWO search phases:

**Phase 1 (keyword search):** git grep for function names and keywords from the gap.
**Phase 2 (deep dive):** If Phase 1 found nothing, traces call chains from known
subsystem entry points, reads surrounding code context, and searches for Haskell
types/constructors mentioned in the gap text. This catches implementations that
use indirect mechanisms (STM retry, type-level gates, multi-layer indirection).

Your job:
1. CATEGORIZE the gap:
   - performance_optimization: Haskell uses optimized types/algorithms but semantics match spec
   - post_spec_addition: Feature added after spec was written
   - representation_mismatch: Different data representation but same semantics
   - calculation_difference: Different computation approach, need to verify equivalence
   - evaluation_order: Different order of operations, may be semantically equivalent
   - genuine_spec_violation: Haskell actually violates the spec
   - unimplemented_spec_rule: Spec rule has no implementation
   - search_failure: The original pipeline couldn't find the code but it actually exists
     (IMPORTANT: if Phase 2 deep dive found code that Phase 1 missed, use this category)

2. ASSESS SEVERITY for our Python implementation:
   - critical: Must match Haskell behavior exactly (consensus-affecting)
   - important: Affects correctness, needs careful handling
   - informational: Good to know, can use spec approach initially
   - false_positive: Not a real gap after investigation

3. Note what this means for our implementation.

Be rigorous. Read [CONTEXT] blocks carefully — they show the surrounding code at
relevant locations. Haskell often implements spec rules via indirect mechanisms:
- STM `retry` blocking instead of explicit `if` guards
- Type constructors (e.g., `CurrentSlotUnknown`) that gate behavior
- Multi-layer architecture where 3+ files collaborate to enforce one rule
- Emergent behavior from the architecture rather than a single function

When the gap says "no implementing code was found" but the deep dive found
relevant code, downgrade from critical to the appropriate severity and
categorize as search_failure.
""",
        )
    return _gap_qa_agent


def get_xref_qa_agent() -> Agent:
    global _xref_qa_agent
    if _xref_qa_agent is None:
        _xref_qa_agent = Agent(
            model=_get_qa_model(),
            output_type=XrefValidation,
            system_prompt="""You validate cross-references between spec rules and Haskell code.

Given a spec rule and the Haskell function it's supposedly linked to,
determine if the link is accurate. Check:
- Does the code actually implement the logic described by the rule?
- Is the relationship type correct (implements vs references vs tests)?
- What confidence should we have in this link?

Be strict — false positives waste developer time.
""",
        )
    return _xref_qa_agent


def _git_grep(term: str, repo_path: Path, max_results: int = 5) -> list[str]:
    """Search vendor repos for a term using git grep."""
    results = []
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "-i", "--max-count", str(max_results), term],
            cwd=repo_path,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            stdout = result.stdout.decode("utf-8", errors="replace")
            for line in stdout.strip().splitlines()[:max_results]:
                results.append(line[:500])  # Truncate long lines
    except (subprocess.TimeoutExpired, OSError):
        pass
    return results


def _read_file_section(file_path: Path, center_line: int, context: int = 30) -> str:
    """Read a section of a file around a given line number."""
    try:
        lines = file_path.read_text(errors="replace").splitlines()
        start = max(0, center_line - context)
        end = min(len(lines), center_line + context)
        numbered = [f"{i + 1:>4} | {lines[i]}" for i in range(start, end)]
        return "\n".join(numbered)
    except (OSError, UnicodeDecodeError):
        return ""


def _find_callers(function_name: str, repo_path: Path, max_results: int = 10) -> list[str]:
    """Find where a function is called from in a repo (call chain tracing)."""
    results = []
    try:
        result = subprocess.run(
            ["git", "grep", "-n", "--max-count", str(max_results), function_name],
            cwd=repo_path,
            capture_output=True,
            timeout=15,
        )
        if result.returncode == 0:
            stdout = result.stdout.decode("utf-8", errors="replace")
            for line in stdout.strip().splitlines()[:max_results]:
                # Skip the definition itself — we want callers
                if f"= {function_name}" not in line and ":: " not in line:
                    results.append(line[:500])
    except (subprocess.TimeoutExpired, OSError):
        pass
    return results


def _search_vendor_repos(search_terms: list[str]) -> dict[str, list[str]]:
    """Search all vendor repos for terms. Returns {repo: [matching lines]}."""
    project_root = Path(__file__).resolve().parents[6]
    vendor_dir = project_root / "vendor"

    all_results = {}
    if not vendor_dir.exists():
        return all_results

    for repo_dir in vendor_dir.iterdir():
        if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
            continue
        repo_name = repo_dir.name
        repo_results = []
        for term in search_terms:
            matches = _git_grep(term, repo_dir)
            repo_results.extend(matches)
        if repo_results:
            all_results[repo_name] = repo_results[:20]  # Cap per repo

    return all_results


# Subsystem -> known entry point functions in Haskell codebase.
# When keyword search fails, trace call chains from these entry points.
SUBSYSTEM_ENTRY_POINTS: dict[str, list[str]] = {
    "block-production": [
        "forkBlockForging",
        "knownSlotWatcher",
        "checkShouldForge",
        "forgeBlock",
        "getCurrentSlot",
        "mkCurrentBlockContext",
        "forecastFor",
    ],
    "consensus": [
        "tickChainDepState",
        "reupdateChainDepState",
        "preferAnchoredCandidate",
        "compareCandidates",
        "checkLeaderVal",
        "praosVrfChecks",
        "chainSelectionForBlock",
    ],
    "ledger": [
        "applyBlockTransition",
        "validateTx",
        "utxoTransition",
        "delegsTransition",
        "epochTransition",
        "applyRUpd",
    ],
    "storage": [
        "addBlockAsync",
        "chainSelSync",
        "copyToImmutableDB",
        "garbageCollect",
        "instructionSTM",
        "switchFork",
    ],
    "networking": [
        "chainSyncClient",
        "blockFetchClient",
        "txSubmissionClient",
        "runMiniProtocol",
        "runMux",
        "demux",
    ],
    "serialization": [
        "decCBOR",
        "encCBOR",
        "hashAnnotated",
        "MemoBytes",
        "Annotator",
    ],
    "plutus": [
        "evaluateScriptCounting",
        "mkTermToEvaluate",
        "runCekDeBruijn",
        "processLogsAndErrors",
        "deserialiseScript",
    ],
    "mempool": [
        "addTx",
        "removeTxs",
        "syncWithLedger",
        "getSnapshotFor",
    ],
}


def _deep_dive_search(
    subsystem: str, gap_delta: str, gap_spec_says: str
) -> dict[str, list[str]]:
    """Deep-dive search for a gap that keyword search missed.

    Instead of grepping for keywords from the gap description, trace
    call chains from known entry points for the subsystem. This catches
    cases where the implementation uses indirect mechanisms (STM retry,
    type-level gates, multi-layer indirection) that don't contain the
    spec rule's keywords.

    The approach that discovered the 3-layer forge sync gate:
    1. Start from known entry points for the subsystem
    2. Find where those functions are called and what they call
    3. Read the surrounding code for behavioral patterns
    4. Look for data types and constructors (not just functions)
    """
    project_root = Path(__file__).resolve().parents[6]
    vendor_dir = project_root / "vendor"

    if not vendor_dir.exists():
        return {}

    entry_points = SUBSYSTEM_ENTRY_POINTS.get(subsystem, [])
    if not entry_points:
        return {}

    all_results: dict[str, list[str]] = {}

    # Also extract potential type/constructor names from the gap text
    type_terms = []
    for word in (gap_delta + " " + gap_spec_says).split():
        cleaned = word.strip(".,;:()[]{}'\"`")
        # Look for PascalCase (Haskell types/constructors)
        if len(cleaned) > 3 and cleaned[0].isupper() and any(c.islower() for c in cleaned):
            type_terms.append(cleaned)
        # Look for camelCase (Haskell functions)
        if len(cleaned) > 4 and cleaned[0].islower() and any(c.isupper() for c in cleaned):
            type_terms.append(cleaned)

    # Deduplicate and limit
    type_terms = list(set(type_terms))[:10]
    search_terms = entry_points + type_terms

    for repo_dir in vendor_dir.iterdir():
        if not repo_dir.is_dir() or not (repo_dir / ".git").exists():
            continue
        repo_name = repo_dir.name
        repo_results = []

        for term in search_terms:
            # Standard grep
            matches = _git_grep(term, repo_dir, max_results=3)
            repo_results.extend(matches)

            # For entry points, also trace callers (one level up)
            if term in entry_points and matches:
                callers = _find_callers(term, repo_dir, max_results=5)
                for caller in callers:
                    repo_results.append(f"[CALLER] {caller}")

        # Read surrounding code for the most relevant matches
        for match in repo_results[:3]:
            if ":" in match and not match.startswith("[CALLER]"):
                parts = match.split(":", 2)
                if len(parts) >= 2:
                    file_path = repo_dir / parts[0]
                    try:
                        line_num = int(parts[1])
                        section = _read_file_section(file_path, line_num, context=15)
                        if section:
                            repo_results.append(f"[CONTEXT] {parts[0]}:{parts[1]}\n{section}")
                    except (ValueError, OSError):
                        pass

        if repo_results:
            all_results[repo_name] = repo_results[:30]

    return all_results


async def validate_gaps(
    pool,
    subsystem: str,
    limit: int | None = None,
    concurrency: int = 5,
    progress=None,
    task_id=None,
) -> dict:
    """Validate and categorize gap_analysis entries for a subsystem."""
    import asyncio

    stats = {
        "gaps_validated": 0,
        "search_failures_resolved": 0,
        "false_positives": 0,
        "critical": 0,
        "important": 0,
        "informational": 0,
    }

    # Fetch gaps with their spec section context (single query, own connection)
    query = """
        SELECT ga.id, ga.spec_section_id, ga.delta, ga.spec_says, ga.haskell_does,
               ga.implications, ss.section_id, ss.title, ss.verbatim, ss.extracted_rule
        FROM gap_analysis ga
        LEFT JOIN spec_sections ss ON ga.spec_section_id = ss.id
        WHERE ga.subsystem = $1
        AND (ga.metadata IS NULL OR NOT (ga.metadata ? 'qa_validated'))
        ORDER BY ga.id
    """
    params = [subsystem]
    if limit:
        query += f" LIMIT ${len(params) + 1}"
        params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    if progress and task_id is not None:
        progress.update(task_id, total=len(rows))

    semaphore = asyncio.Semaphore(concurrency)

    async def _validate_gap(row):
        async with semaphore:
            gap_id = row["id"]
            title = row["title"] or "Unknown"
            delta = row["delta"] or ""
            spec_says = row["spec_says"] or ""
            haskell_does = row["haskell_does"] or ""

            # --- Phase 1: Keyword search (fast, shallow) ---
            search_terms = []
            if title:
                words = title.split()
                search_terms.extend([w for w in words if len(w) > 4 and w[0].islower()])
            if "function" in delta.lower() or "missing" in delta.lower():
                for word in delta.split():
                    if len(word) > 4 and word[0].islower() and not word.startswith("the"):
                        search_terms.append(word.rstrip(".,;:"))
                        break

            search_terms = list(set(search_terms))[:5]

            vendor_results = {}
            if search_terms:
                vendor_results = _search_vendor_repos(search_terms)

            # --- Phase 2: Deep dive if keyword search found nothing ---
            # This catches implementations that use indirect mechanisms
            # (STM retry, type-level gates, multi-layer indirection)
            # that don't contain the spec rule's keywords.
            deep_dive_results = {}
            if not vendor_results or "no implementing" in haskell_does.lower():
                deep_dive_results = _deep_dive_search(subsystem, delta, spec_says)

            # Build context for the QA agent
            vendor_context = ""
            if vendor_results:
                vendor_context = "\n\nPHASE 1 — KEYWORD SEARCH RESULTS:\n"
                for repo, matches in vendor_results.items():
                    vendor_context += f"\n--- {repo} ---\n"
                    vendor_context += "\n".join(matches[:10])

            if deep_dive_results:
                vendor_context += "\n\nPHASE 2 — DEEP DIVE (entry point + call chain tracing):\n"
                for repo, matches in deep_dive_results.items():
                    vendor_context += f"\n--- {repo} ---\n"
                    vendor_context += "\n".join(matches[:15])
            elif not vendor_results:
                vendor_context = (
                    "\n\nNo matches found via keyword search OR deep-dive "
                    "call chain tracing from subsystem entry points."
                )

            prompt = (
                f"GAP ENTRY:\n"
                f"Rule: {title}\n"
                f"Spec says: {spec_says[:500]}\n"
                f"Haskell does: {haskell_does[:500]}\n"
                f"Delta: {delta[:800]}\n"
                f"{vendor_context}\n\n"
                f"IMPORTANT: If the Phase 1 keyword search found nothing but Phase 2 "
                f"deep dive found relevant code, this is likely a 'search_failure' — "
                f"the original pipeline missed it. Read the [CONTEXT] blocks carefully "
                f"to determine if the code actually implements the spec rule, possibly "
                f"via indirect mechanisms (STM retry, type constructors, multi-layer "
                f"indirection, or emergent behavior from architecture)."
            )

            try:
                result = await get_gap_qa_agent().run(prompt)
                validation = result.output

                # Update the gap with QA metadata
                qa_metadata = {
                    "qa_validated": True,
                    "category": validation.category.value,
                    "severity": validation.severity.value,
                    "verified": validation.verified,
                    "code_found": validation.code_found,
                    "code_location": validation.code_location,
                    "assessment": validation.assessment,
                    "implementation_note": validation.implementation_note,
                }

                # Each task gets its own connection from the pool
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE gap_analysis
                        SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
                        WHERE id = $2""",
                        json.dumps(qa_metadata),
                        gap_id,
                    )

                stats["gaps_validated"] += 1
                if validation.category == GapCategory.search_failure:
                    stats["search_failures_resolved"] += 1
                if validation.severity == GapSeverity.false_positive:
                    stats["false_positives"] += 1
                elif validation.severity == GapSeverity.critical:
                    stats["critical"] += 1
                elif validation.severity == GapSeverity.important:
                    stats["important"] += 1
                elif validation.severity == GapSeverity.informational:
                    stats["informational"] += 1

            except Exception as e:
                logger.warning("Gap validation failed for %s: %s", gap_id, e)

            if progress:
                progress.update(task_id, advance=1)

    tasks = [_validate_gap(row) for row in rows]
    await asyncio.gather(*tasks)

    return stats


async def validate_xrefs(
    pool,
    subsystem: str,
    limit: int | None = None,
    concurrency: int = 5,
    progress=None,
    task_id=None,
) -> dict:
    """Spot-check cross-references for accuracy."""
    import asyncio

    stats = {"checked": 0, "accurate": 0, "inaccurate": 0}

    # Sample cross-references to validate (focus on 'implements' — most important)
    query = """
        SELECT cr.id, cr.relationship, cr.confidence, cr.target_id, cr.target_type,
               ss.section_id, ss.title, ss.extracted_rule,
               cc.function_name, cc.module_name, cc.content as code_content
        FROM cross_references cr
        JOIN spec_sections ss ON cr.source_id = ss.id AND cr.source_type = 'spec_section'
        LEFT JOIN code_chunks cc ON cr.target_id = cc.id AND cr.target_type = 'code_chunk'
        WHERE ss.subsystem = $1
        AND cr.relationship = 'implements'
        AND (cr.notes IS NULL OR cr.notes NOT LIKE '%qa_validated%')
        ORDER BY cr.confidence ASC
    """
    params = [subsystem]
    if limit:
        query += f" LIMIT ${len(params) + 1}"
        params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    if progress and task_id is not None:
        progress.update(task_id, total=len(rows))

    semaphore = asyncio.Semaphore(concurrency)

    async def _validate_xref(row):
        async with semaphore:
            xref_id = row["id"]
            rule_title = row["title"]
            extracted_rule = row["extracted_rule"] or ""
            func_name = row["function_name"] or "unknown"
            code_content = row["code_content"] or ""

            prompt = (
                f"SPEC RULE: {rule_title}\n"
                f"Extracted: {extracted_rule[:1000]}\n\n"
                f"LINKED CODE: {func_name} in {row.get('module_name', '?')}\n"
                f"{code_content[:2000]}\n\n"
                f"Relationship: {row['relationship']} (confidence: {row['confidence']})"
            )

            try:
                result = await get_xref_qa_agent().run(prompt)
                validation = result.output

                # Each task gets its own connection from the pool
                async with pool.acquire() as conn:
                    await conn.execute(
                        """UPDATE cross_references
                        SET confidence = $1,
                            notes = COALESCE(notes, '') || ' [qa_validated]'
                        WHERE id = $2""",
                        validation.confidence_adjustment,
                        xref_id,
                    )

                stats["checked"] += 1
                if validation.is_accurate:
                    stats["accurate"] += 1
                else:
                    stats["inaccurate"] += 1

            except Exception as e:
                logger.warning("Xref validation failed for %s: %s", xref_id, e)

            if progress:
                progress.update(task_id, advance=1)

    tasks = [_validate_xref(row) for row in rows]
    await asyncio.gather(*tasks)

    return stats
