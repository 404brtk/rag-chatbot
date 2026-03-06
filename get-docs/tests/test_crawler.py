import httpx
import pytest

from src.core.crawler import (
    CrawlError,
    CrawlPage,
    CrawlResult,
    crawl_sitemap,
    _fetch_page,
)
from src.core.robots_parser import RobotsParser
from tests.conftest import html_page, mock_response


class TestFetchPage:
    @pytest.mark.asyncio
    async def test_success(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="<html>ok</html>")
        )

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html == "<html>ok</html>"
        assert error is None

    @pytest.mark.asyncio
    async def test_non_200_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=mock_response(status_code=403))

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html is None
        assert error == "HTTP 403"

    @pytest.mark.asyncio
    async def test_non_html_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="binary", content_type="application/pdf")
        )

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html is None
        assert "Not HTML" in error

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=httpx.ReadTimeout("slow"))

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html is None
        assert error == "Timeout"

    @pytest.mark.asyncio
    async def test_network_error_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=httpx.ConnectError("refused"))

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html is None
        assert "refused" in error


class TestCrawlSitemap:
    @pytest.mark.asyncio
    async def test_fetches_sitemap_pages(self, mocker):
        robots_txt = "Sitemap: https://example.com/sitemap.xml"
        robots = RobotsParser(robots_txt)

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/docs/intro</loc></url>
            <url><loc>https://example.com/docs/guide</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/docs/intro": mock_response(text=html_page("Intro")),
            "https://example.com/docs/guide": mock_response(text=html_page("Guide")),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 2
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_default_sitemap_xml(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/page": mock_response(text=html_page("Page")),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_respects_robots_disallow(self, mocker):
        robots = RobotsParser("User-agent: *\nDisallow: /private/")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/public</loc></url>
            <url><loc>https://example.com/private/secret</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/public": mock_response(text=html_page("Public")),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://example.com/public"

    @pytest.mark.asyncio
    async def test_respects_max_pages(self, mocker):
        robots = RobotsParser("")

        urls_xml = "\n".join(
            f"<url><loc>https://example.com/p{i}</loc></url>" for i in range(50)
        )
        sitemap_xml = f"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            {urls_xml}
        </urlset>"""

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            side_effect=lambda url, **kw: (
                mock_response(text=sitemap_xml)
                if "sitemap" in url
                else mock_response(text=html_page("Page"))
            )
        )

        result = await crawl_sitemap(
            "https://example.com",
            client,
            robots=robots,
            max_pages=5,
            delay_seconds=0,
        )
        assert len(result.pages) <= 5

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page</loc></url>
            <url><loc>https://example.com/page</loc></url>
            <url><loc>https://example.com/page/</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/page": mock_response(text=html_page("Page")),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_records_fetch_errors(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/ok</loc></url>
            <url><loc>https://example.com/broken</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/ok": mock_response(text=html_page("OK")),
            "https://example.com/broken": mock_response(status_code=500),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 1
        assert len(result.errors) == 1
        assert "500" in result.errors[0].error

    @pytest.mark.asyncio
    async def test_skips_ai_input_disallowed(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nAllow: /\nContent-Signal: /private/ ai-input=no"
        )

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/public/page</loc></url>
            <url><loc>https://example.com/private/data</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
            "https://example.com/public/page": mock_response(text=html_page("Public")),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://example.com/public/page"

    @pytest.mark.asyncio
    async def test_global_ai_input_no(self, mocker):
        robots = RobotsParser("User-agent: *\nAllow: /\nContent-Signal: ai-input=no")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>"""

        responses = {
            "https://example.com/sitemap.xml": mock_response(text=sitemap_xml),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 0


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
            if url == "https://example.com/docs/intro":
                return mock_response(text=html_page("Intro"))
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=side_effect)

        result = await crawl_sitemap(
            "https://example.com/docs/en/home",
            client,
            robots=robots,
            delay_seconds=0,
        )
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://example.com/docs/intro"

    @pytest.mark.asyncio
    async def test_finds_sitemap_at_root_from_deep_url(self, mocker):
        robots = RobotsParser("")

        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page</loc></url>
        </urlset>"""

        def side_effect(url, **kw):
            if url == "https://example.com/sitemap.xml":
                return mock_response(text=sitemap_xml)
            if url == "https://example.com/page":
                return mock_response(text=html_page("Page"))
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=side_effect)

        result = await crawl_sitemap(
            "https://example.com/docs/en/home",
            client,
            robots=robots,
            delay_seconds=0,
        )
        assert len(result.pages) == 1


class TestDataclasses:
    def test_crawl_page_fields(self):
        p = CrawlPage(url="https://example.com", html="<html></html>")
        assert p.url == "https://example.com"

    def test_crawl_error_fields(self):
        e = CrawlError(url="https://example.com", error="timeout")
        assert e.error == "timeout"

    def test_crawl_result_defaults(self):
        r = CrawlResult()
        assert r.pages == []
        assert r.errors == []
