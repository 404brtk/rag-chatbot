import asyncio
import time
from collections.abc import Awaitable, Callable


async def fetch_with_rate_limit[T, R](
    items: list[T],
    fetch_fn: Callable[[T], Awaitable[R]],
    max_concurrent: int = 5,
    delay_seconds: float = 1.5,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[tuple[T, R | Exception]]:
    if not items:
        return []

    semaphore = asyncio.Semaphore(max_concurrent)
    lock = asyncio.Lock()
    last_start = 0.0
    completed = 0
    total = len(items)

    async def _run(idx: int, item: T) -> tuple[int, T, R | Exception]:
        nonlocal last_start, completed

        async with semaphore:
            async with lock:
                now = time.monotonic()
                wait = delay_seconds - (now - last_start)
                if wait > 0:
                    await asyncio.sleep(wait)
                last_start = time.monotonic()

            try:
                result: R | Exception = await fetch_fn(item)
            except Exception as e:
                result = e

            completed += 1
            if on_progress:
                await on_progress(completed, total)

            return idx, item, result

    tasks = [asyncio.ensure_future(_run(i, item)) for i, item in enumerate(items)]

    ordered: dict[int, tuple[T, R | Exception]] = {}
    for task in asyncio.as_completed(tasks):
        idx, item, result = await task
        ordered[idx] = (item, result)

    return [ordered[i] for i in range(total)]
