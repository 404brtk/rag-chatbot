import httpx
import pytest

from src.core.robots_parser import RobotsParser
from src.core.sitemap_parser import (
    SitemapEntry,
    SitemapParser,
    collect_sitemap_urls,
    fetch_sitemap_urls,
)
from src.core.sitemap_parser import _dedupe_versioned_sitemaps
from tests.conftest import mock_http_client, mock_response


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
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(text=xml))

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
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            side_effect=[_mock_response(text=index_xml), _mock_response(text=child_xml)]
        )

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == ["https://example.com/page1"]

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(status_code=404))

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_error(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=httpx.ConnectError("fail"))

        urls = await fetch_sitemap_urls("https://example.com/sitemap.xml", client)
        assert urls == []

    @pytest.mark.asyncio
    async def test_max_depth_stops_recursion(self, mocker):
        index_xml = """<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap><loc>https://example.com/deeper.xml</loc></sitemap>
        </sitemapindex>"""
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(text=index_xml))

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml", client, max_depth=1
        )
        assert urls == []

    @pytest.mark.asyncio
    async def test_filters_sub_sitemaps_by_base_url(self, mocker):
        index_xml = _index_xml(
            "https://example.com/docs/sitemap-1.xml",
            "https://example.com/blog/sitemap-1.xml",
            "https://example.com/docs/sitemap-2.xml",
            "https://learn.example.com/sitemap.xml",
        )
        docs_xml_1 = _urlset_xml("https://example.com/docs/intro")
        docs_xml_2 = _urlset_xml("https://example.com/docs/guide")

        def side_effect(url, **kw):
            responses = {
                "https://example.com/sitemap.xml": _mock_response(text=index_xml),
                "https://example.com/docs/sitemap-1.xml": _mock_response(
                    text=docs_xml_1
                ),
                "https://example.com/docs/sitemap-2.xml": _mock_response(
                    text=docs_xml_2
                ),
            }
            return responses.get(url, _mock_response(status_code=404))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml",
            client,
            base_url="https://example.com/docs/",
        )
        assert sorted(urls) == [
            "https://example.com/docs/guide",
            "https://example.com/docs/intro",
        ]
        called_urls = [call.args[0] for call in inner.get.call_args_list]
        assert "https://example.com/blog/sitemap-1.xml" not in called_urls
        assert "https://learn.example.com/sitemap.xml" not in called_urls

    @pytest.mark.asyncio
    async def test_filters_final_urls_by_scope(self, mocker):
        xml = _urlset_xml(
            "https://example.com/docs/intro",
            "https://example.com/blog/post",
            "https://example.com/docs/guide",
        )
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(text=xml))

        urls = await fetch_sitemap_urls(
            "https://example.com/docs/sitemap.xml",
            client,
            base_url="https://example.com/docs/",
        )
        assert urls == [
            "https://example.com/docs/intro",
            "https://example.com/docs/guide",
        ]

    @pytest.mark.asyncio
    async def test_multi_level_filtering(self, mocker):
        root_index = _index_xml(
            "https://example.com/docs/sitemap-index.xml",
            "https://example.com/blog/sitemap.xml",
        )
        docs_index = _index_xml(
            "https://example.com/docs/manual/sitemap.xml",
            "https://example.com/community/sitemap.xml",
        )
        manual_xml = _urlset_xml("https://example.com/docs/manual/page1")

        def side_effect(url, **kw):
            responses = {
                "https://example.com/sitemap.xml": _mock_response(text=root_index),
                "https://example.com/docs/sitemap-index.xml": _mock_response(
                    text=docs_index
                ),
                "https://example.com/docs/manual/sitemap.xml": _mock_response(
                    text=manual_xml
                ),
            }
            return responses.get(url, _mock_response(status_code=404))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml",
            client,
            base_url="https://example.com/docs/",
        )
        assert urls == ["https://example.com/docs/manual/page1"]
        called_urls = [call.args[0] for call in inner.get.call_args_list]
        assert "https://example.com/blog/sitemap.xml" not in called_urls
        assert "https://example.com/community/sitemap.xml" not in called_urls

    @pytest.mark.asyncio
    async def test_parent_sitemap_recursed_for_deep_scope(self, mocker):
        root_index = _index_xml(
            "https://example.com/sitemap-pages.xml",
            "https://example.com/community/sitemap.xml",
            "https://example.com/docs/sitemap-index.xml",
        )
        docs_index = _index_xml(
            "https://example.com/docs/drivers/node/current/sitemap.xml",
            "https://example.com/docs/drivers/go/current/sitemap.xml",
            "https://example.com/docs/manual/sitemap.xml",
            "https://example.com/docs/kubernetes/current/sitemap.xml",
        )
        node_xml = _urlset_xml(
            "https://example.com/docs/drivers/node/current/intro",
            "https://example.com/docs/drivers/node/current/quickstart",
        )
        go_xml = _urlset_xml(
            "https://example.com/docs/drivers/go/current/intro",
        )

        def side_effect(url, **kw):
            responses = {
                "https://example.com/sitemap.xml": _mock_response(text=root_index),
                "https://example.com/docs/sitemap-index.xml": _mock_response(
                    text=docs_index
                ),
                "https://example.com/docs/drivers/node/current/sitemap.xml": _mock_response(
                    text=node_xml
                ),
                "https://example.com/docs/drivers/go/current/sitemap.xml": _mock_response(
                    text=go_xml
                ),
            }
            return responses.get(url, _mock_response(status_code=404))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml",
            client,
            base_url="https://example.com/docs/drivers/",
        )

        assert sorted(urls) == [
            "https://example.com/docs/drivers/go/current/intro",
            "https://example.com/docs/drivers/node/current/intro",
            "https://example.com/docs/drivers/node/current/quickstart",
        ]
        called_urls = [call.args[0] for call in inner.get.call_args_list]
        assert "https://example.com/docs/sitemap-index.xml" in called_urls
        assert "https://example.com/community/sitemap.xml" not in called_urls
        assert "https://example.com/docs/manual/sitemap.xml" not in called_urls
        assert (
            "https://example.com/docs/kubernetes/current/sitemap.xml" not in called_urls
        )

    @pytest.mark.asyncio
    async def test_no_base_url_fetches_all(self, mocker):
        index_xml = _index_xml(
            "https://example.com/docs/sitemap.xml",
            "https://example.com/blog/sitemap.xml",
        )
        docs_xml = _urlset_xml("https://example.com/docs/page")
        blog_xml = _urlset_xml("https://example.com/blog/post")

        def side_effect(url, **kw):
            responses = {
                "https://example.com/sitemap.xml": _mock_response(text=index_xml),
                "https://example.com/docs/sitemap.xml": _mock_response(text=docs_xml),
                "https://example.com/blog/sitemap.xml": _mock_response(text=blog_xml),
            }
            return responses.get(url, _mock_response(status_code=404))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await fetch_sitemap_urls(
            "https://example.com/sitemap.xml",
            client,
            base_url=None,
        )
        assert sorted(urls) == [
            "https://example.com/blog/post",
            "https://example.com/docs/page",
        ]


class TestDedupeVersionedSitemaps:
    def test_prefers_current_over_versions(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/kubernetes/current/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/kubernetes/v1.6/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/kubernetes/v1.5/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/kubernetes/v1.4/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        assert len(result) == 1
        assert (
            result[0].loc == "https://example.com/docs/kubernetes/current/sitemap.xml"
        )

    def test_picks_highest_version_when_no_current(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/ef/v8.1/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/ef/v9.0/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/ef/v8.4/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        assert len(result) == 1
        assert result[0].loc == "https://example.com/docs/ef/v9.0/sitemap.xml"

    def test_keeps_unversioned_sitemaps(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/compass/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/shell/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        assert len(result) == 2

    def test_mixed_versioned_and_unversioned(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/kubernetes/current/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/kubernetes/v1.6/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/compass/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/ef/v9.0/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/ef/v8.4/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        locs = {e.loc for e in result}
        assert len(result) == 3
        assert "https://example.com/docs/kubernetes/current/sitemap.xml" in locs
        assert "https://example.com/docs/compass/sitemap.xml" in locs
        assert "https://example.com/docs/ef/v9.0/sitemap.xml" in locs

    def test_handles_vx_suffix(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/driver/current/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/driver/v6.x/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        assert len(result) == 1
        assert result[0].loc == "https://example.com/docs/driver/current/sitemap.xml"

    def test_multiple_products_each_deduped(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/a/current/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/a/v1.0/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/b/v3.0/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/b/v2.0/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        locs = {e.loc for e in result}
        assert len(result) == 2
        assert "https://example.com/docs/a/current/sitemap.xml" in locs
        assert "https://example.com/docs/b/v3.0/sitemap.xml" in locs

    def test_keyword_substring_not_false_positive(self):
        subs = [
            SitemapEntry(loc="https://example.com/docs/main-concepts/v2.0/sitemap.xml"),
            SitemapEntry(loc="https://example.com/docs/main-concepts/v1.0/sitemap.xml"),
        ]
        result = _dedupe_versioned_sitemaps(subs)
        assert len(result) == 1
        assert (
            result[0].loc == "https://example.com/docs/main-concepts/v2.0/sitemap.xml"
        )


class TestCollectSitemapUrls:
    @pytest.mark.asyncio
    async def test_returns_urls_from_robots_sitemap(self, mocker):
        robots = RobotsParser("Sitemap: https://example.com/sitemap.xml")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/intro</loc></url>
            <url><loc>https://example.com/docs/guide</loc></url>
        </urlset>"""

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(text=sitemap_xml),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert urls == ["https://example.com/page"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_sitemap_found(self, mocker):
        robots = RobotsParser("")

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(text=sitemap_xml),
        )

        urls = await collect_sitemap_urls("https://example.com", client, robots=robots)
        assert len(urls) == 2
        assert "https://example.com/private/secret" in urls

    @pytest.mark.asyncio
    async def test_fallback_when_sitemapindex_has_zero_scope_matches(self, mocker):
        robots = RobotsParser("Sitemap: https://example.com/sitemap.xml")

        root_index = _index_xml(
            "https://example.com/blog/sitemap.xml",
            "https://example.com/community/sitemap.xml",
        )
        fallback_xml = _urlset_xml("https://example.com/docs/intro")

        def side_effect(url, **kw):
            if url == "https://example.com/sitemap.xml":
                return mock_response(text=root_index)
            if url == "https://example.com/docs/sitemap.xml":
                return mock_response(text=fallback_xml)
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs/",
            client,
            robots=robots,
        )
        assert urls == ["https://example.com/docs/intro"]


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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs/en", client, robots=robots
        )
        assert urls == ["https://example.com/docs/en/intro"]

    @pytest.mark.asyncio
    async def test_stops_after_first_successful_sitemap(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/sub/page1</loc></url>
            <url><loc>https://example.com/docs/other</loc></url>
        </urlset>"""

        def side_effect(url, **kw):
            if url == "https://example.com/docs/sitemap.xml":
                return mock_response(text=sitemap_xml)
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=side_effect)

        urls = await collect_sitemap_urls(
            "https://example.com/docs/sub", client, robots=robots
        )
        assert urls == ["https://example.com/docs/sub/page1"]
        called_urls = [call.args[0] for call in inner.get.call_args_list]
        assert "https://example.com/sitemap.xml" not in called_urls
