"""FastAPI application entry point."""

from fastapi import FastAPI

from caching_service.routers import router

# The schema is managed by Alembic (`alembic upgrade head`), not created here.
app = FastAPI(title="Caching service")
app.include_router(router)
