from dataclasses import dataclass
import xml.etree.ElementTree as ET
import httpx

from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.utils.http_client import get_with_retry
from src.utils.lang_utils import ENGLISH_FOLDERS, is_lang_code
from src.utils.rate_limiter import fetch_with_rate_limit
from src.utils.url_utils import (
    extract_path,
    is_url_within_scope,
    make_url_prefix,
    url_path_parents,
)


@dataclass
class SitemapEntry:
    loc: str
    lastmod: str | None = None


def _strip_ns(tag: str) -> str:
    """Remove XML namespace prefix: '{http://...}urlset' -> 'urlset'."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _parse_entry(elem: ET.Element) -> SitemapEntry | None:
    loc = None
    lastmod = None
    for child in elem:
        tag = _strip_ns(child.tag)
        if tag == "loc" and child.text:
            loc = child.text.strip()
        elif tag == "lastmod" and child.text:
            lastmod = child.text.strip()
    if loc:
        return SitemapEntry(loc=loc, lastmod=lastmod)
    return None


class SitemapParser:
    """(urlset XML, sitemapindex XML, or plain text)."""

    def __init__(self, content: str):
        self._urls: list[SitemapEntry] = []
        self._sub_sitemaps: list[SitemapEntry] = []
        self._parse(content)

    def _parse(self, content: str) -> None:
        content = content.strip()
        if not content:
            return

        if not content.startswith("<"):
            self._parse_plain_text(content)
            return

        self._parse_xml(content)

    def _parse_plain_text(self, content: str) -> None:
        for line in content.splitlines():
            url = line.strip()
            if url and not url.startswith("#"):
                self._urls.append(SitemapEntry(loc=url))

    def _parse_xml(self, content: str) -> None:
        root = ET.fromstring(content)
        tag = _strip_ns(root.tag)

        if tag == "urlset":
            for child in root:
                if _strip_ns(child.tag) == "url":
                    entry = _parse_entry(child)
                    if entry:
                        self._urls.append(entry)

        elif tag == "sitemapindex":
            for child in root:
                if _strip_ns(child.tag) == "sitemap":
                    entry = _parse_entry(child)
                    if entry:
                        self._sub_sitemaps.append(entry)

    def get_urls(self) -> list[SitemapEntry]:
        return list(self._urls)

    def get_sub_sitemaps(self) -> list[SitemapEntry]:
        return list(self._sub_sitemaps)

    def is_index(self) -> bool:
        return len(self._sub_sitemaps) > 0


def _filter_by_scope(urls: list[str], base_url: str | None) -> list[str]:
    if not base_url:
        return urls
    prefix = make_url_prefix(base_url)
    return [u for u in urls if is_url_within_scope(u, prefix)]


async def fetch_sitemap_urls(
    sitemap_url: str,
    client: httpx.AsyncClient,
    timeout: float = 10,
    max_depth: int = 3,
    base_url: str | None = None,
    max_concurrent: int = 5,
    delay_seconds: float = 1.5,
) -> list[str]:
    if max_depth <= 0:
        return []

    try:
        resp = await get_with_retry(
            client, sitemap_url, follow_redirects=True, timeout=timeout
        )
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    try:
        parser = SitemapParser(resp.text)
    except ET.ParseError:
        return []

    if not parser.is_index():
        return _filter_by_scope([entry.loc for entry in parser.get_urls()], base_url)

    subs = parser.get_sub_sitemaps()
    if base_url:
        prefix = make_url_prefix(base_url)
        subs = [s for s in subs if is_url_within_scope(s.loc, prefix)]

    if not subs:
        return []

    async def _fetch_sub(sub: SitemapEntry) -> list[str]:
        return await fetch_sitemap_urls(
            sub.loc,
            client,
            timeout,
            max_depth - 1,
            base_url=base_url,
            max_concurrent=max_concurrent,
            delay_seconds=delay_seconds,
        )

    outcomes = await fetch_with_rate_limit(
        subs,
        _fetch_sub,
        max_concurrent=max_concurrent,
        delay_seconds=delay_seconds,
    )

    urls: list[str] = []
    for _sub, result in outcomes:
        if isinstance(result, Exception):
            continue
        urls.extend(result)
    return urls


def _relative_parts(url: str, base_path: str) -> list[str]:
    path = extract_path(url)
    if path.startswith(base_path):
        path = path[len(base_path) :]
    return [p for p in path.strip("/").split("/") if p]


def _has_lang_segment(parts: list[str]) -> str | None:
    for p in parts:
        if is_lang_code(p):
            return p
    return None


def _filter_language_urls(urls: list[str], base_url: str) -> list[str]:
    if not urls:
        return urls

    base_path = extract_path(base_url).rstrip("/") + "/"

    all_lang_codes: set[str] = set()
    for url in urls:
        parts = _relative_parts(url, base_path)
        lang = _has_lang_segment(parts)
        if lang:
            all_lang_codes.add(lang)

    if len(all_lang_codes) < 2:
        return urls

    for enf in ENGLISH_FOLDERS:
        if enf in all_lang_codes:
            return [u for u in urls if enf in _relative_parts(u, base_path)]

    return [u for u in urls if _has_lang_segment(_relative_parts(u, base_path)) is None]


async def collect_sitemap_urls(
    base_url: str,
    client: httpx.AsyncClient,
    robots: RobotsParser | None = None,
    timeout: float = 15,
    max_depth: int = 3,
    max_concurrent: int = 5,
    delay_seconds: float = 1.5,
) -> list[str]:
    if robots is None:
        robots = await fetch_robots_txt(base_url, client, timeout)

    sitemap_sources = robots.get_sitemaps()
    all_page_urls: list[str] = []

    if sitemap_sources:
        for src in sitemap_sources:
            all_page_urls.extend(
                await fetch_sitemap_urls(
                    src,
                    client,
                    timeout,
                    max_depth,
                    base_url=base_url,
                    max_concurrent=max_concurrent,
                    delay_seconds=delay_seconds,
                )
            )

    if not all_page_urls:
        for parent in url_path_parents(base_url):
            candidate = parent.rstrip("/") + "/sitemap.xml"
            urls = await fetch_sitemap_urls(
                candidate,
                client,
                timeout,
                max_depth,
                base_url=base_url,
                max_concurrent=max_concurrent,
                delay_seconds=delay_seconds,
            )
            if urls:
                all_page_urls.extend(urls)
                break

    return _filter_language_urls(all_page_urls, base_url)
