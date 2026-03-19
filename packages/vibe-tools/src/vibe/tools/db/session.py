"""Async database session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vibe_node.db.engine import get_engine


@asynccontextmanager
async def get_session(url: str | None = None) -> AsyncGenerator[AsyncSession]:
    """Yield an async database session."""
    engine = get_engine(url) if url else get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
