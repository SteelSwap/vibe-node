"""SQLModel definitions for the vibe-node knowledge base.

These models define the ParadeDB schema and provide validation for all
data flowing into the database. They serve as the single source of truth
for the schema — the init script, ingestion pipelines, and search queries
all derive from these definitions.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import ARRAY, VARCHAR
from sqlmodel import Column, Field, SQLModel, Text


class SpecDocument(SQLModel, table=True):
    """Converted spec content chunked by section, definition, or rule."""

    __tablename__ = "spec_documents"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(max_length=512)
    source_repo: str = Field(max_length=256, index=True)
    source_path: str = Field(max_length=1024)
    era: str = Field(max_length=32, index=True)
    spec_version: str = Field(max_length=64)
    published_date: datetime | None = Field(default=None)
    content_markdown: str = Field(sa_column=Column(Text))
    content_plain: str = Field(sa_column=Column(Text))
    chunk_type: str = Field(max_length=32, index=True)
    parent_document_id: uuid.UUID | None = Field(default=None, foreign_key="spec_documents.id")
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))
    content_hash: str = Field(max_length=64, index=True)


class CodeChunk(SQLModel, table=True):
    """Function-level Haskell source indexed per release."""

    __tablename__ = "code_chunks"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo: str = Field(max_length=256, index=True)
    release_tag: str = Field(max_length=64, index=True)
    commit_hash: str = Field(max_length=40)
    commit_date: datetime
    file_path: str = Field(max_length=1024)
    module_name: str = Field(max_length=512, index=True)
    function_name: str = Field(max_length=256)
    line_start: int
    line_end: int
    content: str = Field(sa_column=Column(Text))
    signature: str | None = Field(default=None, sa_column=Column(Text))
    era: str = Field(max_length=32, index=True)
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))


class GitHubIssue(SQLModel, table=True):
    """GitHub issues for historical bug/ambiguity awareness."""

    __tablename__ = "github_issues"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repo: str = Field(max_length=256, index=True)
    issue_number: int
    title: str = Field(max_length=512)
    body: str | None = Field(default=None, sa_column=Column(Text))
    state: str = Field(max_length=16, index=True)
    labels: list[str] = Field(default_factory=list, sa_column=Column(ARRAY(VARCHAR)))
    created_at: datetime
    closed_at: datetime | None = Field(default=None)
    author: str = Field(max_length=128)
    content_combined: str = Field(sa_column=Column(Text))
    metadata_: dict | None = Field(default=None, sa_column=Column("metadata", JSON))
