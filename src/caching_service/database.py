"""Database engine and session wiring."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from caching_service.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # Created lazily so that importing the application (e.g. in tests) never
    # requires a reachable database.
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
