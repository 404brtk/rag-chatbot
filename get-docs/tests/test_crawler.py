import pytest

from src.core.crawler import (
    fetch_and_convert_urls,
    fetch_page_as_markdown,
    filter_urls_by_robots,
    html_to_doc_page,
    probe_and_fetch,
)
from src.core.robots_txt_parser import RobotsParser
from src.models.enums import FetchMethod, SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import EthicsContext
from tests.conftest import html_page, mock_http_client, mock_response


class TestHtmlToDocPage:
    def test_extracts_title_and_markdown(self):
        html = html_page("Getting Started", "Welcome to the docs")
        page = html_to_doc_page(
            url="https://example.com/start",
            html=html,
            source_method=SourceMethod.SITEMAP_CRAWL,
        )
        assert page.title == "Getting Started"
        assert "Welcome to the docs" in page.content
        assert page.source_method == SourceMethod.SITEMAP_CRAWL

    def test_empty_html_returns_empty_markdown(self):
        page = html_to_doc_page(
            url="https://example.com",
            html="<html></html>",
            source_method=SourceMethod.LLMS_TXT,
        )
        assert page.content == ""


class TestProbeAndFetch:
    @pytest.mark.asyncio
    async def test_returns_content_negotiation_when_markdown_header(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(
                text="# Hello",
                content_type="text/markdown; charset=utf-8",
            )
        )

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
        )
        assert page is not None
        assert "HTML content" in page.content
        assert method == FetchMethod.HTML
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_returns_none_when_all_fail(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=mock_response(status_code=404))

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.SITEMAP_CRAWL,
        )
        assert page is None

    @pytest.mark.asyncio
    async def test_skips_negotiation_for_md_urls(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(text="# Direct MD", content_type="text/plain")
        )

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro.md",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
        )
        assert page is not None
        assert method == FetchMethod.MD_URL
        assert inner.get.call_count == 1

    @pytest.mark.asyncio
    async def test_rejects_html_disguised_as_text_plain(self, mocker):
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.SITEMAP_CRAWL,
        )
        assert page is not None
        assert method == FetchMethod.HTML
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_md_extension_url_falls_back_to_html(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            side_effect=[
                mock_response(status_code=404),
                mock_response(
                    text=html_page("Page", "HTML version"),
                    content_type="text/html; charset=utf-8",
                ),
            ]
        )

        page, method = await probe_and_fetch(
            url="https://example.com/docs/intro.md",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
        )
        assert page is not None
        assert "HTML version" in page.content
        assert method == FetchMethod.HTML

    @pytest.mark.asyncio
    async def test_root_url_skips_md_probes_goes_to_html(self, mocker):
        fetched_urls: list[str] = []

        async def mock_get(url, **kwargs):
            fetched_urls.append(url)
            return mock_response(
                text=html_page("Home", "Welcome"),
                content_type="text/html; charset=utf-8",
            )

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page, method = await probe_and_fetch(
            url="https://example.com/",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.SINGLE_PAGE,
        )
        assert page is not None
        assert "Welcome" in page.content
        assert method == FetchMethod.HTML
        assert not any(".md" in u for u in fetched_urls)
        assert len(fetched_urls) == 2


class TestFetchPagePreferredMethod:
    @pytest.mark.asyncio
    async def test_preferred_html_makes_single_request(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(
                text=html_page("Page", "Content"),
                content_type="text/html; charset=utf-8",
            )
        )

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.HTML,
        )
        assert page is not None
        assert "Content" in page.content
        assert inner.get.call_count == 1

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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert "Fallback" in page.content
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_preferred_md_url_succeeds(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(text="# MD Content", content_type="text/plain")
        )

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert page.content == "# MD Content"
        assert inner.get.call_count == 1

    @pytest.mark.asyncio
    async def test_preferred_content_negotiation_falls_back_to_md_url_then_html(
        self, mocker
    ):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", "HTML fallback"),
                content_type="text/html; charset=utf-8",
            )

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert "HTML fallback" in page.content
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_preferred_content_negotiation_falls_back_to_md_url(self, mocker):
        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(status_code=404)
            return mock_response(text="# From MD URL", content_type="text/plain")

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert page.content == "# From MD URL"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_preferred_md_url_root_url_skips_to_html(self, mocker):
        fetched_urls: list[str] = []

        async def mock_get(url, **kwargs):
            fetched_urls.append(url)
            return mock_response(
                text=html_page("Home", "Homepage content"),
                content_type="text/html; charset=utf-8",
            )

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        page = await fetch_page_as_markdown(
            url="https://example.com/",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.SINGLE_PAGE,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert "Homepage content" in page.content
        assert len(fetched_urls) == 1
        assert not any(".md" in u for u in fetched_urls)

    @pytest.mark.asyncio
    async def test_md_url_fetched_directly_regardless_of_preferred(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            return_value=mock_response(text="# Direct MD", content_type="text/plain")
        )

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro.md",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert page.content == "# Direct MD"
        assert inner.get.call_count == 1

    @pytest.mark.asyncio
    async def test_md_extension_fails_falls_back_to_html(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            side_effect=[
                mock_response(status_code=404),
                mock_response(
                    text=html_page("Page", "HTML version"),
                    content_type="text/html; charset=utf-8",
                ),
            ]
        )

        page = await fetch_page_as_markdown(
            url="https://example.com/docs/intro.md",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.MD_URL,
        )
        assert page is not None
        assert "HTML version" in page.content
        assert inner.get.call_count == 2

    @pytest.mark.asyncio
    async def test_preferred_content_negotiation_root_url_skips_md_to_html(
        self, mocker
    ):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(
            side_effect=[
                mock_response(status_code=404),
                mock_response(
                    text=html_page("Home", "Root content"),
                    content_type="text/html; charset=utf-8",
                ),
            ]
        )

        page = await fetch_page_as_markdown(
            url="https://example.com/",
            client=client,
            timeout=10.0,
            source_method=SourceMethod.SINGLE_PAGE,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert "Root content" in page.content
        assert inner.get.call_count == 2


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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
        )

        assert len(pages) == 1

    @pytest.mark.asyncio
    async def test_no_scope_filter_when_base_url_none(self, mocker):
        urls = [
            "https://example.com/docs/page",
            "https://other.com/page",
        ]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.LLMS_TXT,
            ethics=EthicsContext(),
        )

        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_no_prefix_substring_match(self, mocker):
        urls = [
            "https://example.com/docs/en/intro",
            "https://example.com/docs/english/intro",
        ]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())
        ethics = EthicsContext()

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=robots,
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=ethics,
            base_url="https://example.com",
        )

        assert len(pages) == 1
        assert pages[0].url == "https://example.com/public/page"
        assert ethics.pages_filtered_by_robots_txt == 1
        assert ethics.pages_filtered_by_content_signal == 1

    @pytest.mark.asyncio
    async def test_max_pages_truncates(self, mocker):
        urls = [f"https://example.com/page{i}" for i in range(10)]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=3, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())
        progress = mocker.AsyncMock()

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
            on_progress=progress,
        )

        assert len(pages) == 3
        assert progress.await_count >= 2

    @pytest.mark.asyncio
    async def test_language_filter_in_pipeline(self, mocker):
        urls = [
            "https://example.com/docs/en/guide",
            "https://example.com/docs/en/api",
            "https://example.com/docs/fr/guide",
            "https://example.com/docs/de/guide",
        ]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
            base_url="https://example.com/docs",
        )

        assert len(pages) == 2
        fetched_urls = {p.url for p in pages}
        assert "https://example.com/docs/en/guide" in fetched_urls
        assert "https://example.com/docs/en/api" in fetched_urls

    @pytest.mark.asyncio
    async def test_version_dedup_in_pipeline(self, mocker):
        urls = [
            "https://example.com/docs/driver/current/guide",
            "https://example.com/docs/driver/v1.0/guide",
            "https://example.com/docs/driver/current/api",
            "https://example.com/docs/driver/v1.0/api",
        ]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
            base_url="https://example.com/docs",
        )

        assert len(pages) == 2
        fetched_urls = {p.url for p in pages}
        assert "https://example.com/docs/driver/current/guide" in fetched_urls
        assert "https://example.com/docs/driver/current/api" in fetched_urls


class TestProbeUrlSelection:
    @pytest.mark.asyncio
    async def test_root_url_skipped_for_probe(self, mocker):
        urls = [
            "https://example.com/",
            "https://example.com/docs/intro",
            "https://example.com/docs/guide",
        ]
        fetched_urls: list[str] = []

        async def mock_get(url, **kwargs):
            fetched_urls.append(url)
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", f"Content for {url}"),
                content_type="text/html; charset=utf-8",
            )

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
        )

        assert len(pages) == 3
        assert fetched_urls[0] == "https://example.com/docs/intro"
        assert not any("example.com.md" in u for u in fetched_urls)

    @pytest.mark.asyncio
    async def test_all_root_urls_still_works(self, mocker):
        urls = ["https://example.com/"]

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=_html_mock_get())

        pages = await fetch_and_convert_urls(
            urls=urls,
            client=client,
            robots=RobotsParser(""),
            options=GetDocsRequest(
                url="https://example.com", max_pages=10, delay_seconds=0
            ),
            source_method=SourceMethod.SITEMAP_CRAWL,
            ethics=EthicsContext(),
        )

        assert len(pages) == 1


class TestFilterUrlsByRobots:
    def test_all_allowed(self):
        robots = RobotsParser("")
        allowed, robots_count, signal_count = filter_urls_by_robots(
            urls=["https://example.com/a", "https://example.com/b"],
            robots=robots,
        )
        assert allowed == ["https://example.com/a", "https://example.com/b"]
        assert robots_count == 0
        assert signal_count == 0

    def test_disallow_filters(self):
        robots = RobotsParser("User-agent: *\nDisallow: /private/")
        allowed, robots_count, signal_count = filter_urls_by_robots(
            urls=[
                "https://example.com/public/page",
                "https://example.com/private/page",
                "https://example.com/private/other",
            ],
            robots=robots,
        )
        assert allowed == ["https://example.com/public/page"]
        assert robots_count == 2
        assert signal_count == 0

    def test_content_signal_filters(self):
        robots = RobotsParser(
            "User-agent: *\nAllow: /\nContent-Signal: /secret/ ai-input=no"
        )
        allowed, robots_count, signal_count = filter_urls_by_robots(
            urls=[
                "https://example.com/public/page",
                "https://example.com/secret/page",
            ],
            robots=robots,
        )
        assert allowed == ["https://example.com/public/page"]
        assert robots_count == 0
        assert signal_count == 1

    def test_both_disallow_and_content_signal(self):
        robots = RobotsParser(
            "User-agent: *\nDisallow: /blocked/\nContent-Signal: /noinput/ ai-input=no"
        )
        allowed, robots_count, signal_count = filter_urls_by_robots(
            urls=[
                "https://example.com/ok",
                "https://example.com/blocked/page",
                "https://example.com/noinput/page",
            ],
            robots=robots,
        )
        assert allowed == ["https://example.com/ok"]
        assert robots_count == 1
        assert signal_count == 1

    def test_empty_input(self):
        robots = RobotsParser("User-agent: *\nDisallow: /")
        allowed, robots_count, signal_count = filter_urls_by_robots(
            urls=[], robots=robots
        )
        assert allowed == []
        assert robots_count == 0
        assert signal_count == 0
