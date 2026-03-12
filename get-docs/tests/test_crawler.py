import httpx
import pytest

from src.core.crawler import (
    fetch_and_convert_urls,
    fetch_page_as_markdown,
    filter_urls_by_robots,
    html_to_doc_page,
    probe_and_fetch,
)
from src.core.robots_parser import RobotsParser
from src.models.enums import FetchMethod, SourceMethod
from src.models.requests import GetDocsOptions
from src.models.responses import EthicsContext
from tests.conftest import html_page, mock_response


class TestHtmlToDocPage:
    def test_extracts_title_and_markdown(self):
        html = html_page("Getting Started", "Welcome to the docs")
        page = html_to_doc_page(
            "https://example.com/start", html, SourceMethod.SITEMAP_CRAWL
        )
        assert page.title == "Getting Started"
        assert "Welcome to the docs" in page.content
        assert page.source_method == SourceMethod.SITEMAP_CRAWL

    def test_empty_html_returns_empty_markdown(self):
        page = html_to_doc_page(
            "https://example.com", "<html></html>", SourceMethod.LLMS_TXT
        )
        assert page.content == ""


class TestFetchPageAsMarkdown:
    @pytest.mark.asyncio
    async def test_content_negotiation_returns_markdown(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text="# Hello\nWorld",
                content_type="text/markdown; charset=utf-8",
            )
        )

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
        )
        assert page is not None
        assert page.content == "# Hello\nWorld"
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_md_url_probe_returns_raw_markdown(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(
                    text="<html>hi</html>",
                    content_type="text/html",
                )
            if call_count == 2:
                return mock_response(
                    text="# Raw Markdown\nContent here",
                    content_type="text/plain",
                )
            return mock_response(status_code=404)

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.SITEMAP_CRAWL,
        )
        assert page is not None
        assert page.content == "# Raw Markdown\nContent here"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_html_extraction(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Fallback Page", "Fallback content"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.SITEMAP_CRAWL,
        )
        assert page is not None
        assert "Fallback content" in page.content
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_when_all_fail(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=mock_response(status_code=404))

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.SITEMAP_CRAWL,
        )
        assert page is None

    @pytest.mark.asyncio
    async def test_md_url_skips_content_negotiation(self, mocker):
        urls_fetched: list[str] = []

        async def mock_get(url, **kwargs):
            urls_fetched.append(url)
            return mock_response(
                text="# Markdown Content\nHello",
                content_type="text/plain",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://docs.stripe.com/connect.md",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
        )
        assert page is not None
        assert page.content == "# Markdown Content\nHello"
        assert len(urls_fetched) == 1
        assert urls_fetched[0] == "https://docs.stripe.com/connect.md"

    @pytest.mark.asyncio
    async def test_md_probe_rejects_html_disguised_as_text(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(status_code=404)
            if call_count == 2:
                return mock_response(
                    text="<!DOCTYPE html><html><body>Not markdown</body></html>",
                    content_type="text/plain",
                )
            return mock_response(
                text=html_page("Real Page"),
                content_type="text/html",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.SITEMAP_CRAWL,
        )
        assert page is not None
        assert call_count == 3


class TestProbeAndFetch:
    @pytest.mark.asyncio
    async def test_returns_content_negotiation_when_markdown_header(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text="# Hello",
                content_type="text/markdown; charset=utf-8",
            )
        )

        page, method = await probe_and_fetch(
            "https://example.com/docs/intro", client, 10.0, SourceMethod.LLMS_TXT
        )
        assert page is not None
        assert page.content == "# Hello"
        assert method == FetchMethod.CONTENT_NEGOTIATION

    @pytest.mark.asyncio
    async def test_returns_md_url_when_negotiation_fails(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(status_code=404)
            return mock_response(text="# MD Content", content_type="text/plain")

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            "https://example.com/docs/intro", client, 10.0, SourceMethod.LLMS_TXT
        )
        assert page is not None
        assert page.content == "# MD Content"
        assert method == FetchMethod.MD_URL
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_returns_html_when_all_md_methods_fail(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Fallback", "HTML content"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            "https://example.com/docs/intro", client, 10.0, SourceMethod.LLMS_TXT
        )
        assert page is not None
        assert "HTML content" in page.content
        assert method == FetchMethod.HTML
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_skips_negotiation_for_md_urls(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="# Direct MD", content_type="text/plain")
        )

        page, method = await probe_and_fetch(
            "https://example.com/docs/intro.md", client, 10.0, SourceMethod.LLMS_TXT
        )
        assert page is not None
        assert method == FetchMethod.MD_URL
        assert client.get.call_count == 1


class TestFetchPagePreferredMethod:
    @pytest.mark.asyncio
    async def test_preferred_html_makes_single_request(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text=html_page("Page", "Content"),
                content_type="text/html; charset=utf-8",
            )
        )

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.HTML,
        )
        assert page is not None
        assert "Content" in page.content
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_preferred_md_url_tries_md_then_html_fallback(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if url.endswith(".md"):
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", "Fallback"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert "Fallback" in page.content
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_preferred_md_url_succeeds(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="# MD Content", content_type="text/plain")
        )

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert page.content == "# MD Content"
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_preferred_content_negotiation_falls_back_to_html(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", "HTML fallback"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert "HTML fallback" in page.content
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_md_url_fetched_directly_regardless_of_preferred(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="# Direct MD", content_type="text/plain")
        )

        page = await fetch_page_as_markdown(
            "https://example.com/docs/intro.md",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert page.content == "# Direct MD"
        assert client.get.call_count == 1


def _html_mock_get(pages: dict[str, str] | None = None):
    async def mock_get(url, **kwargs):
        headers = kwargs.get("headers", {})
        if headers.get("Accept") == "text/markdown":
            return mock_response(status_code=404)
        if url.endswith(".md"):
            return mock_response(status_code=404)
        if pages and url in pages:
            return mock_response(
                text=html_page("Page", pages[url]),
                content_type="text/html; charset=utf-8",
            )
        return mock_response(
            text=html_page("Page", "Default content"),
            content_type="text/html; charset=utf-8",
        )

    return mock_get


class TestFetchAndConvertUrls:
    @pytest.mark.asyncio
    async def test_scope_filter_drops_out_of_scope_urls(self, mocker):
        urls = [
            "https://example.com/docs/en/intro",
            "https://example.com/docs/en/guide",
            "https://example.com/docs/de/intro",
            "https://example.com/careers/apply",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
            base_url="https://example.com/docs/en",
        )

        assert len(pages) == 2
        fetched_urls = {p.url for p in pages}
        assert "https://example.com/docs/en/intro" in fetched_urls
        assert "https://example.com/docs/en/guide" in fetched_urls

    @pytest.mark.asyncio
    async def test_dedup_normalized_urls(self, mocker):
        urls = [
            "https://example.com/page",
            "https://example.com/page/",
            "https://example.com/page",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
        )

        assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_no_scope_filter_when_base_url_none(self, mocker):
        urls = [
            "https://example.com/docs/page",
            "https://other.com/page",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.LLMS_TXT,
            EthicsContext(),
        )

        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_no_prefix_substring_match(self, mocker):
        urls = [
            "https://example.com/docs/en/intro",
            "https://example.com/docs/english/intro",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
            base_url="https://example.com/docs/en",
        )

        assert len(pages) == 1
        assert pages[0].url == "https://example.com/docs/en/intro"

    @pytest.mark.asyncio
    async def test_seed_page_itself_is_included(self, mocker):
        urls = [
            "https://example.com/docs/en",
            "https://example.com/docs/en/guide",
            "https://example.com/docs/de/guide",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
            base_url="https://example.com/docs/en",
        )

        assert len(pages) == 2
        fetched_urls = {p.url for p in pages}
        assert "https://example.com/docs/en" in fetched_urls
        assert "https://example.com/docs/en/guide" in fetched_urls

    @pytest.mark.asyncio
    async def test_robots_filtering_in_sitemap_path(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /private/\nContent-Signal: /secret/ ai-input=no"
        )
        urls = [
            "https://example.com/public/page",
            "https://example.com/private/page",
            "https://example.com/secret/page",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())
        ethics = EthicsContext()

        pages = await fetch_and_convert_urls(
            urls,
            client,
            robots,
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            ethics,
            base_url="https://example.com",
        )

        assert len(pages) == 1
        assert pages[0].url == "https://example.com/public/page"
        assert ethics.pages_filtered_by_robots == 1
        assert ethics.pages_filtered_by_content_signal == 1

    @pytest.mark.asyncio
    async def test_max_pages_truncates(self, mocker):
        urls = [f"https://example.com/page{i}" for i in range(10)]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=3, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
        )

        assert len(pages) == 3
        fetched_urls = [p.url for p in pages]
        assert fetched_urls == [
            "https://example.com/page0",
            "https://example.com/page1",
            "https://example.com/page2",
        ]

    @pytest.mark.asyncio
    async def test_on_progress_called(self, mocker):
        urls = [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=_html_mock_get())
        progress = mocker.AsyncMock()

        pages = await fetch_and_convert_urls(
            urls,
            client,
            RobotsParser(""),
            GetDocsOptions(max_pages=10, delay_seconds=0),
            SourceMethod.SITEMAP_CRAWL,
            EthicsContext(),
            on_progress=progress,
        )

        assert len(pages) == 3
        assert progress.await_count >= 2


class TestFilterUrlsByRobots:
    def test_all_allowed(self):
        robots = RobotsParser("")
        allowed, robots_count, signal_count = filter_urls_by_robots(
            ["https://example.com/a", "https://example.com/b"],
            robots,
        )
        assert allowed == ["https://example.com/a", "https://example.com/b"]
        assert robots_count == 0
        assert signal_count == 0

    def test_disallow_filters(self):
        robots = RobotsParser("User-agent: *\nDisallow: /private/")
        allowed, robots_count, signal_count = filter_urls_by_robots(
            [
                "https://example.com/public/page",
                "https://example.com/private/page",
                "https://example.com/private/other",
            ],
            robots,
        )
        assert allowed == ["https://example.com/public/page"]
        assert robots_count == 2
        assert signal_count == 0

    def test_content_signal_filters(self):
        robots = RobotsParser(
            "User-agent: *\nAllow: /\nContent-Signal: /secret/ ai-input=no"
        )
        allowed, robots_count, signal_count = filter_urls_by_robots(
            [
                "https://example.com/public/page",
                "https://example.com/secret/page",
            ],
            robots,
        )
        assert allowed == ["https://example.com/public/page"]
        assert robots_count == 0
        assert signal_count == 1

    def test_both_disallow_and_content_signal(self):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /blocked/\nContent-Signal: /noinput/ ai-input=no"
        )
        allowed, robots_count, signal_count = filter_urls_by_robots(
            [
                "https://example.com/ok",
                "https://example.com/blocked/page",
                "https://example.com/noinput/page",
            ],
            robots,
        )
        assert allowed == ["https://example.com/ok"]
        assert robots_count == 1
        assert signal_count == 1

    def test_empty_input(self):
        robots = RobotsParser("User-agent: *\nDisallow: /")
        allowed, robots_count, signal_count = filter_urls_by_robots([], robots)
        assert allowed == []
        assert robots_count == 0
        assert signal_count == 0
