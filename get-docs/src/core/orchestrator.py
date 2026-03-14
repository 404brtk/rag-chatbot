from src.config import settings
from src.core.crawler import (
    ProgressCallback,
    fetch_and_convert_urls,
    fetch_page_as_markdown,
)
from src.core.github_fetcher import (
    GitHubFetchResult,
    fetch_github_docs,
    parse_github_url,
)
from src.core.llms_txt_fetcher import LlmsTxtResult, fetch_llms_txt
from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.core.sitemap_parser import collect_sitemap_urls
from src.models.enums import SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import DocPage, EthicsContext, GetDocsResult
from src.utils.http_client import HttpClient
from src.utils.logger import logger
from src.utils.url_utils import extract_domain


def _llms_full_to_doc_page(llms_result: LlmsTxtResult) -> DocPage:
    return DocPage(
        url=llms_result.source_url,
        title=llms_result.title or "",
        content=llms_result.raw_content,
        source_method=SourceMethod.LLMS_TXT,
    )


async def _try_sitemap(
    base_url: str,
    client: HttpClient,
    robots: RobotsParser,
    request: GetDocsRequest,
    ethics: EthicsContext,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    urls = await collect_sitemap_urls(
        base_url,
        client,
        robots=robots,
        timeout=request.timeout,
        max_depth=request.max_depth,
    )
    if not urls:
        return []
    return await fetch_and_convert_urls(
        urls,
        client,
        robots,
        request,
        SourceMethod.SITEMAP_CRAWL,
        ethics,
        base_url=base_url,
        on_progress=on_progress,
    )


async def get_docs(
    request: GetDocsRequest,
    client: HttpClient,
    on_progress: ProgressCallback | None = None,
) -> GetDocsResult:
    """Main orchestration: fetch docs from the best available source.

    priority:
    - url only: llms-full.txt -> llms.txt -> sitemap crawl -> single-page fallback
    - github_repo: GitHub, url-based fallback if url also provided
    """
    base_url = str(request.url) if request.url else None
    ethics = EthicsContext()
    result = GetDocsResult(url=base_url or "", ethics=ethics)

    robots: RobotsParser | None = None
    if base_url:
        logger.info(f"Fetching robots.txt for {base_url}")
        robots = await fetch_robots_txt(base_url, client)
        ethics.robots_crawl_delay_seconds = robots.get_crawl_delay()
        ethics.content_signal_ai_input = robots.is_ai_input_allowed()
        logger.info(
            f"robots.txt: crawl_delay={ethics.robots_crawl_delay_seconds}, ai_input={ethics.content_signal_ai_input}"
        )

        crawl_delay = robots.get_crawl_delay() or 0
        effective_delay = max(request.delay_seconds, crawl_delay)
        domain = extract_domain(base_url)
        client.set_domain_delay(domain, effective_delay)

    step = 0

    # GitHub
    if request.github_repo:
        step += 1
        logger.info(f"Step {step}: Trying GitHub docs for {request.github_repo}")
        doc_folder_override: str | None = None
        parsed_gh = parse_github_url(request.github_repo)
        if parsed_gh and parsed_gh.subpath:
            doc_folder_override = parsed_gh.subpath

        github_token = request.github_token or settings.GITHUB_TOKEN
        try:
            gh_result: GitHubFetchResult | None = await fetch_github_docs(
                request.github_repo,
                client,
                max_files=request.max_pages,
                doc_folder_override=doc_folder_override,
                github_token=github_token,
                on_progress=on_progress,
            )
            if gh_result:
                ethics.license_spdx_id = gh_result.license_spdx_id
            if gh_result and gh_result.pages:
                logger.info(f"GitHub fetch returned {len(gh_result.pages)} pages")
                result.pages.extend(gh_result.pages)
                result.source_method = SourceMethod.GITHUB
                result.github_repo = request.github_repo
                return result
            else:
                logger.info("GitHub fetch returned no pages, falling through")
        except Exception:
            logger.exception("GitHub fetch failed")

    if not base_url or not robots:
        return result

    # llms-full.txt / llms.txt
    step += 1
    logger.info(f"Step {step}: Trying llms.txt / llms-full.txt")
    try:
        llms_result = await fetch_llms_txt(
            base_url,
            client,
            robots=robots,
            ethics=ethics,
        )

        if llms_result is not None:
            if llms_result.is_full:
                logger.info("Found llms-full.txt - using as single doc page")
                result.pages.append(_llms_full_to_doc_page(llms_result))
                result.source_method = SourceMethod.LLMS_TXT
                if on_progress:
                    await on_progress(1, 1)
                return result

            urls = [link.url for link in llms_result.links if not link.optional]
            logger.info(f"Found llms.txt with {len(urls)} links - fetching pages")
            pages = await fetch_and_convert_urls(
                urls,
                client,
                robots,
                request,
                SourceMethod.LLMS_TXT,
                ethics,
                on_progress=on_progress,
            )
            if pages:
                logger.info(f"llms.txt crawl returned {len(pages)} pages")
                result.pages.extend(pages)
                result.source_method = SourceMethod.LLMS_TXT
                return result
            else:
                logger.info("llms.txt links yielded no pages, falling through")
        else:
            logger.info("No llms.txt found, falling through")
    except Exception:
        logger.exception("llms.txt fetch failed")

    # Sitemap crawl
    step += 1
    logger.info(f"Step {step}: Trying sitemap crawl for {base_url}")
    try:
        pages = await _try_sitemap(
            base_url,
            client,
            robots,
            request,
            ethics,
            on_progress,
        )
        if pages:
            logger.info(f"Sitemap crawl returned {len(pages)} pages")
            result.pages.extend(pages)
            result.source_method = SourceMethod.SITEMAP_CRAWL
        else:
            logger.info("Sitemap crawl returned no pages, falling through")
    except Exception:
        logger.exception("Sitemap crawl failed")

    # single-page fallback
    if not result.pages:
        step += 1
        logger.info(f"Step {step}: Falling back to single-page fetch for {base_url}")
        page = await fetch_page_as_markdown(
            base_url, client, request.timeout, SourceMethod.SINGLE_PAGE
        )
        if page:
            result.pages.append(page)
            result.source_method = SourceMethod.SINGLE_PAGE
            if on_progress:
                await on_progress(1, 1)

    return result
