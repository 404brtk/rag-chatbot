import httpx
import pytest

from src.core.crawler import CrawlPage, CrawlResult
from src.core.github_fetcher import GitHubFetchResult, GitHubFile
from src.core.llms_txt_fetcher import LlmsTxtLink, LlmsTxtResult
from src.core.orchestrator import (
    _fetch_page_as_markdown,
    _html_to_doc_page,
    _probe_and_fetch,
    get_docs,
)
from src.core.robots_parser import RobotsParser
from src.models.enums import FetchMethod, SourceMethod
from src.models.requests import GetDocsOptions, GetDocsRequest
from tests.conftest import html_page, mock_response


def _request(url="https://docs.example.com", github_repo=None):
    return GetDocsRequest(
        url=url,
        github_repo=github_repo,
        options=GetDocsOptions(
            max_web_pages=10,
            max_concurrent=5,
            delay_seconds=0,
        ),
    )


class TestGetDocsRequestValidation:
    def test_url_only(self):
        req = GetDocsRequest(url="https://example.com")
        assert req.url is not None
        assert req.github_repo is None

    def test_github_only(self):
        req = GetDocsRequest(github_repo="https://github.com/owner/repo")
        assert req.url is None
        assert req.github_repo is not None

    def test_both_provided(self):
        req = GetDocsRequest(
            url="https://example.com",
            github_repo="https://github.com/owner/repo",
        )
        assert req.url is not None
        assert req.github_repo is not None

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="At least one"):
            GetDocsRequest()


class TestHtmlToDocPage:
    def test_extracts_title_and_markdown(self):
        html = html_page("Getting Started", "Welcome to the docs")
        page = _html_to_doc_page(
            "https://example.com/start", html, SourceMethod.SITEMAP_CRAWL
        )
        assert page.title == "Getting Started"
        assert "Welcome to the docs" in page.content
        assert page.source_method == SourceMethod.SITEMAP_CRAWL

    def test_empty_html_returns_empty_markdown(self):
        page = _html_to_doc_page(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page, method = await _probe_and_fetch(
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

        page, method = await _probe_and_fetch(
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

        page, method = await _probe_and_fetch(
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

        page, method = await _probe_and_fetch(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
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

        page = await _fetch_page_as_markdown(
            "https://example.com/docs/intro.md",
            client,
            10.0,
            SourceMethod.LLMS_TXT,
            preferred_method=FetchMethod.CONTENT_NEGOTIATION,
        )
        assert page is not None
        assert page.content == "# Direct MD"
        assert client.get.call_count == 1


class TestGetDocs:
    @pytest.mark.asyncio
    async def test_llms_full_txt_short_circuits(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms-full.txt",
                raw_content="# Full Docs\nAll content here",
                title="Full Docs",
                is_full=True,
            ),
        )
        mock_sitemap = mocker.patch("src.core.orchestrator.crawl_sitemap")
        mock_github = mocker.patch("src.core.orchestrator.fetch_github_docs")

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.LLMS_TXT
        assert len(result.pages) == 1
        assert result.pages[0].content == "# Full Docs\nAll content here"
        mock_sitemap.assert_not_called()
        mock_github.assert_not_called()

    @pytest.mark.asyncio
    async def test_llms_txt_links_fetched_and_converted(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms.txt",
                raw_content="",
                title="Docs",
                is_full=False,
                links=[
                    LlmsTxtLink(
                        title="Guide",
                        url="https://docs.example.com/guide",
                    ),
                    LlmsTxtLink(
                        title="API",
                        url="https://docs.example.com/api",
                    ),
                ],
            ),
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Doc Page", "Content"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.LLMS_TXT
        assert len(result.pages) == 2
        for page in result.pages:
            assert page.source_method == SourceMethod.LLMS_TXT

    @pytest.mark.asyncio
    async def test_llms_txt_exception_falls_through_to_github(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            side_effect=RuntimeError("connection failed"),
        )
        mocker.patch(
            "src.core.orchestrator.discover_github_repo",
            return_value="https://github.com/owner/repo",
        )
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/intro.md", content="# Fallback")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB_RAW
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_github_is_tried_before_sitemap(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.discover_github_repo",
            return_value="https://github.com/owner/repo",
        )
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/intro.md", content="# GH Docs")],
                license_spdx_id="MIT",
            ),
        )
        mock_sitemap = mocker.patch("src.core.orchestrator.crawl_sitemap")

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB_RAW
        assert result.github_repo == "https://github.com/owner/repo"
        assert len(result.pages) == 1
        assert result.pages[0].content == "# GH Docs"
        assert result.ethics.license_spdx_id == "MIT"
        assert result.ethics.license_allowed is True
        mock_sitemap.assert_not_called()

    @pytest.mark.asyncio
    async def test_github_empty_files_falls_through_to_sitemap(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.discover_github_repo",
            return_value="https://github.com/owner/repo",
        )
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[],
            ),
        )
        mocker.patch(
            "src.core.orchestrator.crawl_sitemap",
            return_value=CrawlResult(
                pages=[
                    CrawlPage(
                        url="https://docs.example.com/intro",
                        html=html_page("Intro", "Sitemap content"),
                    ),
                ],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.SITEMAP_CRAWL
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_sitemap(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.crawl_sitemap",
            return_value=CrawlResult(
                pages=[
                    CrawlPage(
                        url="https://docs.example.com/intro",
                        html=html_page("Intro", "Intro content"),
                    ),
                ],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="<html>no github</html>")
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.SITEMAP_CRAWL
        assert len(result.pages) == 1
        assert "Intro content" in result.pages[0].content

    @pytest.mark.asyncio
    async def test_github_only_request(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/intro.md", content="# GH Only")],
                license_spdx_id="MIT",
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        result = await get_docs(
            _request(url=None, github_repo="https://github.com/owner/repo"),
            client,
        )

        assert result.source_method == SourceMethod.GITHUB_RAW
        assert len(result.pages) == 1
        assert result.pages[0].content == "# GH Only"
        assert result.ethics.license_spdx_id == "MIT"
        assert result.ethics.license_allowed is True

    @pytest.mark.asyncio
    async def test_github_auto_discovery(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.discover_github_repo",
            return_value="https://github.com/discovered/repo",
        )
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="discovered",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/readme.md", content="# Discovered")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/discovered/repo">GitHub</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB_RAW
        assert result.github_repo == "https://github.com/discovered/repo"
        assert len(result.pages) == 1

    @pytest.mark.asyncio
    async def test_empty_pages_filtered(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.crawl_sitemap",
            return_value=CrawlResult(
                pages=[
                    CrawlPage(
                        url="https://docs.example.com/empty",
                        html="<html><body></body></html>",
                    ),
                    CrawlPage(
                        url="https://docs.example.com/real",
                        html=html_page("Real", "Has content"),
                    ),
                ],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(text="<html>no github</html>")
        )

        result = await get_docs(_request(), client)

        assert len(result.pages) == 1
        assert result.pages[0].url == "https://docs.example.com/real"

    @pytest.mark.asyncio
    async def test_robots_filters_llms_links(self, mocker):
        robots = RobotsParser("User-agent: *\nDisallow: /private/")
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=robots,
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms.txt",
                raw_content="",
                title="Docs",
                is_full=False,
                links=[
                    LlmsTxtLink(
                        title="Public",
                        url="https://docs.example.com/public/guide",
                    ),
                    LlmsTxtLink(
                        title="Private",
                        url="https://docs.example.com/private/secret",
                    ),
                ],
            ),
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", "Content"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        result = await get_docs(_request(), client)

        assert len(result.pages) == 1
        assert result.pages[0].url == "https://docs.example.com/public/guide"
        assert result.ethics.pages_filtered_by_robots == 1

    @pytest.mark.asyncio
    async def test_explicit_github_repo_used_directly(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mock_discover = mocker.patch(
            "src.core.orchestrator.discover_github_repo",
        )
        mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/intro.md", content="# Intro")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        result = await get_docs(
            _request(github_repo="https://github.com/owner/repo"), client
        )

        assert result.source_method == SourceMethod.GITHUB_RAW
        mock_discover.assert_not_called()

    @pytest.mark.asyncio
    async def test_github_root_only_when_url_present(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mock_fetch_gh = mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="docs",
                files=[GitHubFile(path="docs/intro.md", content="# Docs")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        await get_docs(
            _request(
                url="https://docs.example.com",
                github_repo="https://github.com/owner/repo",
            ),
            client,
        )

        mock_fetch_gh.assert_called_once()
        _, kwargs = mock_fetch_gh.call_args
        assert kwargs["root_only"] is True
        assert kwargs["doc_folder_override"] is None

    @pytest.mark.asyncio
    async def test_github_deep_search_when_no_url(self, mocker):
        mock_fetch_gh = mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="packages/docs",
                files=[GitHubFile(path="packages/docs/intro.md", content="# Docs")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        await get_docs(
            _request(url=None, github_repo="https://github.com/owner/repo"),
            client,
        )

        mock_fetch_gh.assert_called_once()
        _, kwargs = mock_fetch_gh.call_args
        assert kwargs["root_only"] is False
        assert kwargs["doc_folder_override"] is None

    @pytest.mark.asyncio
    async def test_github_subpath_used_as_doc_folder_override(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mock_fetch_gh = mocker.patch(
            "src.core.orchestrator.fetch_github_docs",
            return_value=GitHubFetchResult(
                owner="owner",
                repo="repo",
                branch="main",
                doc_folder="packages/docs",
                files=[GitHubFile(path="packages/docs/intro.md", content="# Docs")],
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        await get_docs(
            _request(
                url="https://docs.example.com",
                github_repo="https://github.com/owner/repo/tree/main/packages/docs",
            ),
            client,
        )

        mock_fetch_gh.assert_called_once()
        _, kwargs = mock_fetch_gh.call_args
        assert kwargs["doc_folder_override"] == "packages/docs"

    @pytest.mark.asyncio
    async def test_content_signal_filters_urls(self, mocker):
        robots = RobotsParser(
            "User-agent: *\nAllow: /\nContent-Signal: /private/ ai-input=no"
        )
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=robots,
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms.txt",
                raw_content="",
                title="Docs",
                is_full=False,
                links=[
                    LlmsTxtLink(
                        title="Public",
                        url="https://docs.example.com/public/guide",
                    ),
                    LlmsTxtLink(
                        title="Private",
                        url="https://docs.example.com/private/secret",
                    ),
                ],
            ),
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            return mock_response(
                text=html_page("Page", "Content"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        result = await get_docs(_request(), client)

        assert len(result.pages) == 1
        assert result.pages[0].url == "https://docs.example.com/public/guide"
        assert result.ethics.pages_filtered_by_content_signal == 1

    @pytest.mark.asyncio
    async def test_content_signal_ai_input_captured(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(
                "User-agent: *\nAllow: /\nContent-Signal: ai-input=no"
            ),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms-full.txt",
                raw_content="# Docs",
                title="Docs",
                is_full=True,
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        result = await get_docs(_request(), client)

        assert result.ethics.content_signal_ai_input is False

    @pytest.mark.asyncio
    async def test_crawl_delay_captured(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser("User-agent: *\nCrawl-delay: 5"),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms-full.txt",
                raw_content="# Docs",
                title="Docs",
                is_full=True,
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        result = await get_docs(_request(), client)

        assert result.ethics.robots_crawl_delay_seconds == 5

    @pytest.mark.asyncio
    async def test_falls_back_to_single_page_scrape(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=None,
        )
        mocker.patch(
            "src.core.orchestrator.crawl_sitemap",
            return_value=CrawlResult(pages=[]),
        )

        call_count = 0

        async def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            if call_count == 1:
                return mock_response(text="<html>no github</html>")
            return mock_response(
                text=html_page("Home", "Welcome to the docs"),
                content_type="text/html; charset=utf-8",
            )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.SINGLE_PAGE
        assert len(result.pages) == 1
        assert result.pages[0].url == "https://docs.example.com/"
        assert "Welcome to the docs" in result.pages[0].content

    @pytest.mark.asyncio
    async def test_on_progress_callback(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://docs.example.com/llms-full.txt",
                raw_content="# Full Docs",
                title="Full Docs",
                is_full=True,
            ),
        )

        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        progress = mocker.AsyncMock()

        await get_docs(_request(), client, on_progress=progress)

        progress.assert_awaited_once_with(1, 1)
