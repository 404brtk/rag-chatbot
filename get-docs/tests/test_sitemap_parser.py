import httpx
import pytest

from src.core.robots_parser import RobotsParser
from src.core.sitemap_parser import (
    SitemapParser,
    collect_sitemap_urls,
    fetch_sitemap_urls,
)
from tests.conftest import mock_response


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _urlset_xml(*urls: str, ns: bool = True) -> str:
    """Helper to build a <urlset> XML string."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for u in urls:
        entries += f"  <url><loc>{u}</loc></url>\n"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset{ns_attr}>\n{entries}</urlset>'
    )


def _urlset_xml_with_lastmod(urls: list[tuple[str, str]], ns: bool = True) -> str:
    """Helper for urlset with lastmod values."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for loc, lastmod in urls:
        entries += f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>\n"
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset{ns_attr}>\n{entries}</urlset>'
    )


def _index_xml(*sitemaps: str, ns: bool = True) -> str:
    """Helper to build a <sitemapindex> XML string."""
    ns_attr = f' xmlns="{SITEMAP_NS}"' if ns else ""
    entries = ""
    for s in sitemaps:
        entries += f"  <sitemap><loc>{s}</loc></sitemap>\n"
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex{ns_attr}>\n{entries}</sitemapindex>'


class TestUrlset:
    def test_single_url(self):
        xml = _urlset_xml("https://example.com/page1")
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page1"
        assert urls[0].lastmod is None

    def test_multiple_urls(self):
        xml = _urlset_xml(
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        )
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 3
        assert [u.loc for u in urls] == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

    def test_with_lastmod(self):
        xml = _urlset_xml_with_lastmod(
            [
                ("https://example.com/page1", "2024-01-15"),
                ("https://example.com/page2", "2024-06-20T10:30:00+00:00"),
            ]
        )
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 2
        assert urls[0].lastmod == "2024-01-15"
        assert urls[1].lastmod == "2024-06-20T10:30:00+00:00"

    def test_not_an_index(self):
        parser = SitemapParser(_urlset_xml("https://example.com/"))
        assert parser.is_index() is False
        assert parser.get_sub_sitemaps() == []

    def test_ignores_changefreq_and_priority(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>https://example.com/page</loc>
    <lastmod>2024-01-01</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page"
        assert urls[0].lastmod == "2024-01-01"

    def test_empty_loc_skipped(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><loc></loc></url>
  <url><loc>https://example.com/valid</loc></url>
</urlset>"""
        parser = SitemapParser(xml)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/valid"

    def test_missing_loc_skipped(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url><lastmod>2024-01-01</lastmod></url>
  <url><loc>https://example.com/ok</loc></url>
</urlset>"""
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 1
        assert parser.get_urls()[0].loc == "https://example.com/ok"


class TestSitemapIndex:
    def test_single_sub_sitemap(self):
        xml = _index_xml("https://example.com/sitemap-docs.xml")
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 1
        assert subs[0].loc == "https://example.com/sitemap-docs.xml"

    def test_multiple_sub_sitemaps(self):
        xml = _index_xml(
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
            "https://example.com/sitemap3.xml",
        )
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 3
        assert [s.loc for s in subs] == [
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
            "https://example.com/sitemap3.xml",
        ]

    def test_is_index(self):
        parser = SitemapParser(_index_xml("https://example.com/sitemap.xml"))
        assert parser.is_index() is True
        assert parser.get_urls() == []

    def test_with_lastmod(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="{SITEMAP_NS}">
  <sitemap>
    <loc>https://example.com/sitemap-blog.xml</loc>
    <lastmod>2024-03-10</lastmod>
  </sitemap>
</sitemapindex>"""
        parser = SitemapParser(xml)
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 1
        assert subs[0].loc == "https://example.com/sitemap-blog.xml"
        assert subs[0].lastmod == "2024-03-10"


class TestPlainText:
    def test_basic(self):
        content = "https://example.com/a\nhttps://example.com/b\nhttps://example.com/c"
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert len(urls) == 3
        assert [u.loc for u in urls] == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]
        assert all(u.lastmod is None for u in urls)

    def test_blank_lines_skipped(self):
        content = "https://example.com/a\n\n\nhttps://example.com/b\n"
        parser = SitemapParser(content)
        assert len(parser.get_urls()) == 2

    def test_comments_skipped(self):
        content = "# this is a comment\nhttps://example.com/page\n# another comment"
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert len(urls) == 1
        assert urls[0].loc == "https://example.com/page"

    def test_whitespace_trimmed(self):
        content = "  https://example.com/a  \n  https://example.com/b  "
        parser = SitemapParser(content)
        urls = parser.get_urls()
        assert urls[0].loc == "https://example.com/a"
        assert urls[1].loc == "https://example.com/b"

    def test_not_an_index(self):
        parser = SitemapParser("https://example.com/page")
        assert parser.is_index() is False


class TestEdgeCases:
    def test_empty_string(self):
        parser = SitemapParser("")
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []
        assert parser.is_index() is False

    def test_whitespace_only(self):
        parser = SitemapParser("   \n\n  \n  ")
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []

    def test_malformed_xml_raises(self):
        with pytest.raises(Exception):
            SitemapParser("<urlset><url><loc>broken")

    def test_without_namespace(self):
        xml = _urlset_xml("https://example.com/page", ns=False)
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 1
        assert parser.get_urls()[0].loc == "https://example.com/page"

    def test_index_without_namespace(self):
        xml = _index_xml("https://example.com/sitemap.xml", ns=False)
        parser = SitemapParser(xml)
        assert parser.is_index() is True
        assert parser.get_sub_sitemaps()[0].loc == "https://example.com/sitemap.xml"

    def test_loc_with_whitespace_trimmed(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>
      https://example.com/page
    </loc>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        assert parser.get_urls()[0].loc == "https://example.com/page"

    def test_returns_defensive_copies(self):
        parser = SitemapParser(_urlset_xml("https://example.com/"))
        urls1 = parser.get_urls()
        urls2 = parser.get_urls()
        assert urls1 == urls2
        assert urls1 is not urls2

    def test_unknown_root_tag_produces_empty(self):
        xml = '<?xml version="1.0"?><something><url><loc>https://example.com/</loc></url></something>'
        parser = SitemapParser(xml)
        assert parser.get_urls() == []
        assert parser.get_sub_sitemaps() == []
        assert parser.is_index() is False

    def test_large_urlset(self):
        urls = [f"https://example.com/page{i}" for i in range(500)]
        xml = _urlset_xml(*urls)
        parser = SitemapParser(xml)
        assert len(parser.get_urls()) == 500
        assert parser.get_urls()[0].loc == "https://example.com/page0"
        assert parser.get_urls()[499].loc == "https://example.com/page499"


class TestCombined:
    def test_realistic_docs_sitemap(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}">
  <url>
    <loc>https://docs.example.com/</loc>
    <lastmod>2024-06-01</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://docs.example.com/getting-started</loc>
    <lastmod>2024-05-20</lastmod>
  </url>
  <url>
    <loc>https://docs.example.com/api-reference</loc>
  </url>
</urlset>"""
        parser = SitemapParser(xml)
        assert parser.is_index() is False
        urls = parser.get_urls()
        assert len(urls) == 3
        assert urls[0].loc == "https://docs.example.com/"
        assert urls[0].lastmod == "2024-06-01"
        assert urls[1].lastmod == "2024-05-20"
        assert urls[2].lastmod is None

    def test_realistic_sitemap_index(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="{SITEMAP_NS}">
  <sitemap>
    <loc>https://example.com/sitemap-docs.xml</loc>
    <lastmod>2024-06-01</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/sitemap-blog.xml</loc>
    <lastmod>2024-05-15</lastmod>
  </sitemap>
  <sitemap>
    <loc>https://example.com/sitemap-api.xml</loc>
  </sitemap>
</sitemapindex>"""
        parser = SitemapParser(xml)
        assert parser.is_index() is True
        subs = parser.get_sub_sitemaps()
        assert len(subs) == 3
        assert subs[0].loc == "https://example.com/sitemap-docs.xml"
        assert subs[0].lastmod == "2024-06-01"
        assert subs[2].lastmod is None
        assert parser.get_urls() == []


def _mock_response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/xml; charset=utf-8",
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com"),
    )


class TestFetchSitemapUrls:
    @pytest.mark.asyncio
    async def test_simple_urlset(self, mocker):
        xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/a</loc></url>
            <url><loc>https://example.com/b</loc></url>
        </urlset>"""
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=_mock_response(text=xml))

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == ["https://example.com/a", "https://example.com/b"]

    @pytest.mark.asyncio
    async def test_sitemapindex_recurses(self, mocker):
        index_xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/sitemap-1.xml</loc></sitemap>
        </sitemapindex>"""
        child_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
        </urlset>"""
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            side_effect=[_mock_response(text=index_xml), _mock_response(text=child_xml)]
        )

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == ["https://example.com/page1"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=_mock_response(status_code=404))

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=httpx.ConnectError("fail"))

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == []

    @pytest.mark.asyncio
    async def test_max_depth_stops_recursion(self, mocker):
        index_xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/deeper.xml</loc></sitemap>
        </sitemapindex>"""
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=_mock_response(text=index_xml))

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml", client, max_depth=1
        )
        assert urls == []


class TestCollectSitemapUrls:
    @pytest.mark.asyncio
    async def test_returns_urls_from_robots_sitemap(self, mocker):
        robots = RobotsParser("Sitemap: https://example.com/sitemap.xml")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/intro</loc></url>
            <url><loc>https://example.com/docs/guide</loc></url>
        </urlset>"""

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text=sitemap_xml),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert urls == [
            "https://example.com/docs/intro",
            "https://example.com/docs/guide",
        ]

    @pytest.mark.asyncio
    async def test_falls_back_to_default_sitemap_xml(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page</loc></url>
        </urlset>"""

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text=sitemap_xml),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert urls == ["https://example.com/page"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_sitemap_found(self, mocker):
        robots = RobotsParser("")

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(status_code=404),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert urls == []

    @pytest.mark.asyncio
    async def test_returns_raw_urls_without_filtering(self, mocker):
        """collect_sitemap_urls returns all URLs -- filtering is done by the caller."""
        robots = RobotsParser("User-agent: *\nDisallow: /private/")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/public</loc></url>
            <url><loc>https://example.com/private/secret</loc></url>
        </urlset>"""

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text=sitemap_xml),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert len(urls) == 2
        assert "https://example.com/private/secret" in urls

    @pytest.mark.asyncio
    async def test_passes_max_depth_to_sitemap_parser(self, mocker):
        robots = RobotsParser("")

        mock_fetch = mocker.patch(
            "src.core.sitemap_parser.fetch_sitemap_urls",
            return_value=["https://example.com/page"],
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        await collect_sitemap_urls(
            "https://example.com", client, robots=robots, max_depth=5
        )

        assert mock_fetch.call_args[0][3] == 5


class TestSitemapFallbackPathWalking:
    @pytest.mark.asyncio
    async def test_finds_sitemap_at_subpath(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/intro</loc></url>
        </urlset>"""

        def side_effect(url, **kw):
            if url == "https://example.com/docs/sitemap.xml":
                return mock_response(text=sitemap_xml)
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs", client, robots=robots
        )
        assert urls == ["https://example.com/docs/intro"]

    @pytest.mark.asyncio
    async def test_finds_sitemap_at_root_from_deep_url(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/en/intro</loc></url>
        </urlset>"""

        def side_effect(url, **kw):
            if url == "https://example.com/sitemap.xml":
                return mock_response(text=sitemap_xml)
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs/en", client, robots=robots
        )
        assert urls == ["https://example.com/docs/en/intro"]

    @pytest.mark.asyncio
    async def test_stops_after_first_successful_sitemap(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/page1</loc></url>
        </urlset>"""

        def side_effect(url, **kw):
            if url == "https://example.com/docs/sitemap.xml":
                return mock_response(text=sitemap_xml)
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs/sub", client, robots=robots
        )
        assert urls == ["https://example.com/docs/page1"]
        called_urls = [call.args[0] for call in client.get.call_args_list]
        assert "https://example.com/sitemap.xml" not in called_urls


class TestFilterLanguageUrls:
    def test_flat_no_english_prefix(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://opencode.ai/docs"
        urls = [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/permissions",
            "https://opencode.ai/docs/hooks",
            "https://opencode.ai/docs/de",
            "https://opencode.ai/docs/fr",
            "https://opencode.ai/docs/es",
            "https://opencode.ai/docs/ja",
            "https://opencode.ai/docs/ko",
            "https://opencode.ai/docs/zh-cn",
            "https://opencode.ai/docs/zh-tw",
            "https://opencode.ai/docs/it",
            "https://opencode.ai/docs/da",
        ]
        result = _filter_language_urls(urls, base)
        assert "https://opencode.ai/docs/config" in result
        assert "https://opencode.ai/docs/permissions" in result
        assert "https://opencode.ai/docs/hooks" in result
        for lang in ("de", "fr", "es", "ja", "ko", "zh-cn", "zh-tw", "it", "da"):
            assert f"https://opencode.ai/docs/{lang}" not in result

    def test_flat_with_nested_lang_pages(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://opencode.ai/docs"
        urls = [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/guide",
            "https://opencode.ai/docs/de",
            "https://opencode.ai/docs/de/config",
            "https://opencode.ai/docs/fr",
            "https://opencode.ai/docs/fr/guide",
        ]
        result = _filter_language_urls(urls, base)
        assert result == [
            "https://opencode.ai/docs/config",
            "https://opencode.ai/docs/guide",
        ]

    def test_nested_english_folder(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com"
        urls = [
            "https://example.com/en/guide",
            "https://example.com/en/api",
            "https://example.com/fr/guide",
            "https://example.com/fr/api",
            "https://example.com/de/guide",
        ]
        result = _filter_language_urls(urls, base)
        assert result == [
            "https://example.com/en/guide",
            "https://example.com/en/api",
        ]

    def test_nested_en_us_folder(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/en-us/intro",
            "https://example.com/docs/en-us/guide",
            "https://example.com/docs/ja/intro",
            "https://example.com/docs/ja/guide",
        ]
        result = _filter_language_urls(urls, base)
        assert result == [
            "https://example.com/docs/en-us/intro",
            "https://example.com/docs/en-us/guide",
        ]

    def test_empty_list(self):
        from src.core.sitemap_parser import _filter_language_urls

        assert _filter_language_urls([], "https://example.com") == []

    def test_no_language_codes(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs/guide",
            "https://example.com/docs/api",
        ]
        result = _filter_language_urls(urls, base)
        assert result == urls

    def test_single_language_code_not_filtered(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs/go",
        ]
        result = _filter_language_urls(urls, base)
        assert result == urls

    def test_similar_prefix_not_stripped(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/config",
            "https://example.com/docs-extra/page",
            "https://example.com/docs/de",
            "https://example.com/docs/fr",
        ]
        result = _filter_language_urls(urls, base)
        assert "https://example.com/docs-extra/page" in result
        assert "https://example.com/docs/config" in result
        assert "https://example.com/docs/de" not in result
        assert "https://example.com/docs/fr" not in result

    def test_last_segment_detected(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com/docs"
        urls = [
            "https://example.com/docs/intro",
            "https://example.com/docs/de",
            "https://example.com/docs/fr",
        ]
        result = _filter_language_urls(urls, base)
        assert result == ["https://example.com/docs/intro"]

    def test_preserves_order(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com"
        urls = [
            "https://example.com/en/c",
            "https://example.com/fr/a",
            "https://example.com/en/a",
            "https://example.com/de/b",
            "https://example.com/en/b",
        ]
        result = _filter_language_urls(urls, base)
        assert result == [
            "https://example.com/en/c",
            "https://example.com/en/a",
            "https://example.com/en/b",
        ]

    def test_deeply_nested_lang_folder(self):
        from src.core.sitemap_parser import _filter_language_urls

        base = "https://example.com"
        urls = [
            "https://example.com/product/docs/en/guide",
            "https://example.com/product/docs/en/api",
            "https://example.com/product/docs/fr/guide",
            "https://example.com/product/docs/de/guide",
        ]
        result = _filter_language_urls(urls, base)
        assert result == [
            "https://example.com/product/docs/en/guide",
            "https://example.com/product/docs/en/api",
        ]
