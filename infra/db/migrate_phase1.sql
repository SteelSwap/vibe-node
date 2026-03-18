-- Phase 1: Cross-referencing infrastructure
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- spec_sections: atomic unit of spec traceability.
-- One row = one spec rule, definition, equation, or type declaration.
-- More granular than spec_documents (which are optimized for search).
-- Produced by the PydanticAI rule extraction pipeline.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spec_sections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_chunk_id   UUID REFERENCES spec_documents(id) ON DELETE SET NULL,
    section_id      TEXT NOT NULL,
    title           TEXT NOT NULL,
    section_type    TEXT NOT NULL,
    era             TEXT NOT NULL,
    subsystem       TEXT NOT NULL,
    verbatim        TEXT NOT NULL,
    extracted_rule  TEXT NOT NULL,
    embedding       vector(1536),
    metadata        JSONB,
    UNIQUE (section_id)
);

CREATE INDEX IF NOT EXISTS idx_spec_sections_era
    ON spec_sections (era);
CREATE INDEX IF NOT EXISTS idx_spec_sections_subsystem
    ON spec_sections (subsystem);
CREATE INDEX IF NOT EXISTS idx_spec_sections_type
    ON spec_sections (section_type);

-- ---------------------------------------------------------------------------
-- cross_references: links any two entities in the knowledge base.
-- 10 relationship types borrowed from W3C PROV-O, Dublin Core, SPDX, OSLC RM.
-- Canonical direction stored; inverses computed at query time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cross_references (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL,
    source_id       UUID NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       UUID NOT NULL,
    relationship    TEXT NOT NULL,
    confidence      FLOAT DEFAULT 1.0,
    notes           TEXT,
    created_by      TEXT DEFAULT 'manual',
    UNIQUE (source_type, source_id, target_type, target_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_xref_source
    ON cross_references (source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_xref_target
    ON cross_references (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_xref_relationship
    ON cross_references (relationship);

-- ---------------------------------------------------------------------------
-- test_specifications: test knowledge base.
-- Describes *what* should be tested and *how* for each spec rule.
-- Not a state tracker — does not record whether tests pass/fail.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_specifications (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_section_id      UUID REFERENCES spec_sections(id) ON DELETE SET NULL,
    subsystem            TEXT NOT NULL,
    test_type            TEXT NOT NULL,
    test_name            TEXT NOT NULL,
    description          TEXT NOT NULL,
    hypothesis_strategy  TEXT,
    priority             TEXT NOT NULL,
    phase                TEXT NOT NULL,
    metadata             JSONB
);

CREATE INDEX IF NOT EXISTS idx_test_specs_subsystem
    ON test_specifications (subsystem);
CREATE INDEX IF NOT EXISTS idx_test_specs_phase
    ON test_specifications (phase);
CREATE INDEX IF NOT EXISTS idx_test_specs_priority
    ON test_specifications (priority);

-- ---------------------------------------------------------------------------
-- gap_analysis: structured spec-vs-implementation divergences.
-- Queryable version of docs/specs/gap-analysis.md entries.
-- Created by the PydanticAI pipeline or manually during research.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gap_analysis (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spec_section_id   UUID REFERENCES spec_sections(id) ON DELETE SET NULL,
    subsystem         TEXT NOT NULL,
    era               TEXT NOT NULL,
    spec_says         TEXT NOT NULL,
    haskell_does      TEXT NOT NULL,
    delta             TEXT NOT NULL,
    implications      TEXT NOT NULL,
    discovered_during TEXT NOT NULL,
    code_chunk_id     UUID REFERENCES code_chunks(id) ON DELETE SET NULL,
    embedding         vector(1536),
    metadata          JSONB
);

CREATE INDEX IF NOT EXISTS idx_gap_analysis_subsystem
    ON gap_analysis (subsystem);
CREATE INDEX IF NOT EXISTS idx_gap_analysis_era
    ON gap_analysis (era);
