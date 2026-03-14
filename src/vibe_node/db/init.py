"""Database initialization script.

Creates all tables and enables required PostgreSQL extensions (pgvector, pg_search).
Idempotent — safe to run multiple times.

Usage:
    uv run python -m vibe_node.db.init
    # or via CLI (future):
    vibe-node db init
"""

import asyncio

from sqlalchemy import text
from sqlmodel import SQLModel

from vibe_node.db.engine import get_engine

# Import models so SQLModel registers them
from vibe_node.db.models import CodeChunk, GitHubIssue, SpecDocument  # noqa: F401

# SQL for extensions and columns that SQLModel/SQLAlchemy can't express
POST_CREATE_SQL = [
    # Enable extensions
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_search",
    # Add vector embedding columns (pgvector type not natively supported by SQLModel)
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'spec_documents' AND column_name = 'embedding'
        ) THEN
            ALTER TABLE spec_documents ADD COLUMN embedding vector(768);
        END IF;
    END $$
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'code_chunks' AND column_name = 'embedding'
        ) THEN
            ALTER TABLE code_chunks ADD COLUMN embedding vector(768);
        END IF;
    END $$
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'github_issues' AND column_name = 'embedding'
        ) THEN
            ALTER TABLE github_issues ADD COLUMN embedding vector(768);
        END IF;
    END $$
    """,
    # Unique constraints
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_code_chunks_release'
        ) THEN
            ALTER TABLE code_chunks
            ADD CONSTRAINT uq_code_chunks_release
            UNIQUE (repo, release_tag, file_path, function_name, line_start);
        END IF;
    END $$
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_github_issues_repo_number'
        ) THEN
            ALTER TABLE github_issues
            ADD CONSTRAINT uq_github_issues_repo_number
            UNIQUE (repo, issue_number);
        END IF;
    END $$
    """,
]


async def init_db(url: str | None = None) -> None:
    """Initialize the database: create tables, enable extensions, add vector columns."""
    engine = get_engine(url) if url else get_engine()

    async with engine.begin() as conn:
        # Create all SQLModel tables
        await conn.run_sync(SQLModel.metadata.create_all)

        # Run post-creation SQL for extensions and vector columns
        for sql in POST_CREATE_SQL:
            await conn.execute(text(sql))

    await engine.dispose()
    print("Database initialized successfully.")


if __name__ == "__main__":
    asyncio.run(init_db())
