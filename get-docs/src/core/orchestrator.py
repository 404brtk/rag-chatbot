from src.config import settings
from src.core.github_fetcher import (
    GitHubFetchResult,
    fetch_github_docs,
    parse_github_url,
)
from src.core.robots_txt_parser import fetch_robots_txt
from src.core.llms_txt_parser import fetch_llms_txt
from src.core.sitemap_parser import collect_sitemap_urls
from src.core.link_crawler import crawl_links
from src.core.page_fetcher import ProgressCallback, fetch_and_convert_urls
from src.models.enums import SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import DocPage, EthicsContext, GetDocsResult
from src.utils.http_client import HttpClient
from src.utils.logger import logger
from src.utils.url_utils import extract_domain


async def get_docs(
    request: GetDocsRequest,
    client: HttpClient,
    on_progress: ProgressCallback | None = None,
) -> GetDocsResult:
    """Main orchestration: fetch docs from the best available source.

    priority:
    - url only: llms-full.txt -> llms.txt -> sitemap crawl -> link crawl -> single-page fallback
    - github_repo: GitHub, url-based fallback if url also provided
    """
    base_url = str(request.url) if request.url else None
    ethics = EthicsContext()
    result = GetDocsResult(url=base_url or "", ethics=ethics)

    step = 0

    # GitHub
    if request.github_repo:
        step += 1
        logger.info(f"Step {step}: Trying GitHub docs for {request.github_repo}")
        doc_folder_override: str | None = None
        parsed_gh = parse_github_url(url=request.github_repo)
        if parsed_gh and parsed_gh.subpath:
            doc_folder_override = parsed_gh.subpath

        github_token = request.github_token or settings.GITHUB_TOKEN
        try:
            gh_result: GitHubFetchResult | None = await fetch_github_docs(
                repo_url=request.github_repo,
                client=client,
                max_files=request.max_pages,
                doc_folder_override=doc_folder_override,
                github_token=github_token,
                on_progress=on_progress,
                fair_use=request.fair_use,
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

    if not base_url:
        return result

    logger.info(f"Fetching robots.txt for {base_url}")
    robots = await fetch_robots_txt(base_url=base_url, client=client)
    ethics.robots_crawl_delay_seconds = robots.get_crawl_delay()
    ethics.content_signal_ai_input = robots.is_ai_input_allowed()
    logger.info(
        f"robots.txt: crawl_delay={ethics.robots_crawl_delay_seconds}, ai_input={ethics.content_signal_ai_input}"
    )

    crawl_delay = robots.get_crawl_delay() or 0
    effective_delay = max(request.delay_seconds, crawl_delay)
    domain = extract_domain(url=base_url)
    client.set_domain_delay(domain=domain, delay=effective_delay)

    # llms-full.txt / llms.txt
    step += 1
    logger.info(f"Step {step}: Trying llms.txt / llms-full.txt")
    try:
        llms_result = await fetch_llms_txt(
            base_url=base_url,
            client=client,
            robots=robots,
            ethics=ethics,
            skip_full=request.skip_llms_full,
        )

        if llms_result is not None:
            if llms_result.is_full:
                logger.info("Found llms-full.txt - using as single doc page")
                result.pages.append(
                    DocPage(
                        url=llms_result.source_url,
                        title=llms_result.title or "",
                        content=llms_result.raw_content,
                        source_method=SourceMethod.LLMS_TXT,
                    )
                )
                result.source_method = SourceMethod.LLMS_TXT
                if on_progress:
                    await on_progress(1, 1)
                return result
            else:
                urls = [link.url for link in llms_result.links if not link.optional]
                logger.info(f"Found llms.txt with {len(urls)} links - fetching pages")
                pages = await fetch_and_convert_urls(
                    urls=urls,
                    client=client,
                    robots=robots,
                    options=request,
                    source_method=SourceMethod.LLMS_TXT,
                    ethics=ethics,
                    base_url=base_url,
                    on_progress=on_progress,
                )
                if pages:
                    logger.info(f"llms.txt crawl returned {len(pages)} pages")
                    result.pages.extend(pages)
                    result.source_method = SourceMethod.LLMS_TXT
                    return result
                logger.info("llms.txt links yielded no pages, falling through")
        else:
            logger.info("No llms.txt found, falling through")
    except Exception:
        logger.exception("llms.txt fetch failed")

    # Sitemap crawl
    step += 1
    logger.info(f"Step {step}: Trying sitemap crawl for {base_url}")
    try:
        urls = await collect_sitemap_urls(
            base_url=base_url,
            client=client,
            robots=robots,
            timeout=request.timeout,
            max_depth=request.max_depth,
        )
        if urls:
            pages = await fetch_and_convert_urls(
                urls=urls,
                client=client,
                robots=robots,
                options=request,
                source_method=SourceMethod.SITEMAP_CRAWL,
                ethics=ethics,
                base_url=base_url,
                on_progress=on_progress,
            )
            if pages:
                logger.info(f"Sitemap crawl returned {len(pages)} pages")
                result.pages.extend(pages)
                result.source_method = SourceMethod.SITEMAP_CRAWL
                return result
            logger.info("Sitemap crawl returned no pages, falling through")
        else:
            logger.info("No sitemap URLs found, falling through")
    except Exception:
        logger.exception("Sitemap crawl failed")

    # link crawl
    step += 1
    logger.info(f"Step {step}: Trying link crawl for {base_url}")
    try:
        pages = await crawl_links(
            base_url=base_url,
            client=client,
            robots=robots,
            options=request,
            ethics=ethics,
            on_progress=on_progress,
        )
        if pages:
            logger.info(f"Link crawl returned {len(pages)} pages")
            result.pages.extend(pages)
            result.source_method = SourceMethod.LINK_CRAWL
            return result
        logger.info("Link crawl returned no pages, falling through")
    except Exception:
        logger.exception("Link crawl failed")

    # single-page fallback
    step += 1
    logger.info(f"Step {step}: Falling back to single-page fetch for {base_url}")
    try:
        pages = await fetch_and_convert_urls(
            urls=[base_url],
            client=client,
            robots=robots,
            options=request,
            source_method=SourceMethod.SINGLE_PAGE,
            ethics=ethics,
            on_progress=on_progress,
        )
        if pages:
            result.pages.extend(pages)
            result.source_method = SourceMethod.SINGLE_PAGE
    except Exception:
        logger.exception("Single-page fetch failed")

    return result
