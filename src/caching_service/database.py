"""Async database engine and session wiring."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from caching_service.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    # Created lazily so that importing the application (e.g. in tests) never
    # requires a reachable database.
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session
