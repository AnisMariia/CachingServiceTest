"""Payload generation with cached transformer results."""

import asyncio
import hashlib
import logging
import uuid
from functools import partial
from itertools import chain

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from caching_service.models import Base, CachedTransformation, Payload
from caching_service.transformer import TransformerPool

logger = logging.getLogger(__name__)

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
    logger.debug("Inserting %d row(s) into %s", len(rows), model.__tablename__)
    # ON CONFLICT DO NOTHING is the only race-free way to do this.
    await session.execute(insert(model).values(rows).on_conflict_do_nothing())


async def _store_transformation(
    bind: AsyncEngine | AsyncConnection, source_hash: str, source: str, transformed: str
) -> None:
    async with async_sessionmaker(bind, expire_on_commit=False)() as session:
        await _insert_ignoring_duplicates(
            session,
            CachedTransformation,
            [{"source_hash": source_hash, "source": source, "transformed": transformed}],
        )
        await session.commit()


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

    missing = sorted(hashes.keys() - result.keys(), key=hashes.__getitem__)
    logger.info(
        "Cache lookup: %d unique string(s), %d cached (transformer NOT called), %d missing",
        len(hashes),
        len(result),
        len(missing),
    )
    for source in result:
        logger.debug("Cache hit for %s, transformer skipped", hashes[source][:8])

    # Each string is stored by its own transformer call, in a session of its own, as
    # soon as it is transformed. A request that finds the string in flight therefore
    # never sees a gap before the row exists, and one failure loses none of the
    # other strings' results.
    bind = session.bind
    outcomes = await asyncio.gather(
        *(
            pool.transform(source, partial(_store_transformation, bind, hashes[source], source))
            for source in missing
        ),
        return_exceptions=True,
    )
    failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    if failures:
        logger.warning("%d of %d transformer call(s) failed", len(failures), len(missing))
        raise failures[0]
    result.update(zip(missing, outcomes, strict=True))
    return result


async def store_payload(
    session: AsyncSession, list_1: list[str], list_2: list[str], pool: TransformerPool
) -> tuple[uuid.UUID, bool]:
    """Store the payload for the two lists; return its id and whether this call created it.

    Identical payloads share one id, so a repeat returns the existing id with False.
    """
    interleaved = interleave(list_1, list_2)
    logger.info("Creating payload from %d string(s)", len(interleaved))
    transformed = await _transform_all(session, interleaved, pool)
    output = OUTPUT_SEPARATOR.join(transformed[source] for source in interleaved)
    fingerprint = sha256_hex(output)
    logger.debug("Payload fingerprint %s", fingerprint[:8])

    # RETURNING yields a row only if ours was inserted, i.e. did not lose to an identical one.
    inserted_id = await session.scalar(
        insert(Payload)
        .values(id=uuid.uuid4(), fingerprint=fingerprint, output=output)
        .on_conflict_do_nothing()
        .returning(Payload.id)
    )
    created = inserted_id is not None
    payload_id = inserted_id or await session.scalar(
        select(Payload.id).where(Payload.fingerprint == fingerprint)
    )
    logger.info(
        "Payload %s with id %s", "created" if created else "already existed", payload_id
    )
    assert payload_id is not None  # the row exists: we inserted it or lost the race
    await session.commit()
    return payload_id, created


async def create_payload(
    session: AsyncSession, list_1: list[str], list_2: list[str], pool: TransformerPool
) -> uuid.UUID:
    """Like store_payload, for callers that only need the id."""
    payload_id, _ = await store_payload(session, list_1, list_2, pool)
    return payload_id


async def get_payload_output(session: AsyncSession, payload_id: uuid.UUID) -> str | None:
    return await session.scalar(select(Payload.output).where(Payload.id == payload_id))
