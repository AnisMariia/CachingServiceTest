"""FastAPI application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from caching_service.config import get_settings
from caching_service.routers import router

logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# The schema is managed by Alembic (`alembic upgrade head`), not created here.
app = FastAPI(title="Caching service")
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    # The default handler echoes the rejected input back; for a lone surrogate in
    # the body that echo cannot be encoded as UTF-8 and turns a 422 into a 500.
    details = [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": details})
