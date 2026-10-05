"""FastAPI application entry point."""

import logging

from fastapi import FastAPI

from caching_service.config import get_settings
from caching_service.routers import router

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# The schema is managed by Alembic (`alembic upgrade head`), not created here.
app = FastAPI(title="Caching service")
app.include_router(router)
