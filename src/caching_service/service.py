"""Payload generation with cached transformer results."""

import hashlib
import uuid
from collections.abc import Callable, Iterable
from itertools import chain

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caching_service.models import CachedTransformation, Payload
from caching_service.transformer import transform

OUTPUT_SEPARATOR = ", "


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def interleave(list_1: list[str], list_2: list[str]) -> list[str]:
    return list(chain.from_iterable(zip(list_1, list_2, strict=True)))


def _transform_all(
    session: Session, sources: Iterable[str], transformer: Callable[[str], str]
) -> dict[str, str]:
    """Return source -> transformed, calling the transformer once per string not yet cached."""
    unique = set(sources)
    hashes = {source: sha256_hex(source) for source in unique}

    rows = session.scalars(
        select(CachedTransformation).where(CachedTransformation.source_hash.in_(hashes.values()))
    )
    cached = {row.source: row.transformed for row in rows}

    for source in unique - cached.keys():
        cached[source] = transformer(source)
        session.add(
            CachedTransformation(
                source_hash=hashes[source], source=source, transformed=cached[source]
            )
        )
    return cached


def create_payload(
    session: Session,
    list_1: list[str],
    list_2: list[str],
    transformer: Callable[[str], str] = transform,
) -> uuid.UUID:
    """Store the payload for the two lists and return its id; identical payloads share one id."""
    interleaved = interleave(list_1, list_2)
    transformed = _transform_all(session, interleaved, transformer)
    output = OUTPUT_SEPARATOR.join(transformed[source] for source in interleaved)
    fingerprint = sha256_hex(output)

    existing = session.scalar(select(Payload.id).where(Payload.fingerprint == fingerprint))
    if existing is not None:
        session.commit()  # still persist any newly cached transformations
        return existing

    payload = Payload(fingerprint=fingerprint, output=output)
    try:
        session.add(payload)
        session.commit()
    except IntegrityError:
        # A concurrent request stored the same payload or cache entry first. Their
        # cache rows are equivalent to ours, so retry once without re-adding them.
        session.rollback()
        return _find_or_create_payload(session, fingerprint, output)
    return payload.id


def _find_or_create_payload(session: Session, fingerprint: str, output: str) -> uuid.UUID:
    existing = session.scalar(select(Payload.id).where(Payload.fingerprint == fingerprint))
    if existing is not None:
        return existing
    payload = Payload(fingerprint=fingerprint, output=output)
    session.add(payload)
    session.commit()
    return payload.id


def get_payload_output(session: Session, payload_id: uuid.UUID) -> str | None:
    return session.scalar(select(Payload.output).where(Payload.id == payload_id))
