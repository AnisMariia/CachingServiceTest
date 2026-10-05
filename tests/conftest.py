import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from caching_service.app import app
from caching_service.config import get_settings
from caching_service.database import get_session
from caching_service.routers import get_pool
from caching_service.transformer import TransformerPool

ROOT = Path(__file__).resolve().parent.parent

# The reaper container needs docker.sock mounted, which Docker Desktop on macOS refuses;
# the `with` block below stops the database container anyway.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


class CountingTransformer:
    """Upper-cases like the real one, recording calls and optionally taking some time."""

    def __init__(self, delay: float = 0, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.delay = delay
        self.fail_on = fail_on
        self.running = 0
        self.max_running = 0

    async def __call__(self, text: str) -> str:
        self.calls.append(text)
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await asyncio.sleep(self.delay)
            if text == self.fail_on:
                raise RuntimeError("transformer unavailable")
            return text.upper()
        finally:
            self.running -= 1


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A throwaway PostgreSQL with the schema built by the real migrations."""
    with PostgresContainer("postgres:17", driver="psycopg") as postgres:
        url = postgres.get_connection_url()
        # Alembic's env.py reads the URL from the settings, like the application.
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    # NullPool: connections must not outlive the event loop of the test that made them.
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE payloads, cached_transformations"))
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def transformer() -> CountingTransformer:
    return CountingTransformer()


@pytest.fixture
def pool(transformer: CountingTransformer) -> TransformerPool:
    return TransformerPool(transformer, max_concurrency=10)


@pytest.fixture(autouse=True)
def overrides(engine: AsyncEngine, pool: TransformerPool) -> Iterator[None]:
    async def session_override() -> AsyncIterator[AsyncSession]:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_pool] = lambda: pool
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def sync_client() -> TestClient:
    """For the CLI, which is synchronous and talks to the app over blocking httpx."""
    return TestClient(app)
