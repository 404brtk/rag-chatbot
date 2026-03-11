from collections.abc import Awaitable, Callable

import httpx

from src.core.crawler import crawl_sitemap
from src.core.github_discovery import discover_github_repo
from src.core.github_fetcher import (
    GitHubFetchResult,
    fetch_github_docs,
    parse_github_url,
)
from src.core.llms_txt_fetcher import LlmsTxtResult, fetch_llms_txt
from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.models.enums import FetchMethod, SourceMethod
from src.models.requests import GetDocsOptions, GetDocsRequest
from src.models.responses import DocPage, EthicsContext, GetDocsResult
from src.parsing.html_extractor import extract_content, extract_title
from src.parsing.html_to_md import html_to_markdown
from src.parsing.mdx_strip import strip_mdx
from src.utils.http_client import get_with_retry
from src.utils.logger import logger
from src.utils.rate_limiter import fetch_with_rate_limit
from src.utils.url_utils import extract_path, has_md_extension

ProgressCallback = Callable[[int, int | None], Awaitable[None]]


def _html_to_doc_page(url: str, html: str, source_method: SourceMethod) -> DocPage:
    title = extract_title(html)
    element = extract_content(html)
    markdown = html_to_markdown(element) if element else ""
    return DocPage(url=url, title=title, content=markdown, source_method=source_method)


async def _try_content_negotiation(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
) -> str | None:
    """try fetching with Accept: text/markdown header."""
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
    """try fetching a .md variant of the URL."""
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
        page = _html_to_doc_page(url, resp.text, source_method)
        return page if page.content else None
    except httpx.HTTPError:
        return None


async def _probe_and_fetch(
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


async def _fetch_page_as_markdown(
    url: str,
    client: httpx.AsyncClient,
    timeout: float,
    source_method: SourceMethod,
    preferred_method: FetchMethod | None = None,
) -> DocPage | None:
    if preferred_method is None:
        page, _ = await _probe_and_fetch(url, client, timeout, source_method)
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


def _filter_urls_by_robots(
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


async def _fetch_and_convert_urls(
    urls: list[str],
    client: httpx.AsyncClient,
    robots: RobotsParser,
    options: GetDocsOptions,
    source_method: SourceMethod,
    ethics: EthicsContext,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    filtered, robots_count, signal_count = _filter_urls_by_robots(urls, robots)
    ethics.pages_filtered_by_robots += robots_count
    ethics.pages_filtered_by_content_signal += signal_count

    filtered = filtered[: options.max_web_pages]

    if not filtered:
        return []

    pages: list[DocPage] = []
    effective_delay = max(options.delay_seconds, robots.get_crawl_delay() or 0)

    first_page, method = await _probe_and_fetch(
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
            lambda url: _fetch_page_as_markdown(
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


def _llms_full_to_doc_page(llms_result: LlmsTxtResult) -> DocPage:
    return DocPage(
        url=llms_result.source_url,
        title=llms_result.title or "",
        content=llms_result.raw_content,
        source_method=SourceMethod.LLMS_TXT,
    )


async def _try_sitemap(
    base_url: str,
    client: httpx.AsyncClient,
    robots: RobotsParser,
    options: GetDocsOptions,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    """Sitemap crawl fallback: fetch pages, convert to markdown.

    TODO: it's worth considering using _fetch_page_as_markdown instead of plain HTML fetch
    to benefit from content negotiation and .md URL probing.
    This would however triple the requests
    unlike llms.txt, it's not so certain that it will actually work
    thus, it's better not to put additional strain on the servers
    """
    crawl_result = await crawl_sitemap(
        base_url,
        client,
        robots=robots,
        max_pages=options.max_web_pages,
        max_concurrent=options.max_concurrent,
        delay_seconds=options.delay_seconds,
    )

    pages: list[DocPage] = []
    for cp in crawl_result.pages:
        page = _html_to_doc_page(cp.url, cp.html, SourceMethod.SITEMAP_CRAWL)
        if page.content:
            pages.append(page)

    if on_progress:
        await on_progress(len(pages), len(pages))

    return pages


async def _fetch_github(
    repo_url: str,
    client: httpx.AsyncClient,
    max_files: int = 300,
    delay_seconds: float = 1.5,
    doc_folder_override: str | None = None,
    root_only: bool = False,
) -> tuple[list[DocPage], str, GitHubFetchResult | None]:
    gh_result = await fetch_github_docs(
        repo_url,
        client,
        max_files=max_files,
        delay_seconds=delay_seconds,
        doc_folder_override=doc_folder_override,
        root_only=root_only,
    )
    if gh_result is None or not gh_result.files:
        return [], repo_url, gh_result

    pages = [
        DocPage(
            url=(
                f"https://github.com/{gh_result.owner}/{gh_result.repo}"
                f"/blob/{gh_result.branch}/{f.path}"
            ),
            title=f.path,
            # TODO: add rst-to-markdown conversion for .rst files
            content=strip_mdx(f.content) if f.path.endswith(".mdx") else f.content,
            source_method=SourceMethod.GITHUB_RAW,
        )
        for f in gh_result.files
    ]
    return pages, repo_url, gh_result


async def _resolve_github_repo(
    request: GetDocsRequest,
    client: httpx.AsyncClient,
    timeout: float,
) -> str | None:
    if request.github_repo:
        return request.github_repo

    if not request.url:
        return None

    try:
        resp = await get_with_retry(
            client, str(request.url), follow_redirects=True, timeout=timeout
        )
        if resp.status_code == 200 and "text/html" in resp.headers.get(
            "content-type", ""
        ):
            return discover_github_repo(resp.text)
    except httpx.HTTPError:
        pass
    return None


async def get_docs(
    request: GetDocsRequest,
    client: httpx.AsyncClient,
    on_progress: ProgressCallback | None = None,
) -> GetDocsResult:
    """Main orchestration: fetch docs from the best available source.

    priority:
    llms-full.txt -> llms.txt links -> GitHub docs -> sitemap crawl.
    """
    base_url = str(request.url) if request.url else None
    options = request.options
    ethics = EthicsContext()
    result = GetDocsResult(url=base_url or "", ethics=ethics)

    robots: RobotsParser | None = None
    if base_url:
        robots = await fetch_robots_txt(base_url, client)
        ethics.robots_crawl_delay_seconds = robots.get_crawl_delay()
        ethics.content_signal_ai_input = robots.is_ai_input_allowed()

    # 1. llms-full.txt / llms.txt
    if base_url and robots:
        try:
            llms_result = await fetch_llms_txt(
                base_url, client, robots=robots, delay_seconds=options.delay_seconds
            )

            if llms_result is not None:
                if llms_result.is_full:
                    result.pages.append(_llms_full_to_doc_page(llms_result))
                    result.source_method = SourceMethod.LLMS_TXT
                    if on_progress:
                        await on_progress(1, 1)
                    return result

                urls = [link.url for link in llms_result.links if not link.optional]
                pages = await _fetch_and_convert_urls(
                    urls,
                    client,
                    robots,
                    options,
                    SourceMethod.LLMS_TXT,
                    ethics,
                    on_progress,
                )
                if pages:
                    result.pages.extend(pages)
                    result.source_method = SourceMethod.LLMS_TXT
                    return result
        except Exception:
            logger.exception("llms.txt fetch failed")

    # 2. GitHub docs
    repo_url = await _resolve_github_repo(request, client, timeout=options.timeout)
    if repo_url:
        doc_folder_override: str | None = None
        parsed_gh = parse_github_url(repo_url)
        if parsed_gh and parsed_gh.subpath:
            doc_folder_override = parsed_gh.subpath

        has_url = request.url is not None
        root_only = has_url and doc_folder_override is None

        try:
            github_pages, repo_url, gh_result = await _fetch_github(
                repo_url,
                client,
                max_files=options.max_github_files,
                delay_seconds=options.delay_seconds,
                doc_folder_override=doc_folder_override,
                root_only=root_only,
            )
            if gh_result:
                ethics.license_spdx_id = gh_result.license_spdx_id
                ethics.license_allowed = gh_result.license_spdx_id is not None
            if github_pages:
                result.pages.extend(github_pages)
                result.source_method = SourceMethod.GITHUB_RAW
                result.github_repo = repo_url
                if on_progress:
                    await on_progress(len(github_pages), len(github_pages))
                return result
        except Exception:
            logger.exception("GitHub fetch failed")

    # 3. Sitemap crawl
    if base_url and robots:
        try:
            pages = await _try_sitemap(
                base_url,
                client,
                robots,
                options,
                on_progress,
            )
            if pages:
                result.pages.extend(pages)
                result.source_method = SourceMethod.SITEMAP_CRAWL
        except Exception:
            logger.exception("Sitemap crawl failed")

    # 4. single-page fallback
    if not result.pages and base_url:
        page = await _fetch_page_as_markdown(
            base_url, client, options.timeout, SourceMethod.SINGLE_PAGE
        )
        if page:
            result.pages.append(page)
            result.source_method = SourceMethod.SINGLE_PAGE
            if on_progress:
                await on_progress(1, 1)

    return result
