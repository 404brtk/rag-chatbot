from collections.abc import Awaitable, Callable

import httpx

from src.core.robots_parser import RobotsParser
from src.models.enums import FetchMethod, SourceMethod
from src.models.requests import GetDocsOptions
from src.models.responses import DocPage, EthicsContext
from src.parsing.html_extractor import extract_content, extract_title
from src.parsing.html_to_md import html_to_markdown
from src.utils.http_client import get_with_retry
from src.utils.logger import logger
from src.utils.rate_limiter import fetch_with_rate_limit
from src.utils.url_utils import (
    extract_path,
    has_md_extension,
    is_url_within_scope,
    make_url_prefix,
    normalize_url,
)

ProgressCallback = Callable[[int, int | None], Awaitable[None]]


def html_to_doc_page(url: str, html: str, source_method: SourceMethod) -> DocPage:
    title = extract_title(html)
    element = extract_content(html)
    markdown = html_to_markdown(element) if element else ""
    return DocPage(url=url, title=title, content=markdown, source_method=source_method)


async def _try_content_negotiation(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
) -> str | None:
    try:
        resp = await get_with_retry(
            client,
            url,
            headers={"Accept": "text/markdown"},
            follow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "text/markdown" in content_type:
            text = resp.text.strip()
            return text if text else None
    except httpx.HTTPError:
        pass
    return None


async def _try_md_url(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
) -> str | None:
    md_url = url if has_md_extension(url) else url.rstrip("/") + ".md"
    try:
        resp = await get_with_retry(
            client, md_url, follow_redirects=True, timeout=timeout
        )
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "text/markdown" in content_type or "text/plain" in content_type:
            text = resp.text.strip()
            if text and not text.lstrip().startswith("<!"):
                return text
    except httpx.HTTPError:
        pass
    return None


async def _fetch_html(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
    source_method: SourceMethod,
) -> DocPage | None:
    try:
        resp = await get_with_retry(client, url, follow_redirects=True, timeout=timeout)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None
        page = html_to_doc_page(url, resp.text, source_method)
        return page if page.content else None
    except httpx.HTTPError:
        return None


async def probe_and_fetch(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
    source_method: SourceMethod,
) -> tuple[DocPage | None, FetchMethod]:
    if not has_md_extension(url):
        md = await _try_content_negotiation(url, client, timeout)
        if md:
            return DocPage(
                url=url, title="", content=md, source_method=source_method
            ), FetchMethod.CONTENT_NEGOTIATION

    md = await _try_md_url(url, client, timeout)
    if md:
        return DocPage(
            url=url, title="", content=md, source_method=source_method
        ), FetchMethod.MD_URL

    return await _fetch_html(url, client, timeout, source_method), FetchMethod.HTML


async def fetch_page_as_markdown(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
    source_method: SourceMethod,
    preferred_method: FetchMethod | None = None,
) -> DocPage | None:
    if preferred_method is None:
        page, _ = await probe_and_fetch(url, client, timeout, source_method)
        return page

    if has_md_extension(url):
        md = await _try_md_url(url, client, timeout)
        if md:
            return DocPage(url=url, title="", content=md, source_method=source_method)
        return await _fetch_html(url, client, timeout, source_method)

    if preferred_method == FetchMethod.CONTENT_NEGOTIATION:
        md = await _try_content_negotiation(url, client, timeout)
        if md:
            return DocPage(url=url, title="", content=md, source_method=source_method)

    elif preferred_method == FetchMethod.MD_URL:
        md = await _try_md_url(url, client, timeout)
        if md:
            return DocPage(url=url, title="", content=md, source_method=source_method)

    elif preferred_method == FetchMethod.HTML:
        return await _fetch_html(url, client, timeout, source_method)

    return await _fetch_html(url, client, timeout, source_method)


def filter_urls_by_robots(
    urls: list[str],
    robots: RobotsParser,
) -> tuple[list[str], int, int]:
    allowed: list[str] = []
    robots_filtered = 0
    content_signal_filtered = 0

    for url in urls:
        path = extract_path(url)
        if not robots.is_allowed(path):
            robots_filtered += 1
            continue
        if robots.is_ai_input_allowed(path) is False:
            content_signal_filtered += 1
            continue
        allowed.append(url)

    return allowed, robots_filtered, content_signal_filtered


async def fetch_and_convert_urls(
    urls: list[str],
    client: httpx.AsyncClient,
    robots: RobotsParser,
    options: GetDocsOptions,
    source_method: SourceMethod,
    ethics: EthicsContext,
    base_url: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        norm = normalize_url(url)
        if norm not in seen:
            seen.add(norm)
            unique.append(norm)

    if base_url is not None:
        prefix = make_url_prefix(base_url)
        unique = [u for u in unique if is_url_within_scope(u, prefix)]

    filtered, robots_count, signal_count = filter_urls_by_robots(unique, robots)
    ethics.pages_filtered_by_robots += robots_count
    ethics.pages_filtered_by_content_signal += signal_count

    filtered = filtered[: options.max_web_pages]

    if not filtered:
        return []

    pages: list[DocPage] = []
    effective_delay = max(options.delay_seconds, robots.get_crawl_delay() or 0)

    first_page, method = await probe_and_fetch(
        filtered[0], client, options.timeout, source_method
    )
    if first_page:
        pages.append(first_page)

    if on_progress:
        await on_progress(len(pages), len(filtered))

    remaining = filtered[1:]
    if remaining:
        outcomes = await fetch_with_rate_limit(
            remaining,
            lambda url: fetch_page_as_markdown(
                url,
                client,
                options.timeout,
                source_method,
                preferred_method=method,
            ),
            max_concurrent=options.max_concurrent,
            delay_seconds=effective_delay,
            on_progress=on_progress,
        )

        for url, outcome in outcomes:
            if isinstance(outcome, Exception):
                logger.warning(f"Failed to fetch {url}: {outcome}")
                continue
            if outcome is None:
                logger.warning(f"Failed to fetch or extract content: {url}")
                continue
            pages.append(outcome)

    return pages
