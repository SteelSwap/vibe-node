"""Async database engine configuration."""

import os

from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://vibenode:vibenode@localhost:5432/vibenode",
)


def get_engine(url: str = DATABASE_URL):
    """Create an async SQLAlchemy engine."""
    return create_async_engine(url, echo=False)
