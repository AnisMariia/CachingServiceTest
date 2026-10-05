"""Server settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://postgres:postgres@localhost:5432/caching_service"
    )
    # Upper bound on simultaneous calls to the transformer across all requests, so a
    # burst of traffic cannot overload the external service it stands in for.
    transformer_concurrency: int = Field(default=10, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
