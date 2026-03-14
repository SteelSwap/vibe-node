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
-- spec_documents: parsed specification content with version history
-- The same spec file may have multiple rows at different commits,
-- giving us a full historical record of how each spec evolved.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spec_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title               VARCHAR(512)  NOT NULL,
    source_repo         VARCHAR(256)  NOT NULL,
    source_path         VARCHAR(1024) NOT NULL,
    era                 VARCHAR(32)   NOT NULL,
    spec_version        VARCHAR(64)   NOT NULL,
    commit_hash         VARCHAR(40)   NOT NULL,
    commit_date         TIMESTAMPTZ   NOT NULL,
    published_date      TIMESTAMPTZ,
    content_markdown    TEXT          NOT NULL,
    content_plain       TEXT          NOT NULL,
    embedding           vector(1536),
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
CREATE INDEX IF NOT EXISTS idx_spec_documents_commit_hash
    ON spec_documents (commit_hash);
CREATE INDEX IF NOT EXISTS idx_spec_documents_commit_date
    ON spec_documents (commit_date);

-- ---------------------------------------------------------------------------
-- code_chunks: parsed Haskell/Agda source from reference repos
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
    embedding       vector(1536),
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
-- github_issues: issue content with full discussion threads
-- content_combined includes title + body + all comments for search
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
    updated_at        TIMESTAMPTZ,
    author            VARCHAR(128)  NOT NULL,
    comment_count     INTEGER       NOT NULL DEFAULT 0,
    content_combined  TEXT          NOT NULL,
    embedding         vector(1536),
    linked_prs        VARCHAR[],
    metadata          JSONB,

    CONSTRAINT uq_github_issues_identity
        UNIQUE (repo, issue_number)
);

CREATE INDEX IF NOT EXISTS idx_github_issues_repo
    ON github_issues (repo);
CREATE INDEX IF NOT EXISTS idx_github_issues_state
    ON github_issues (state);

-- ---------------------------------------------------------------------------
-- github_issue_comments: individual comments for fine-grained search
-- Each comment is separately embedded so we can find specific insights
-- within long discussion threads.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS github_issue_comments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id        UUID          NOT NULL REFERENCES github_issues(id) ON DELETE CASCADE,
    repo            VARCHAR(256)  NOT NULL,
    issue_number    INTEGER       NOT NULL,
    comment_id      BIGINT        NOT NULL,
    author          VARCHAR(128)  NOT NULL,
    body            TEXT          NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL,
    updated_at      TIMESTAMPTZ,
    embedding       vector(1536),
    metadata        JSONB,

    CONSTRAINT uq_github_comments_identity
        UNIQUE (repo, comment_id)
);

CREATE INDEX IF NOT EXISTS idx_github_comments_issue_id
    ON github_issue_comments (issue_id);
CREATE INDEX IF NOT EXISTS idx_github_comments_repo
    ON github_issue_comments (repo);
CREATE INDEX IF NOT EXISTS idx_github_comments_issue_number
    ON github_issue_comments (repo, issue_number);

-- ---------------------------------------------------------------------------
-- github_pull_requests: PR content with review discussions
-- PRs contain code review decisions, design rationale, and implementation
-- context that isn't captured in issues.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS github_pull_requests (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo                    VARCHAR(256)  NOT NULL,
    pr_number               INTEGER       NOT NULL,
    title                   VARCHAR(512)  NOT NULL,
    body                    TEXT,
    state                   VARCHAR(16)   NOT NULL,
    merged                  BOOLEAN       NOT NULL DEFAULT FALSE,
    labels                  VARCHAR[],
    created_at              TIMESTAMPTZ   NOT NULL,
    closed_at               TIMESTAMPTZ,
    merged_at               TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ,
    author                  VARCHAR(128)  NOT NULL,
    merge_commit_sha        VARCHAR(40),
    base_branch             VARCHAR(256)  NOT NULL,
    head_branch             VARCHAR(256)  NOT NULL,
    comment_count           INTEGER       NOT NULL DEFAULT 0,
    review_comment_count    INTEGER       NOT NULL DEFAULT 0,
    content_combined        TEXT          NOT NULL,
    embedding               vector(1536),
    linked_issues           VARCHAR[],
    metadata                JSONB,

    CONSTRAINT uq_github_prs_identity
        UNIQUE (repo, pr_number)
);

CREATE INDEX IF NOT EXISTS idx_github_prs_repo
    ON github_pull_requests (repo);
CREATE INDEX IF NOT EXISTS idx_github_prs_state
    ON github_pull_requests (state);
CREATE INDEX IF NOT EXISTS idx_github_prs_merged
    ON github_pull_requests (merged);

-- ---------------------------------------------------------------------------
-- github_pr_comments: individual comments and review comments on PRs
-- Includes general comments, review summaries, and line-level review comments
-- with file path and diff context.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS github_pr_comments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pr_id           UUID          NOT NULL REFERENCES github_pull_requests(id) ON DELETE CASCADE,
    repo            VARCHAR(256)  NOT NULL,
    pr_number       INTEGER       NOT NULL,
    comment_id      BIGINT        NOT NULL,
    comment_type    VARCHAR(32)   NOT NULL,
    author          VARCHAR(128)  NOT NULL,
    body            TEXT          NOT NULL,
    file_path       VARCHAR(1024),
    diff_hunk       TEXT,
    created_at      TIMESTAMPTZ   NOT NULL,
    updated_at      TIMESTAMPTZ,
    embedding       vector(1536),
    metadata        JSONB,

    CONSTRAINT uq_github_pr_comments_identity
        UNIQUE (repo, comment_id, comment_type)
);

CREATE INDEX IF NOT EXISTS idx_github_pr_comments_pr_id
    ON github_pr_comments (pr_id);
CREATE INDEX IF NOT EXISTS idx_github_pr_comments_repo
    ON github_pr_comments (repo);
CREATE INDEX IF NOT EXISTS idx_github_pr_comments_pr_number
    ON github_pr_comments (repo, pr_number);
