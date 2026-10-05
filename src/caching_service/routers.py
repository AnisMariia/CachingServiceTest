"""HTTP endpoints."""

import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service import service
from caching_service.config import get_settings
from caching_service.database import get_session
from caching_service.schemas import PayloadCreate, PayloadCreated, PayloadRead
from caching_service.transformer import TransformerPool, transform

router = APIRouter(prefix="/payload", tags=["payload"])


@lru_cache
def get_pool() -> TransformerPool:
    # One pool per process: the concurrency limit and in-flight sharing only work
    # if every request goes through the same instance.
    return TransformerPool(transform, get_settings().transformer_concurrency)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
PoolDep = Annotated[TransformerPool, Depends(get_pool)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_payload(
    body: PayloadCreate, session: SessionDep, pool: PoolDep
) -> PayloadCreated:
    return PayloadCreated(
        id=await service.create_payload(session, body.list_1, body.list_2, pool)
    )


@router.get("/{payload_id}")
async def read_payload(payload_id: uuid.UUID, session: SessionDep) -> PayloadRead:
    output = await service.get_payload_output(session, payload_id)
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payload not found")
    return PayloadRead(output=output)
