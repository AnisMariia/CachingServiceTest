"""Stand-in for the external service whose calls we want to minimise."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

# Simulated network latency, so that the benefit of the cache is visible.
LATENCY_SECONDS = 0.05

Transformer = Callable[[str], Awaitable[str]]


async def transform(text: str) -> str:
    await asyncio.sleep(LATENCY_SECONDS)
    return text.upper()


class TransformerPool:
    """Calls the transformer with a concurrency limit and without duplicate in-flight calls.

    Two concurrent requests that both miss the database cache for the same string
    would otherwise each call the transformer. Here they share one call instead.
    This only covers a single process; across processes the database still ends up
    with one row per string, at the cost of an occasional repeated call.
    """

    def __init__(self, transformer: Transformer, max_concurrency: int) -> None:
        self._transformer = transformer
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._in_flight: dict[str, asyncio.Task[str]] = {}

    async def transform(self, source: str) -> str:
        task = self._in_flight.get(source)
        if task is None:
            task = asyncio.create_task(self._call(source))
            self._in_flight[source] = task
            task.add_done_callback(lambda done: self._finish(source, done))
        # The call is owned by its own task, not by the first caller: shielding keeps
        # it alive when that caller is cancelled (e.g. the client disconnects), so
        # the other requests waiting on the same string still get their result.
        return await asyncio.shield(task)

    async def _call(self, source: str) -> str:
        async with self._semaphore:
            return await self._transformer(source)

    def _finish(self, source: str, task: asyncio.Task[str]) -> None:
        del self._in_flight[source]
        if not task.cancelled():
            # Mark the error as retrieved: if every waiter was cancelled, nobody else
            # would, and asyncio would log "exception was never retrieved".
            with contextlib.suppress(Exception):
                task.exception()
