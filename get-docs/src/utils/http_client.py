import asyncio
import random
import httpx

from src.utils.logger import logger

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _randomized_backoff(attempt: int, base_delay: float, max_delay: float) -> float:
    delay = base_delay * (2**attempt)
    delay = min(delay, max_delay)
    return delay * (0.5 + random.random() * 0.5)


def _get_delay(
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


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs,
) -> httpx.Response:
    for attempt in range(1 + max_retries):
        try:
            resp = await client.get(url, **kwargs)
            logger.debug(f"GET {url} -> {resp.status_code}")

            if resp.status_code not in _RETRYABLE_STATUS_CODES:
                return resp

            if attempt == max_retries:
                logger.warning(
                    f"GET {url} -> {resp.status_code} (gave up after {max_retries} retries)"
                )
                return resp

            delay = _get_delay(resp, attempt, base_delay, max_delay)
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
