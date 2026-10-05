import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from caching_service.app import app
from caching_service.database import get_session
from caching_service.models import Base
from caching_service.routers import get_pool
from caching_service.transformer import TransformerPool


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


@pytest.fixture
def engine() -> AsyncEngine:
    # In-memory SQLite keeps tests fast and dependency-free; the models use only
    # portable types, so they behave the same on PostgreSQL.
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    async def create_tables() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    return engine


@pytest.fixture
async def session(engine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session


@pytest.fixture
def transformer() -> CountingTransformer:
    return CountingTransformer()


@pytest.fixture
def pool(transformer) -> TransformerPool:
    return TransformerPool(transformer, max_concurrency=10)


@pytest.fixture(autouse=True)
def overrides(engine, pool) -> Iterator[None]:
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
