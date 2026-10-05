from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import Session

from caching_service.app import app
from caching_service.database import get_session
from caching_service.models import Base


@pytest.fixture
def engine():
    # In-memory SQLite keeps tests fast and dependency-free; the models use only
    # portable types, so they behave the same on PostgreSQL.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()
