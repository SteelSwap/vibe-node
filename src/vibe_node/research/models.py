"""Pydantic models for the rule extraction and linking pipeline.

All pipeline stage inputs/outputs are strictly typed.
"""
from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class SectionType(str, Enum):
    rule = "rule"
    definition = "definition"
    equation = "equation"
    type_decl = "type"
    figure = "figure"
    algorithm = "algorithm"


class RelationshipType(str, Enum):
    implements = "implements"
    tests = "tests"
    discusses = "discusses"
    references = "references"
    contradicts = "contradicts"
    extends = "extends"
    derived_from = "derivedFrom"
    supersedes = "supersedes"
    requires = "requires"
    tracked_by = "trackedBy"


class TestType(str, Enum):
    unit = "unit"
    property = "property"
    replay = "replay"
    conformance = "conformance"
    integration = "integration"


class Priority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


# === Stage 1: Rule Extraction ===


class ExtractedRule(BaseModel):
    """A single rule/definition/equation extracted from a spec chunk."""

    section_id: str = Field(description="Stable identifier, e.g. 'shelley-ledger:rule-utxo-transition'")
    title: str = Field(description="Human-readable title")
    section_type: SectionType
    verbatim: str = Field(description="Exact text from the spec")
    extracted_rule: str = Field(description="Context-enriched, self-contained description")


class ExtractionResult(BaseModel):
    """Output of Stage 1: all rules extracted from a single spec chunk."""

    spec_chunk_id: str = Field(description="UUID of the source spec_documents row")
    era: str
    subsystem: str
    rules: list[ExtractedRule]


# === Stage 2: Semantic Search Candidates ===


class SearchCandidate(BaseModel):
    """A candidate entity found by semantic search."""

    entity_type: str = Field(description="code_chunk, github_issue, github_pr")
    entity_id: str
    title: str
    content_preview: str = Field(description="First 500 chars")
    similarity: float


# === Stage 3: Link Evaluation ===


class LinkDecision(BaseModel):
    """LLM's evaluation of whether a candidate is related to a rule."""

    is_linked: bool = Field(description="Whether this candidate is genuinely related")
    relationship: RelationshipType | None = Field(
        default=None, description="Relationship type if linked"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in the link"
    )
    notes: str | None = Field(default=None, description="Brief explanation")


# === Stage 4: Gap Detection + Test Specification ===


class GapEntry(BaseModel):
    """A divergence between spec and Haskell implementation."""

    spec_says: str
    haskell_does: str
    delta: str
    implications: str


class ProposedTest(BaseModel):
    """A proposed test specification for a rule."""

    test_type: TestType
    test_name: str
    description: str
    hypothesis_strategy: str | None = Field(
        default=None, description="For property tests: generators, value ranges, invariants"
    )
    priority: Priority


class AnalysisResult(BaseModel):
    """Output of Stage 4: gap analysis + proposed tests for a single rule."""

    gap: GapEntry | None = Field(default=None, description="If divergence found")
    proposed_tests: list[ProposedTest] = Field(default_factory=list)
