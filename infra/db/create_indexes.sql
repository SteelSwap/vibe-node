-- BM25 Indexes (pg_search) on text columns + filter columns for pushdown
DROP INDEX IF EXISTS idx_spec_documents_bm25;
CREATE INDEX idx_spec_documents_bm25 ON spec_documents
USING bm25 (id, content_plain, document_title, section_title, subsection_title, era, source_repo, chunk_type)
WITH (key_field='id');

DROP INDEX IF EXISTS idx_code_chunks_bm25;
CREATE INDEX idx_code_chunks_bm25 ON code_chunks
USING bm25 (id, content, embed_text, function_name, module_name, era, repo, release_tag)
WITH (key_field='id');

DROP INDEX IF EXISTS idx_github_issues_bm25;
CREATE INDEX idx_github_issues_bm25 ON github_issues
USING bm25 (id, content_combined, title, repo, state)
WITH (key_field='id');

DROP INDEX IF EXISTS idx_github_issue_comments_bm25;
CREATE INDEX idx_github_issue_comments_bm25 ON github_issue_comments
USING bm25 (id, body, repo)
WITH (key_field='id');

DROP INDEX IF EXISTS idx_github_pull_requests_bm25;
CREATE INDEX idx_github_pull_requests_bm25 ON github_pull_requests
USING bm25 (id, content_combined, title, repo, state)
WITH (key_field='id');

DROP INDEX IF EXISTS idx_github_pr_comments_bm25;
CREATE INDEX idx_github_pr_comments_bm25 ON github_pr_comments
USING bm25 (id, body, repo)
WITH (key_field='id');

-- HNSW Vector Indexes (pgvector, cosine distance)
CREATE INDEX IF NOT EXISTS idx_spec_documents_hnsw ON spec_documents USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_code_chunks_hnsw ON code_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_github_issues_hnsw ON github_issues USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_github_issue_comments_hnsw ON github_issue_comments USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_github_pull_requests_hnsw ON github_pull_requests USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_github_pr_comments_hnsw ON github_pr_comments USING hnsw (embedding vector_cosine_ops);
