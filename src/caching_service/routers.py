"""HTTP endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from caching_service import service
from caching_service.database import get_session
from caching_service.schemas import PayloadCreate, PayloadCreated, PayloadRead

router = APIRouter(prefix="/payload", tags=["payload"])

SessionDep = Annotated[Session, Depends(get_session)]


# Plain `def` endpoints: the transformer and the database driver are blocking,
# so FastAPI runs them in a thread pool instead of stalling the event loop.
@router.post("", status_code=status.HTTP_201_CREATED)
def create_payload(body: PayloadCreate, session: SessionDep) -> PayloadCreated:
    return PayloadCreated(id=service.create_payload(session, body.list_1, body.list_2))


@router.get("/{payload_id}")
def read_payload(payload_id: uuid.UUID, session: SessionDep) -> PayloadRead:
    output = service.get_payload_output(session, payload_id)
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payload not found")
    return PayloadRead(output=output)
