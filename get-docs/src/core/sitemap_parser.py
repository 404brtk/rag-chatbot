from dataclasses import dataclass
import xml.etree.ElementTree as ET


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
    """Extract loc and lastmod from a <url> or <sitemap> element."""
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
        """URLs from a <urlset> sitemap."""
        return list(self._urls)

    def get_sub_sitemaps(self) -> list[SitemapEntry]:
        """Sub-sitemap URLs from a <sitemapindex>."""
        return list(self._sub_sitemaps)

    def is_index(self) -> bool:
        """True if this was a sitemap index (contains sub-sitemaps, not pages)."""
        return len(self._sub_sitemaps) > 0
