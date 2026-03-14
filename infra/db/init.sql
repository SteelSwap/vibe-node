-- =============================================================================
-- ParadeDB initialization script for vibe-node spec intelligence database
-- Runs via /docker-entrypoint-initdb.d/ on first container startup
-- Idempotent: safe to re-run without data loss
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

-- ---------------------------------------------------------------------------
-- spec_documents: parsed specification content (Shelley formal spec, CIPs, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spec_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               VARCHAR(512)  NOT NULL,
    source_repo         VARCHAR(256)  NOT NULL,
    source_path         VARCHAR(1024) NOT NULL,
    era                 VARCHAR(32)   NOT NULL,
    spec_version        VARCHAR(64)   NOT NULL,
    published_date      TIMESTAMPTZ,
    content_markdown    TEXT          NOT NULL,
    content_plain       TEXT          NOT NULL,
    embedding           vector(768),
    chunk_type          VARCHAR(32)   NOT NULL,
    parent_document_id  UUID REFERENCES spec_documents(id),
    metadata            JSONB,
    content_hash        VARCHAR(64)   NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_spec_documents_era
    ON spec_documents (era);
CREATE INDEX IF NOT EXISTS idx_spec_documents_source_repo
    ON spec_documents (source_repo);
CREATE INDEX IF NOT EXISTS idx_spec_documents_chunk_type
    ON spec_documents (chunk_type);
CREATE INDEX IF NOT EXISTS idx_spec_documents_content_hash
    ON spec_documents (content_hash);

-- ---------------------------------------------------------------------------
-- code_chunks: parsed Haskell source from reference repos
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS code_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo            VARCHAR(256)  NOT NULL,
    release_tag     VARCHAR(64)   NOT NULL,
    commit_hash     VARCHAR(40)   NOT NULL,
    commit_date     TIMESTAMPTZ   NOT NULL,
    file_path       VARCHAR(1024) NOT NULL,
    module_name     VARCHAR(512)  NOT NULL,
    function_name   VARCHAR(256)  NOT NULL,
    line_start      INTEGER       NOT NULL,
    line_end        INTEGER       NOT NULL,
    content         TEXT          NOT NULL,
    signature       TEXT,
    embedding       vector(768),
    era             VARCHAR(32)   NOT NULL,
    metadata        JSONB,

    CONSTRAINT uq_code_chunks_identity
        UNIQUE (repo, release_tag, file_path, function_name, line_start)
);

CREATE INDEX IF NOT EXISTS idx_code_chunks_repo
    ON code_chunks (repo);
CREATE INDEX IF NOT EXISTS idx_code_chunks_release_tag
    ON code_chunks (release_tag);
CREATE INDEX IF NOT EXISTS idx_code_chunks_era
    ON code_chunks (era);
CREATE INDEX IF NOT EXISTS idx_code_chunks_module_name
    ON code_chunks (module_name);

-- ---------------------------------------------------------------------------
-- github_issues: issue/PR content from reference repos
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS github_issues (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo              VARCHAR(256)  NOT NULL,
    issue_number      INTEGER       NOT NULL,
    title             VARCHAR(512)  NOT NULL,
    body              TEXT,
    state             VARCHAR(16)   NOT NULL,
    labels            VARCHAR[],
    created_at        TIMESTAMPTZ   NOT NULL,
    closed_at         TIMESTAMPTZ,
    author            VARCHAR(128)  NOT NULL,
    content_combined  TEXT          NOT NULL,
    embedding         vector(768),
    metadata          JSONB,

    CONSTRAINT uq_github_issues_identity
        UNIQUE (repo, issue_number)
);

CREATE INDEX IF NOT EXISTS idx_github_issues_repo
    ON github_issues (repo);
CREATE INDEX IF NOT EXISTS idx_github_issues_state
    ON github_issues (state);
