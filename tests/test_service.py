import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from caching_service import service
from caching_service.models import CachedTransformation, Payload
from caching_service.transformer import TransformerPool
from tests.conftest import CountingTransformer


def test_interleave():
    assert service.interleave(["a", "b"], ["x", "y"]) == ["a", "x", "b", "y"]


async def test_output_is_interleaved_and_transformed(session, pool):
    payload_id = await service.create_payload(session, ["a", "b"], ["x", "y"], pool)

    assert await service.get_payload_output(session, payload_id) == "A, X, B, Y"


async def test_duplicate_strings_are_transformed_once(session, pool, transformer):
    await service.create_payload(session, ["a", "a"], ["a", "b"], pool)

    assert sorted(transformer.calls) == ["a", "b"]


async def test_cached_strings_are_not_transformed_again(session, pool, transformer):
    await service.create_payload(session, ["a"], ["b"], pool)

    await service.create_payload(session, ["b", "c"], ["a", "a"], pool)

    assert sorted(transformer.calls) == ["a", "b", "c"]


async def test_same_input_reuses_payload_id(session, pool, transformer):
    first = await service.create_payload(session, ["a"], ["b"], pool)
    calls_after_first = len(transformer.calls)

    second = await service.create_payload(session, ["a"], ["b"], pool)

    assert first == second
    assert len(transformer.calls) == calls_after_first


async def test_different_input_gets_different_id(session, pool):
    first = await service.create_payload(session, ["a"], ["b"], pool)
    second = await service.create_payload(session, ["b"], ["a"], pool)

    assert first != second


async def test_unknown_payload_returns_none(session):
    assert await service.get_payload_output(session, uuid.uuid4()) is None


async def test_transformer_failure_stores_nothing_and_can_be_retried(session):
    transformer = CountingTransformer(fail_on="b")
    pool = TransformerPool(transformer, max_concurrency=10)

    with pytest.raises(RuntimeError):
        await service.create_payload(session, ["a"], ["b"], pool)
    await session.rollback()

    assert await session.scalar(select(func.count()).select_from(Payload)) == 0
    transformer.fail_on = None
    await service.create_payload(session, ["a"], ["b"], pool)


class TestConcurrency:
    async def test_identical_concurrent_requests_share_calls_and_id(self, engine):
        from sqlalchemy.ext.asyncio import async_sessionmaker

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
            assert (
                await session.scalar(select(func.count()).select_from(CachedTransformation)) == 4
            )

    async def test_concurrency_is_limited(self, session):
        transformer = CountingTransformer(delay=0.01)
        pool = TransformerPool(transformer, max_concurrency=3)
        sources = [str(i) for i in range(10)]

        await service.create_payload(session, sources, sources, pool)

        assert transformer.max_running == 3

    async def test_cancelled_caller_does_not_break_other_waiters(self):
        transformer = CountingTransformer(delay=0.05)
        pool = TransformerPool(transformer, max_concurrency=10)
        first = asyncio.create_task(pool.transform("a"))
        second = asyncio.create_task(pool.transform("a"))
        await asyncio.sleep(0.01)

        first.cancel()

        assert await second == "A"
        assert transformer.calls == ["a"]

    async def test_failed_call_is_not_remembered(self):
        transformer = CountingTransformer(fail_on="a")
        pool = TransformerPool(transformer, max_concurrency=10)

        with pytest.raises(RuntimeError):
            await pool.transform("a")
        transformer.fail_on = None

        assert await pool.transform("a") == "A"
