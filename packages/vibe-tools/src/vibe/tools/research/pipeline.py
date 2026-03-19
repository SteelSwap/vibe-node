"""PydanticAI rule extraction and linking pipeline.

4-stage agentic pipeline:
1. Rule Extraction — LLM reads spec chunk, outputs structured rules
2. Semantic Search — Vector search for candidate code/tests/issues
3. Link Evaluation — LLM evaluates each candidate relationship
4. Gap Detection — LLM compares rule vs code, proposes Hypothesis tests

Usage:
    vibe-node research extract-rules --subsystem networking
"""
from __future__ import annotations

import logging
import os
import uuid

from pydantic_ai import Agent

from vibe_node.research.models import (
    AnalysisResult,
    ExtractionResult,
    LinkDecision,
    SearchCandidate,
)

logger = logging.getLogger(__name__)

# Model configuration — supports Anthropic API or AWS Bedrock.
# Bedrock format: "bedrock:us.anthropic.claude-opus-4-6-v1"
# Anthropic format: "anthropic:claude-sonnet-4-20250514"
# Override via environment variables.
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", "bedrock:us.anthropic.claude-opus-4-6-v1")
LINKING_MODEL = os.environ.get("LINKING_MODEL", "bedrock:us.anthropic.claude-sonnet-4-5-20250929-v1:0")


def _get_model(model_str: str):
    """Create a PydanticAI model, handling Bedrock bearer token auth.

    Supports:
    - AWS_BEARER_TOKEN or AWS_BEARER_TOKEN_BEDROCK for gateway auth
    - BEDROCK_BASE_URL for custom gateway endpoints
    - Standard AWS credentials (access key, profile, etc.)

    PydanticAI natively checks AWS_BEARER_TOKEN_BEDROCK, but we also
    accept AWS_BEARER_TOKEN for convenience.
    """
    bearer_token = os.environ.get("AWS_BEARER_TOKEN") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    base_url = os.environ.get("BEDROCK_BASE_URL")

    if bearer_token and model_str.startswith("bedrock:"):
        from pydantic_ai.models.bedrock import BedrockConverseModel
        from pydantic_ai.providers.bedrock import BedrockProvider

        model_name = model_str.removeprefix("bedrock:")
        provider = BedrockProvider(
            api_key=bearer_token,
            region_name=region,
            base_url=base_url,
        )
        return BedrockConverseModel(model_name, provider=provider)

    return model_str  # Let PydanticAI resolve it via string


EXTRACTION_SYSTEM_PROMPT = """You are a formal specification analyst. You read Cardano protocol specification chunks
and extract individual rules, definitions, equations, and type declarations.

For each rule you find:
1. Assign a stable section_id like 'shelley-ledger:rule-utxo-transition' or 'byron-crypto:def-hash'
2. Classify as rule, definition, equation, type, figure, or algorithm
3. Copy the verbatim spec text exactly
4. Write an extracted_rule that is self-contained — include any referenced definitions
   or types needed to understand the rule without reading the surrounding spec

If a chunk contains no extractable rules (e.g., it's just prose introduction), return an empty rules list.

IMPORTANT: Use the era and subsystem provided. The section_id should follow the pattern:
{era}-{subsystem}:{type}-{descriptive-name}
"""

LINKING_SYSTEM_PROMPT = """You evaluate whether a candidate code function, test, or GitHub discussion
is related to a formal specification rule.

You will be given:
1. A spec rule (verbatim + extracted description)
2. A candidate entity (code function, test, or issue/PR)

Determine:
- Is this candidate genuinely related to the spec rule? (not just superficially similar)
- What relationship type? (implements, tests, discusses, references, contradicts, extends,
  derivedFrom, supersedes, requires, trackedBy)
- How confident are you? (0.0-1.0)

For 'implements': the code must actually implement the logic described by the rule.
For 'tests': the code must be a test that verifies the rule's behavior.
For 'discusses': the issue/PR must contain substantive discussion about the rule.

Be strict — false positives are worse than false negatives. Only mark is_linked=True
if you're genuinely confident the relationship exists.
"""

ANALYSIS_SYSTEM_PROMPT = """You analyze a formal specification rule and its implementing Haskell code
to detect divergences and propose tests.

You will be given:
1. A spec rule (verbatim + extracted description)
2. The Haskell code that implements it (if any)

Your tasks:
A) GAP DETECTION: Compare the spec and code. If the code behaves differently
   than the spec describes, document the gap:
   - spec_says: what the spec defines
   - haskell_does: what the code actually does
   - delta: the specific difference
   - implications: how this affects our Python implementation

B) TEST PROPOSALS: Propose concrete tests for this rule:
   - Unit tests (pytest): concrete input/output cases
   - Property tests (Hypothesis): invariants with value ranges and generators
   - Include hypothesis_strategy for property tests describing the generators

Focus on the most important tests — don't propose trivial tests.
For property tests, be specific about value ranges (e.g., "lovelace values 0 to 45e15").
"""


# === Lazy Agent Creation ===
# Agents are created on first use, not at import time.
# This avoids crashes when API keys aren't configured yet.

_extraction_agent: Agent | None = None
_link_eval_agent: Agent | None = None
_analysis_agent: Agent | None = None


def get_extraction_agent() -> Agent:
    global _extraction_agent
    if _extraction_agent is None:
        _extraction_agent = Agent(
            model=_get_model(EXTRACTION_MODEL),
            output_type=ExtractionResult,
            system_prompt=EXTRACTION_SYSTEM_PROMPT,
        )
    return _extraction_agent


def get_link_eval_agent() -> Agent:
    global _link_eval_agent
    if _link_eval_agent is None:
        _link_eval_agent = Agent(
            model=_get_model(LINKING_MODEL),
            output_type=LinkDecision,
            system_prompt=LINKING_SYSTEM_PROMPT,
        )
    return _link_eval_agent


def get_analysis_agent() -> Agent:
    global _analysis_agent
    if _analysis_agent is None:
        _analysis_agent = Agent(
            model=_get_model(EXTRACTION_MODEL),
            output_type=AnalysisResult,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
        )
    return _analysis_agent


# === Pipeline Orchestration ===


async def stage1_extract(
    conn, spec_chunk_id: uuid.UUID, era: str, subsystem: str,
) -> ExtractionResult:
    """Stage 1: Extract rules from a spec chunk."""
    row = await conn.fetchrow(
        "SELECT content_markdown, document_title, section_title, subsection_title "
        "FROM spec_documents WHERE id = $1",
        spec_chunk_id,
    )
    if not row:
        return ExtractionResult(
            spec_chunk_id=str(spec_chunk_id), era=era, subsystem=subsystem, rules=[],
        )

    context = (
        f"Document: {row['document_title']}\n"
        f"Section: {row['section_title'] or 'N/A'}\n"
        f"Subsection: {row['subsection_title'] or 'N/A'}\n"
        f"Era: {era}\n"
        f"Subsystem: {subsystem}\n\n"
        f"Content:\n{row['content_markdown']}"
    )

    result = await get_extraction_agent().run(
        f"Extract all rules, definitions, and equations from this spec chunk:\n\n{context}",
    )
    # Override the chunk metadata in case the agent changed them
    result.output.spec_chunk_id = str(spec_chunk_id)
    result.output.era = era
    result.output.subsystem = subsystem
    return result.output


async def stage2_search(
    conn, extracted_rule: str, subsystem: str,
) -> list[SearchCandidate]:
    """Stage 2: Semantic search for candidate links."""
    from vibe_node.db.search import build_vector_query
    from vibe_node.db.search_config import get_available_configs
    from vibe_node.embed.client import EmbeddingClient

    client = EmbeddingClient()
    embedding = await client.embed(extracted_rule[:8000])
    await client.close()

    available = await get_available_configs(conn)
    candidates = []

    # Search code (including tests) — only latest tag per repo
    # First, get the latest release tag for each repo
    latest_tags = await conn.fetch(
        "SELECT repo, MAX(release_tag) as latest_tag FROM code_tag_completion GROUP BY repo"
    )
    latest_tag_set = {(row["repo"], row["latest_tag"]) for row in latest_tags}

    if latest_tag_set:
        # Build a filter for latest tags only
        tag_conditions = " OR ".join(
            f"(repo = '{repo}' AND release_tag = '{tag}')"
            for repo, tag in latest_tag_set
        )
        try:
            # Vector search with tag filter — use raw SQL for the complex WHERE
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
            rows = await conn.fetch(
                f"""SELECT id, function_name, content,
                       1 - (embedding <=> $1::vector) AS similarity
                FROM code_chunks
                WHERE ({tag_conditions})
                AND embedding IS NOT NULL
                ORDER BY embedding <=> $1::vector
                LIMIT 10""",
                embedding_str,
            )
            for row in rows:
                candidates.append(SearchCandidate(
                    entity_type="code_chunk",
                    entity_id=str(row["id"]),
                    title=row.get("function_name", ""),
                    content_preview=(row.get("content", "") or "")[:500],
                    similarity=float(row.get("similarity", 0)),
                ))
        except Exception as e:
            logger.warning("Code search failed: %s", e)

    # Search issues
    if "issue" in available:
        cfg = available["issue"]
        sql, params = build_vector_query(
            cfg["table"], embedding, {}, cfg.get("filter_columns", {}), 5, 0,
        )
        try:
            rows = await conn.fetch(sql, *params)
            for row in rows:
                candidates.append(SearchCandidate(
                    entity_type="github_issue",
                    entity_id=str(row["id"]),
                    title=row.get("title", ""),
                    content_preview=(row.get("content_combined", "") or "")[:500],
                    similarity=1.0 - float(row.get("vector_distance", 1.0)),
                ))
        except Exception as e:
            logger.warning("Issue search failed: %s", e)

    # Search PRs
    if "pr" in available:
        cfg = available["pr"]
        sql, params = build_vector_query(
            cfg["table"], embedding, {}, cfg.get("filter_columns", {}), 5, 0,
        )
        try:
            rows = await conn.fetch(sql, *params)
            for row in rows:
                candidates.append(SearchCandidate(
                    entity_type="github_pr",
                    entity_id=str(row["id"]),
                    title=row.get("title", ""),
                    content_preview=(row.get("content_combined", "") or "")[:500],
                    similarity=1.0 - float(row.get("vector_distance", 1.0)),
                ))
        except Exception as e:
            logger.warning("PR search failed: %s", e)

    return candidates


async def stage3_evaluate_link(
    rule_verbatim: str, rule_extracted: str, candidate: SearchCandidate,
) -> LinkDecision:
    """Stage 3: LLM evaluates whether a candidate is linked to a rule."""
    prompt = (
        f"SPEC RULE:\n"
        f"Verbatim: {rule_verbatim[:1000]}\n"
        f"Extracted: {rule_extracted[:2000]}\n\n"
        f"CANDIDATE ({candidate.entity_type}):\n"
        f"Title: {candidate.title}\n"
        f"Content: {candidate.content_preview}\n"
        f"Similarity: {candidate.similarity:.3f}"
    )
    result = await get_link_eval_agent().run(prompt)
    return result.output


async def stage4_analyze(
    rule_verbatim: str, rule_extracted: str,
    implementing_code: str | None = None,
) -> AnalysisResult:
    """Stage 4: Gap detection + test proposal."""
    prompt = (
        f"SPEC RULE:\n"
        f"Verbatim: {rule_verbatim[:1000]}\n"
        f"Extracted: {rule_extracted[:2000]}\n"
    )
    if implementing_code:
        prompt += f"\nIMPLEMENTING HASKELL CODE:\n{implementing_code[:3000]}"
    else:
        prompt += "\nNo implementing code found — propose tests based on the spec rule alone."

    result = await get_analysis_agent().run(prompt)
    return result.output


async def _process_chunk(
    pool, chunk_id: uuid.UUID, era: str, subsystem: str,
) -> dict:
    """Process a single spec chunk through all 4 pipeline stages.

    Uses its own DB connection from the pool for concurrency safety.
    Returns per-chunk stats.
    """
    import asyncio as _asyncio
    from vibe_node.db.spec_sections import add_spec_section
    from vibe_node.db.test_specs import add_test_spec
    from vibe_node.db.xref import add_xref
    from vibe_node.embed.client import EmbeddingClient

    chunk_stats = {
        "rules_extracted": 0, "links_created": 0,
        "gaps_found": 0, "tests_proposed": 0,
    }

    async with pool.acquire() as conn:
        # Check if already processed — use a marker in spec_documents metadata
        # to track chunks that were processed (even if they produced no rules)
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM spec_sections WHERE spec_chunk_id = $1", chunk_id,
        )
        # Also check if we previously processed this chunk and got no rules
        # by looking for a marker we set after extraction
        already_extracted = await conn.fetchval(
            "SELECT (metadata->>'extraction_processed')::boolean FROM spec_documents WHERE id = $1",
            chunk_id,
        )
        if existing > 0 or already_extracted:
            logger.debug("Skipping already-processed chunk %s", chunk_id)
            return chunk_stats

        # Stage 1: Extract rules
        try:
            extraction = await stage1_extract(conn, chunk_id, era, subsystem)
        except Exception as e:
            logger.warning("Extraction failed for chunk %s: %s", chunk_id, e)
            return chunk_stats

        # Mark chunk as processed (even if no rules extracted)
        await conn.execute(
            """UPDATE spec_documents
            SET metadata = COALESCE(metadata, '{}'::jsonb) || '{"extraction_processed": true}'::jsonb
            WHERE id = $1""",
            chunk_id,
        )

        embed_client = EmbeddingClient()

        for rule in extraction.rules:
            embedding = await embed_client.embed(rule.extracted_rule[:8000])

            section_uuid = await add_spec_section(
                conn,
                section_id=rule.section_id,
                title=rule.title,
                section_type=rule.section_type.value,
                era=era,
                subsystem=subsystem,
                verbatim=rule.verbatim,
                extracted_rule=rule.extracted_rule,
                spec_chunk_id=chunk_id,
                embedding=embedding,
            )
            chunk_stats["rules_extracted"] += 1

            # Stage 2: Semantic search for candidates
            candidates = await stage2_search(conn, rule.extracted_rule, subsystem)

            # Stage 3: Evaluate all candidates concurrently
            async def _eval_candidate(cand):
                try:
                    decision = await stage3_evaluate_link(
                        rule.verbatim, rule.extracted_rule, cand,
                    )
                    return cand, decision
                except Exception as e:
                    logger.warning("Link eval failed: %s", e)
                    return cand, None

            eval_results = await _asyncio.gather(*[_eval_candidate(c) for c in candidates])

            implementing_code = None
            for candidate, decision in eval_results:
                if decision is None:
                    continue
                if decision.is_linked and decision.relationship:
                    await add_xref(
                        conn,
                        source_type="spec_section",
                        source_id=section_uuid,
                        target_type=candidate.entity_type,
                        target_id=uuid.UUID(candidate.entity_id),
                        relationship=decision.relationship.value,
                        confidence=decision.confidence,
                        notes=decision.notes,
                        created_by="pipeline",
                    )
                    chunk_stats["links_created"] += 1

                    if (
                        decision.relationship.value == "implements"
                        and candidate.entity_type == "code_chunk"
                        and implementing_code is None
                    ):
                        code_row = await conn.fetchrow(
                            "SELECT content FROM code_chunks WHERE id = $1",
                            uuid.UUID(candidate.entity_id),
                        )
                        if code_row:
                            implementing_code = code_row["content"]

            # Stage 4: Gap detection + test proposals
            try:
                analysis = await stage4_analyze(
                    rule.verbatim, rule.extracted_rule, implementing_code,
                )
            except Exception as e:
                logger.warning("Analysis failed for %s: %s", rule.section_id, e)
                continue

            if analysis.gap:
                try:
                    await conn.execute(
                        """INSERT INTO gap_analysis (id, spec_section_id, subsystem, era,
                            spec_says, haskell_does, delta, implications, discovered_during)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                        ON CONFLICT (spec_section_id, delta) DO UPDATE SET
                            spec_says = EXCLUDED.spec_says,
                            haskell_does = EXCLUDED.haskell_does,
                            implications = EXCLUDED.implications""",
                        uuid.uuid4(), section_uuid, subsystem, era,
                        analysis.gap.spec_says, analysis.gap.haskell_does,
                        analysis.gap.delta, analysis.gap.implications,
                        f"Phase 1 pipeline, subsystem={subsystem}",
                    )
                    chunk_stats["gaps_found"] += 1
                except Exception as e:
                    logger.warning("Gap insert failed for %s: %s", rule.section_id, e)

            for test in analysis.proposed_tests:
                try:
                    await add_test_spec(
                        conn,
                        subsystem=subsystem,
                        test_type=test.test_type.value,
                        test_name=test.test_name,
                        description=test.description,
                        priority=test.priority.value,
                        phase="phase-2" if subsystem in ("serialization", "networking", "miniprotocols-n2n") else "phase-3",
                        spec_section_id=section_uuid,
                        hypothesis_strategy=test.hypothesis_strategy,
                    )
                    chunk_stats["tests_proposed"] += 1
                except Exception as e:
                    logger.warning("Test spec insert failed for %s: %s", test.test_name, e)

        await embed_client.close()

    return chunk_stats


async def run_pipeline(
    conn, subsystem: str, limit: int | None = None, progress=None,
    concurrency: int = 3,
) -> dict:
    """Run the full 4-stage pipeline for a subsystem.

    Args:
        conn: asyncpg connection (used only for initial chunk discovery).
        subsystem: Which subsystem to process.
        limit: Max chunks to process.
        progress: Rich Progress instance.
        concurrency: Number of chunks to process in parallel.

    Returns summary stats.
    """
    import asyncio as _asyncio
    from vibe_node.db.pool import get_pool

    # Track in-progress chunks to prevent concurrent processing of the same chunk
    _in_progress: set[uuid.UUID] = set()

    # Map subsystem names to search terms for finding relevant spec chunks
    subsystem_terms = {
        "networking": ["ouroboros-network", "network", "multiplexer"],
        "miniprotocols-n2n": ["chain-sync", "block-fetch", "tx-submission", "keep-alive"],
        "miniprotocols-n2c": ["local-chain-sync", "local-tx", "state-query", "tx-monitor"],
        "consensus": ["ouroboros", "praos", "consensus", "chain selection"],
        "ledger": ["ledger", "utxo", "delegation", "epoch"],
        "plutus": ["plutus", "script", "cost-model", "CEK"],
        "serialization": ["cddl", "cbor", "serialization"],
        "mempool": ["mempool", "transaction buffer"],
        "storage": ["immutable", "volatile", "storage", "chaindb"],
        "block-production": ["forge", "block production", "leader"],
    }

    terms = subsystem_terms.get(subsystem, [subsystem])

    # Find relevant spec chunks
    chunks = []
    for term in terms:
        rows = await conn.fetch(
            "SELECT id, era FROM spec_documents "
            "WHERE content_markdown ILIKE $1 "
            "ORDER BY source_repo, document_title LIMIT 50",
            f"%{term}%",
        )
        for row in rows:
            chunks.append((row["id"], row["era"]))

    # Deduplicate
    seen = set()
    unique_chunks = []
    for chunk_id, era in chunks:
        if chunk_id not in seen:
            seen.add(chunk_id)
            unique_chunks.append((chunk_id, era))

    if limit:
        unique_chunks = unique_chunks[:limit]

    stats = {
        "chunks_processed": 0,
        "rules_extracted": 0,
        "links_created": 0,
        "gaps_found": 0,
        "tests_proposed": 0,
    }

    logger.info(
        "Processing %d spec chunks for subsystem=%s (concurrency=%d)",
        len(unique_chunks), subsystem, concurrency,
    )

    # Set progress bar total now that we know the real deduplicated count
    if progress:
        progress.update(progress.task_ids[0], total=len(unique_chunks))

    pool = await get_pool()
    semaphore = _asyncio.Semaphore(concurrency)

    async def _process_with_semaphore(chunk_id, era):
        # Skip if another concurrent task is already processing this chunk
        if chunk_id in _in_progress:
            return
        _in_progress.add(chunk_id)

        async with semaphore:
            chunk_stats = await _process_chunk(pool, chunk_id, era, subsystem)
            for key in chunk_stats:
                stats[key] += chunk_stats[key]
            stats["chunks_processed"] += 1
            if progress:
                progress.update(progress.task_ids[0], advance=1)

    # Launch all chunks concurrently (semaphore limits actual parallelism)
    tasks = [_process_with_semaphore(cid, era) for cid, era in unique_chunks]
    await _asyncio.gather(*tasks)

    return stats
