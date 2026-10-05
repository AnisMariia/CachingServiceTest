import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from caching_service import service
from caching_service.models import CachedTransformation, Payload
from caching_service.transformer import TransformerPool
from tests.conftest import CountingTransformer


def test_interleave() -> None:
    assert service.interleave(["a", "b"], ["x", "y"]) == ["a", "x", "b", "y"]


def test_interleave_rejects_different_lengths() -> None:
    with pytest.raises(ValueError):
        service.interleave(["a"], ["x", "y"])


async def test_output_is_interleaved_and_transformed(
    session: AsyncSession, pool: TransformerPool
) -> None:
    payload_id = await service.create_payload(session, ["a", "b"], ["x", "y"], pool)

    assert await service.get_payload_output(session, payload_id) == "A, X, B, Y"


async def test_duplicate_strings_are_transformed_once(
    session: AsyncSession, pool: TransformerPool, transformer: CountingTransformer
) -> None:
    await service.create_payload(session, ["a", "a"], ["a", "b"], pool)

    assert sorted(transformer.calls) == ["a", "b"]


async def test_cached_strings_are_not_transformed_again(
    session: AsyncSession, pool: TransformerPool, transformer: CountingTransformer
) -> None:
    await service.create_payload(session, ["a"], ["b"], pool)

    await service.create_payload(session, ["b", "c"], ["a", "a"], pool)

    assert sorted(transformer.calls) == ["a", "b", "c"]


async def test_same_input_reuses_payload_id(
    session: AsyncSession, pool: TransformerPool, transformer: CountingTransformer
) -> None:
    first = await service.create_payload(session, ["a"], ["b"], pool)
    calls_after_first = len(transformer.calls)

    second = await service.create_payload(session, ["a"], ["b"], pool)

    assert first == second
    assert len(transformer.calls) == calls_after_first


async def test_different_input_gets_different_id(
    session: AsyncSession, pool: TransformerPool
) -> None:
    first = await service.create_payload(session, ["a"], ["b"], pool)
    second = await service.create_payload(session, ["b"], ["a"], pool)

    assert first != second


async def test_unknown_payload_returns_none(session: AsyncSession) -> None:
    assert await service.get_payload_output(session, uuid.uuid4()) is None


async def test_transformer_failure_stores_nothing_and_can_be_retried(
    session: AsyncSession,
) -> None:
    transformer = CountingTransformer(fail_on="b")
    pool = TransformerPool(transformer, max_concurrency=10)

    with pytest.raises(RuntimeError):
        await service.create_payload(session, ["a"], ["b"], pool)
    await session.rollback()

    assert await session.scalar(select(func.count()).select_from(Payload)) == 0
    assert await session.scalar(select(func.count()).select_from(CachedTransformation)) == 0
    transformer.fail_on = None
    payload_id = await service.create_payload(session, ["a"], ["b"], pool)

    assert await service.get_payload_output(session, payload_id) == "A, B"


@pytest.mark.parametrize(
    ("list_1", "list_2", "expected"),
    [
        (["a"], [""], "A, "),
        (["ß"], ["日本"], "SS, 日本"),
        (["x" * 10_000], ["y"], "X" * 10_000 + ", Y"),
    ],
    ids=["empty-string", "unicode", "long-string"],
)
async def test_unusual_strings(
    session: AsyncSession,
    pool: TransformerPool,
    list_1: list[str],
    list_2: list[str],
    expected: str,
) -> None:
    payload_id = await service.create_payload(session, list_1, list_2, pool)

    assert await service.get_payload_output(session, payload_id) == expected


async def test_swapped_lists_with_equal_output_share_id(
    session: AsyncSession, pool: TransformerPool
) -> None:
    # Identity is the output text: different inputs producing the same text are one payload.
    first = await service.create_payload(session, ["a, b"], ["c"], pool)
    second = await service.create_payload(session, ["a"], ["b, c"], pool)

    assert first == second


async def test_row_stored_by_another_request_is_kept(
    session: AsyncSession, pool: TransformerPool, transformer: CountingTransformer
) -> None:
    row: dict[str, object] = {
        "source_hash": service.sha256_hex("a"),
        "source": "a",
        "transformed": "A",
    }
    await service._insert_ignoring_duplicates(session, CachedTransformation, [row])
    await session.commit()

    await service._insert_ignoring_duplicates(session, CachedTransformation, [row])
    await session.commit()

    assert await session.scalar(select(func.count()).select_from(CachedTransformation)) == 1


class TestConcurrency:
    async def test_identical_concurrent_requests_share_calls_and_id(
        self, engine: AsyncEngine
    ) -> None:
        transformer = CountingTransformer(delay=0.05)
        pool = TransformerPool(transformer, max_concurrency=10)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def request() -> uuid.UUID:
            async with sessions() as session:
                return await service.create_payload(session, ["a", "b"], ["c", "d"], pool)

        ids = await asyncio.gather(*(request() for _ in range(5)))

        assert len(set(ids)) == 1
        assert sorted(transformer.calls) == ["a", "b", "c", "d"]
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(Payload)) == 1
            assert await session.scalar(select(func.count()).select_from(CachedTransformation)) == 4

    async def test_overlapping_concurrent_requests_transform_each_string_once(
        self, engine: AsyncEngine
    ) -> None:
        transformer = CountingTransformer(delay=0.05)
        pool = TransformerPool(transformer, max_concurrency=10)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def request(list_1: list[str], list_2: list[str]) -> uuid.UUID:
            async with sessions() as session:
                return await service.create_payload(session, list_1, list_2, pool)

        first, second = await asyncio.gather(
            request(["a", "b"], ["c", "d"]), request(["b", "c"], ["d", "e"])
        )

        assert first != second
        assert sorted(transformer.calls) == ["a", "b", "c", "d", "e"]
