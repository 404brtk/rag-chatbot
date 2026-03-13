import asyncio
import random
import time
from collections.abc import Awaitable, Callable
import httpx

from src.utils.logger import logger
from src.utils.url_utils import extract_domain

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _randomized_backoff(attempt: int, base_delay: float, max_delay: float) -> float:
    delay = base_delay * (2**attempt)
    delay = min(delay, max_delay)
    return delay * (0.5 + random.random() * 0.5)


def _get_retry_delay(
    resp: httpx.Response,
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), max_delay)
        except ValueError:
            pass
    return _randomized_backoff(attempt, base_delay, max_delay)


class ThrottleState:
    def __init__(self):
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get_lock(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def throttle(self, domain: str, delay: float) -> None:
        async with self.get_lock(domain):
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            wait = delay - (now - last)
            if wait > 0:
                logger.debug(
                    f"Rate limit: sleeping {wait:.1f}s before next request to {domain}"
                )
                await asyncio.sleep(wait)
            self._last_request[domain] = time.monotonic()


class HttpClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        default_delay: float = 1.5,
        throttle: ThrottleState | None = None,
    ):
        self._client = client
        self._default_delay = default_delay
        self._domain_delays: dict[str, float] = {}
        self._throttle_state = throttle or ThrottleState()

    def set_domain_delay(self, domain: str, delay: float) -> None:
        self._domain_delays[domain] = delay
        logger.info(f"Throttle: {domain} delay set to {delay:.1f}s")

    async def _throttle(self, url: str) -> None:
        domain = extract_domain(url)
        delay = self._domain_delays.get(domain, self._default_delay)
        await self._throttle_state.throttle(domain, delay)

    async def get(
        self,
        url: str,
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        **kwargs,
    ) -> httpx.Response:
        for attempt in range(1 + max_retries):
            await self._throttle(url)
            try:
                resp = await self._client.get(url, **kwargs)
                logger.debug(f"GET {url} -> {resp.status_code}")

                if resp.status_code not in _RETRYABLE_STATUS_CODES:
                    return resp

                if attempt == max_retries:
                    logger.warning(
                        f"GET {url} -> {resp.status_code} (gave up after {max_retries} retries)"
                    )
                    return resp

                delay = _get_retry_delay(resp, attempt, base_delay, max_delay)
                logger.debug(
                    f"GET {url} -> {resp.status_code} (retry {attempt + 1}/{max_retries} in {delay:.1f}s)"
                )
                await asyncio.sleep(delay)

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == max_retries:
                    logger.warning(
                        f"GET {url} -> {type(e).__name__} (gave up after {max_retries} retries)"
                    )
                    raise
                delay = _randomized_backoff(attempt, base_delay, max_delay)
                logger.debug(
                    f"GET {url} -> {type(e).__name__} (retry {attempt + 1}/{max_retries} in {delay:.1f}s)"
                )
                await asyncio.sleep(delay)

    async def fetch_many[T, R](
        self,
        items: list[T],
        fetch_fn: Callable[[T], Awaitable[R]],
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
        progress_offset: int = 0,
        progress_total: int | None = None,
    ) -> list[tuple[T, R | Exception]]:
        if not items:
            return []

        total = progress_total if progress_total is not None else len(items)
        results: list[tuple[T, R | Exception]] = []

        for i, item in enumerate(items):
            try:
                result: R | Exception = await fetch_fn(item)
            except Exception as e:
                result = e

            results.append((item, result))

            if on_progress:
                await on_progress(progress_offset + i + 1, total)

        return results

    async def aclose(self) -> None:
        await self._client.aclose()
