"""Payload generation with cached transformer results."""

import asyncio
import hashlib
import uuid
from itertools import chain

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from caching_service.models import Base, CachedTransformation, Payload
from caching_service.transformer import TransformerPool

OUTPUT_SEPARATOR = ", "


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def interleave(list_1: list[str], list_2: list[str]) -> list[str]:
    return list(chain.from_iterable(zip(list_1, list_2, strict=True)))


async def _insert_ignoring_duplicates(
    session: AsyncSession, model: type[Base], rows: list[dict[str, object]]
) -> None:
    """Insert rows, skipping those another request has stored in the meantime."""
    if not rows:
        return
    # ON CONFLICT DO NOTHING is the only race-free way to do this; SQLite (used in
    # tests) has its own spelling of it.
    insert = sqlite.insert if session.bind.dialect.name == "sqlite" else postgresql.insert
    await session.execute(insert(model).values(rows).on_conflict_do_nothing())


async def _transform_all(
    session: AsyncSession, sources: list[str], pool: TransformerPool
) -> dict[str, str]:
    """Return source -> transformed, calling the transformer once per string not yet cached."""
    hashes = {source: sha256_hex(source) for source in set(sources)}

    rows = await session.scalars(
        select(CachedTransformation).where(CachedTransformation.source_hash.in_(hashes.values()))
    )
    result = {row.source: row.transformed for row in rows}

    # Release the connection before the slow external calls: holding it for their
    # whole duration would exhaust the pool under load while it sits idle.
    await session.rollback()

    missing = list(hashes.keys() - result.keys())
    transformed = await asyncio.gather(*(pool.transform(source) for source in missing))
    result.update(zip(missing, transformed, strict=True))

    await _insert_ignoring_duplicates(
        session,
        CachedTransformation,
        [
            {"source_hash": hashes[source], "source": source, "transformed": text}
            for source, text in zip(missing, transformed, strict=True)
        ],
    )
    return result


async def create_payload(
    session: AsyncSession, list_1: list[str], list_2: list[str], pool: TransformerPool
) -> uuid.UUID:
    """Store the payload for the two lists and return its id; identical payloads share one id."""
    interleaved = interleave(list_1, list_2)
    transformed = await _transform_all(session, interleaved, pool)
    output = OUTPUT_SEPARATOR.join(transformed[source] for source in interleaved)
    fingerprint = sha256_hex(output)

    await _insert_ignoring_duplicates(
        session, Payload, [{"id": uuid.uuid4(), "fingerprint": fingerprint, "output": output}]
    )
    # Our row may have lost the race to an identical one, so read the id back.
    payload_id = await session.scalar(select(Payload.id).where(Payload.fingerprint == fingerprint))
    await session.commit()
    return payload_id


async def get_payload_output(session: AsyncSession, payload_id: uuid.UUID) -> str | None:
    return await session.scalar(select(Payload.output).where(Payload.id == payload_id))
