"""Search configuration registry.

Maps entity types to their database tables, searchable columns,
and filter columns. Used by search templates and MCP tools.
"""

SEARCH_CONFIG: dict[str, dict] = {
    # Key is "spec_doc" to match the MCP spec; "spec" is reserved for
    # Phase 1's spec_sections table.
    "spec_doc": {
        "table": "spec_documents",
        "text_column": "content_plain",
        "bm25_columns": ["content_plain", "document_title", "section_title", "subsection_title"],
        "preview_column": "content_plain",
        "title_column": "document_title",
        "id_column": "id",
        "filter_columns": {"era": "era", "repo": "source_repo"},
    },
    "code": {
        "table": "code_chunks",
        "text_column": "embed_text",
        "bm25_columns": ["content", "embed_text", "function_name", "module_name"],
        "preview_column": "content",
        "title_column": "function_name",
        "id_column": "id",
        "filter_columns": {"era": "era", "repo": "repo", "release_tag": "release_tag"},
    },
    "issue": {
        "table": "github_issues",
        "text_column": "content_combined",
        "bm25_columns": ["content_combined", "title"],
        "preview_column": "content_combined",
        "title_column": "title",
        "id_column": "id",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "issue_comment": {
        "table": "github_issue_comments",
        "text_column": "body",
        "bm25_columns": ["body"],
        "preview_column": "body",
        "title_column": None,
        "id_column": "id",
        "filter_columns": {"repo": "repo"},
    },
    "pr": {
        "table": "github_pull_requests",
        "text_column": "content_combined",
        "bm25_columns": ["content_combined", "title"],
        "preview_column": "content_combined",
        "title_column": "title",
        "id_column": "id",
        "filter_columns": {"repo": "repo", "state": "state"},
    },
    "pr_comment": {
        "table": "github_pr_comments",
        "text_column": "body",
        "bm25_columns": ["body"],
        "preview_column": "body",
        "title_column": None,
        "id_column": "id",
        "filter_columns": {"repo": "repo"},
    },
}


async def get_available_configs(conn) -> dict[str, dict]:
    """Return only configs whose tables exist in the database."""
    result = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing_tables = {row["tablename"] for row in result}
    return {
        name: cfg for name, cfg in SEARCH_CONFIG.items()
        if cfg["table"] in existing_tables
    }
