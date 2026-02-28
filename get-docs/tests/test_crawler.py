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


def _mock_response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/html; charset=utf-8",
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com"),
    )


def _html_page(title: str) -> str:
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><main><h1>{title}</h1></main></body></html>"
    )


class TestFetchPage:
    @pytest.mark.asyncio
    async def test_success(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=_mock_response(text="<html>ok</html>")
        )

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html == "<html>ok</html>"
        assert error is None

    @pytest.mark.asyncio
    async def test_non_200_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=_mock_response(status_code=403))

        url, html, error = await _fetch_page("https://example.com", client, 10)
        assert html is None
        assert error == "HTTP 403"

    @pytest.mark.asyncio
    async def test_non_html_returns_error(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=_mock_response(text="binary", content_type="application/pdf")
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/docs/intro": _mock_response(text=_html_page("Intro")),
            "https://example.com/docs/guide": _mock_response(text=_html_page("Guide")),
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/page": _mock_response(text=_html_page("Page")),
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/public": _mock_response(text=_html_page("Public")),
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
                _mock_response(text=sitemap_xml)
                if "sitemap" in url
                else _mock_response(text=_html_page("Page"))
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/page": _mock_response(text=_html_page("Page")),
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/ok": _mock_response(text=_html_page("OK")),
            "https://example.com/broken": _mock_response(status_code=500),
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
            "https://example.com/public/page": _mock_response(
                text=_html_page("Public")
            ),
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
            "https://example.com/sitemap.xml": _mock_response(text=sitemap_xml),
        }
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=lambda url, **kw: responses[url])

        result = await crawl_sitemap(
            "https://example.com", client, robots=robots, delay_seconds=0
        )
        assert len(result.pages) == 0


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
