from dataclasses import dataclass, field
import httpx

from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.core.sitemap_parser import fetch_sitemap_urls
from src.utils.http_client import get_with_retry
from src.utils.logger import logger
from src.utils.rate_limiter import fetch_with_rate_limit
from src.utils.url_utils import (
    extract_path,
    is_url_within_scope,
    make_url_prefix,
    normalize_url,
    url_path_parents,
)


@dataclass
class CrawlPage:
    url: str
    html: str


@dataclass
class CrawlResult:
    pages: list[CrawlPage] = field(default_factory=list)


async def _fetch_page(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
) -> tuple[str, str | None, str | None]:
    try:
        resp = await get_with_retry(client, url, follow_redirects=True, timeout=timeout)
        if resp.status_code != 200:
            return (url, None, f"HTTP {resp.status_code}")
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return (url, None, f"Not HTML: {content_type}")
        return (url, resp.text, None)
    except httpx.HTTPError as exc:
        return (url, None, str(exc))


async def crawl_sitemap(
    base_url: str,
    client: httpx.AsyncClient,
    robots: RobotsParser | None = None,
    timeout: float = 15,
    max_pages: int = 300,
    max_concurrent: int = 10,
    delay_seconds: float = 1.5,
) -> CrawlResult:
    if robots is None:
        robots = await fetch_robots_txt(base_url, client, timeout)

    sitemap_sources = robots.get_sitemaps()
    all_page_urls: list[str] = []

    if sitemap_sources:
        for src in sitemap_sources:
            all_page_urls.extend(await fetch_sitemap_urls(src, client, timeout))
    else:
        for parent in url_path_parents(base_url):
            candidate = parent.rstrip("/") + "/sitemap.xml"
            urls = await fetch_sitemap_urls(candidate, client, timeout)
            if urls:
                all_page_urls.extend(urls)
                break

    prefix = make_url_prefix(base_url)

    seen: set[str] = set()
    filtered: list[str] = []
    for url in all_page_urls:
        norm = normalize_url(url)
        if norm in seen:
            continue
        seen.add(norm)
        if not is_url_within_scope(norm, prefix):
            continue
        path = extract_path(norm)
        if not robots.is_allowed(path):
            continue
        if robots.is_ai_input_allowed(path) is False:
            continue
        filtered.append(norm)

    filtered = filtered[:max_pages]

    result = CrawlResult()
    effective_delay = max(delay_seconds, robots.get_crawl_delay() or 0)

    outcomes = await fetch_with_rate_limit(
        filtered,
        lambda url: _fetch_page(url, client, timeout),
        max_concurrent=max_concurrent,
        delay_seconds=effective_delay,
    )

    for _url, outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.warning(f"Crawl error: {outcome}")
            continue
        url, html, error = outcome
        if error or html is None:
            logger.warning(f"Failed to fetch {url}: {error or 'Unknown'}")
            continue
        result.pages.append(CrawlPage(url=url, html=html))

    return result
