from bs4 import BeautifulSoup
import httpx

from src.config import settings
from src.core.page_fetcher import (
    ProgressCallback,
    filter_urls_by_robots,
    html_to_doc_page,
)
from src.core.robots_tags_parser import (
    check_html_meta,
    has_nofollow_header,
    is_response_blocked,
)
from src.core.robots_txt_parser import RobotsParser
from src.models.enums import SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import DocPage, EthicsContext
from src.utils.http_client import HttpClient
from src.utils.logger import logger
from src.utils.lang_utils import filter_language_urls
from src.utils.version_utils import dedupe_versioned_urls
from src.utils.url_utils import (
    is_asset_url,
    is_url_within_scope,
    make_url_prefix,
    normalize_url,
    resolve_relative,
)


NOFOLLOW_RELS = frozenset({"nofollow", "ugc", "sponsored"})


def extract_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#"):
            continue
        rel_values = set(a.get("rel", []))
        if rel_values & NOFOLLOW_RELS:
            continue
        url = resolve_relative(page_url, href)
        if is_asset_url(url):
            continue
        links.append(url)

    return links


async def crawl_links(
    base_url: str,
    client: HttpClient,
    robots: RobotsParser,
    options: GetDocsRequest,
    ethics: EthicsContext,
    on_progress: ProgressCallback | None = None,
) -> list[DocPage]:
    prefix = make_url_prefix(base_url)
    bot_name = settings.BOT_NAME
    pages: list[DocPage] = []
    seen: set[str] = {normalize_url(base_url)}
    queue: list[list[str]] = [[normalize_url(base_url)]]

    for depth in range(options.max_depth):
        if depth >= len(queue) or not queue[depth]:
            break

        allowed, robots_count, signal_count = filter_urls_by_robots(
            queue[depth], robots
        )
        ethics.pages_filtered_by_robots_txt += robots_count
        ethics.pages_filtered_by_content_signal += signal_count

        next_urls: list[str] = []

        for url in allowed:
            if len(pages) >= options.max_pages:
                break

            try:
                resp = await client.get(
                    url, follow_redirects=True, timeout=options.timeout
                )
            except httpx.HTTPError:
                continue

            if resp.status_code != 200:
                continue
            if "text/html" not in resp.headers.get("content-type", ""):
                continue

            if is_response_blocked(resp, bot_name=bot_name):
                logger.info(f"Blocked by robots tag directive: {url}")
                ethics.pages_filtered_by_robots_tags += 1
                continue

            html = resp.text

            blocked, nofollow_meta = check_html_meta(html, bot_name=bot_name)
            if blocked:
                logger.info(f"Blocked by robots tag directive: {url}")
                ethics.pages_filtered_by_robots_tags += 1
                continue

            page = html_to_doc_page(
                url=url, html=html, source_method=SourceMethod.LINK_CRAWL
            )
            if page.content:
                pages.append(page)
                if on_progress:
                    await on_progress(len(pages), None)

            if not nofollow_meta and not has_nofollow_header(resp, bot_name=bot_name):
                for link in extract_links(html, url):
                    norm = normalize_url(link)
                    if norm not in seen and is_url_within_scope(norm, prefix):
                        seen.add(norm)
                        next_urls.append(norm)

        if len(pages) >= options.max_pages:
            break

        if next_urls:
            next_urls = filter_language_urls(next_urls, base_url)
            next_urls = dedupe_versioned_urls(next_urls)
            queue.append(next_urls)

    return pages
