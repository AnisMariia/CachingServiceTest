"""Alembic environment: uses the application's settings and models."""

from alembic import context
from sqlalchemy import create_engine

from caching_service.config import get_settings
from caching_service.models import Base


def run_migrations() -> None:
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
