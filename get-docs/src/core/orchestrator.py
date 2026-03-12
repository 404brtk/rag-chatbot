import httpx

from src.config import settings
from src.core.crawler import (
    ProgressCallback,
    fetch_and_convert_urls,
    fetch_page_as_markdown,
)
from src.core.github_discovery import discover_github_repo
from src.core.github_fetcher import (
    GitHubFetchResult,
    fetch_github_docs,
    parse_github_url,
)
from src.core.llms_txt_fetcher import LlmsTxtResult, fetch_llms_txt
from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.core.sitemap_parser import collect_sitemap_urls
from src.models.enums import SourceMethod
from src.models.requests import GetDocsOptions, GetDocsRequest
from src.models.responses import DocPage, EthicsContext, GetDocsResult
from src.utils.http_client import get_with_retry
from src.utils.logger import logger


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
    ethics: EthicsContext,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    urls = await collect_sitemap_urls(
        base_url,
        client,
        robots=robots,
        timeout=options.timeout,
        max_depth=options.max_depth,
        max_concurrent=options.max_concurrent,
        delay_seconds=options.delay_seconds,
    )
    if not urls:
        return []
    return await fetch_and_convert_urls(
        urls,
        client,
        robots,
        options,
        SourceMethod.SITEMAP_CRAWL,
        ethics,
        base_url=base_url,
        on_progress=on_progress,
    )


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
                base_url,
                client,
                robots=robots,
                delay_seconds=options.delay_seconds,
                ethics=ethics,
            )

            if llms_result is not None:
                if llms_result.is_full:
                    result.pages.append(_llms_full_to_doc_page(llms_result))
                    result.source_method = SourceMethod.LLMS_TXT
                    if on_progress:
                        await on_progress(1, 1)
                    return result

                urls = [link.url for link in llms_result.links if not link.optional]
                pages = await fetch_and_convert_urls(
                    urls,
                    client,
                    robots,
                    options,
                    SourceMethod.LLMS_TXT,
                    ethics,
                    on_progress=on_progress,
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
            gh_result: GitHubFetchResult | None = await fetch_github_docs(
                repo_url,
                client,
                max_files=options.max_pages,
                max_concurrent=options.max_concurrent,
                delay_seconds=options.delay_seconds,
                doc_folder_override=doc_folder_override,
                root_only=root_only,
                github_token=settings.GITHUB_TOKEN,
            )
            if gh_result:
                ethics.license_spdx_id = gh_result.license_spdx_id
            if gh_result and gh_result.pages:
                result.pages.extend(gh_result.pages)
                result.source_method = SourceMethod.GITHUB
                result.github_repo = repo_url
                if on_progress:
                    await on_progress(len(gh_result.pages), len(gh_result.pages))
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
                ethics,
                on_progress,
            )
            if pages:
                result.pages.extend(pages)
                result.source_method = SourceMethod.SITEMAP_CRAWL
        except Exception:
            logger.exception("Sitemap crawl failed")

    # 4. single-page fallback
    if not result.pages and base_url:
        page = await fetch_page_as_markdown(
            base_url, client, options.timeout, SourceMethod.SINGLE_PAGE
        )
        if page:
            result.pages.append(page)
            result.source_method = SourceMethod.SINGLE_PAGE
            if on_progress:
                await on_progress(1, 1)

    return result
