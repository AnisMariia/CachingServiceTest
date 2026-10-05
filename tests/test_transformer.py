import asyncio

import pytest

from caching_service.transformer import TransformerPool
from tests.conftest import CountingTransformer


async def test_concurrent_calls_for_same_string_share_one_call() -> None:
    transformer = CountingTransformer(delay=0.05)
    pool = TransformerPool(transformer, max_concurrency=10)

    results = await asyncio.gather(*(pool.transform("a") for _ in range(5)))

    assert results == ["A"] * 5
    assert transformer.calls == ["a"]


async def test_concurrency_is_limited() -> None:
    transformer = CountingTransformer(delay=0.01)
    pool = TransformerPool(transformer, max_concurrency=3)

    await asyncio.gather(*(pool.transform(str(i)) for i in range(10)))

    assert transformer.max_running == 3


async def test_cancelled_caller_does_not_break_other_waiters() -> None:
    transformer = CountingTransformer(delay=0.05)
    pool = TransformerPool(transformer, max_concurrency=10)
    first = asyncio.create_task(pool.transform("a"))
    second = asyncio.create_task(pool.transform("a"))
    await asyncio.sleep(0.01)

    first.cancel()

    assert await second == "A"
    assert transformer.calls == ["a"]


async def test_failure_is_raised_to_every_waiter() -> None:
    transformer = CountingTransformer(delay=0.01, fail_on="a")
    pool = TransformerPool(transformer, max_concurrency=10)

    results = await asyncio.gather(pool.transform("a"), pool.transform("a"), return_exceptions=True)

    assert all(isinstance(result, RuntimeError) for result in results)
    assert transformer.calls == ["a"]


async def test_failed_call_is_not_remembered() -> None:
    transformer = CountingTransformer(fail_on="a")
    pool = TransformerPool(transformer, max_concurrency=10)

    with pytest.raises(RuntimeError):
        await pool.transform("a")
    transformer.fail_on = None

    assert await pool.transform("a") == "A"


async def test_finished_call_is_not_cached_in_pool() -> None:
    # Caching across requests is the database's job; the pool only deduplicates in-flight calls.
    transformer = CountingTransformer()
    pool = TransformerPool(transformer, max_concurrency=10)

    await pool.transform("a")
    await pool.transform("a")

    assert transformer.calls == ["a", "a"]
