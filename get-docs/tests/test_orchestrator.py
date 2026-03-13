import pytest

from src.core.github_fetcher import GitHubFetchResult
from src.core.llms_txt_fetcher import LlmsTxtLink, LlmsTxtResult
from src.core.orchestrator import get_docs
from src.core.robots_parser import RobotsParser
from src.models.enums import SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import DocPage
from src.utils.http_client import HttpClient
from tests.conftest import html_page, mock_response, mock_http_client


def _request(url="https://docs.example.com", github_repo=None):
    return GetDocsRequest(
        url=url,
        github_repo=github_repo,
        max_pages=10,
        delay_seconds=0,
    )


def _gh_page(owner, repo, branch, path, content):
    return DocPage(
        url=f"https://github.com/{owner}/{repo}/blob/{branch}/{path}",
        title=path,
        content=content,
        source_method=SourceMethod.GITHUB,
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
        mock_sitemap = mocker.patch("src.core.orchestrator.collect_sitemap_urls")
        mock_github = mocker.patch("src.core.orchestrator.fetch_github_docs")

        client = mocker.AsyncMock(spec=HttpClient)

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

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

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
                pages=[
                    _gh_page("owner", "repo", "main", "docs/intro.md", "# Fallback")
                ],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB
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
                pages=[_gh_page("owner", "repo", "main", "docs/intro.md", "# GH Docs")],
                license_spdx_id="MIT",
            ),
        )
        mock_sitemap = mocker.patch("src.core.orchestrator.collect_sitemap_urls")

        client = mocker.AsyncMock(spec=HttpClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB
        assert result.github_repo == "https://github.com/owner/repo"
        assert len(result.pages) == 1
        assert result.pages[0].content == "# GH Docs"
        assert result.ethics.license_spdx_id == "MIT"
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
                pages=[],
            ),
        )
        mocker.patch(
            "src.core.orchestrator.collect_sitemap_urls",
            return_value=["https://docs.example.com/intro"],
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            if url == "https://docs.example.com/intro":
                return mock_response(
                    text=html_page("Intro", "Sitemap content"),
                    content_type="text/html; charset=utf-8",
                )
            return mock_response(
                text='<html><a href="https://github.com/owner/repo">GH</a></html>'
            )

        client = mocker.AsyncMock(spec=HttpClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

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
            "src.core.orchestrator.collect_sitemap_urls",
            return_value=["https://docs.example.com/intro"],
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            if url == "https://docs.example.com/intro":
                return mock_response(
                    text=html_page("Intro", "Intro content"),
                    content_type="text/html; charset=utf-8",
                )
            return mock_response(text="<html>no github</html>")

        client = mocker.AsyncMock(spec=HttpClient)
        client.get = mocker.AsyncMock(side_effect=mock_get)

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
                pages=[_gh_page("owner", "repo", "main", "docs/intro.md", "# GH Only")],
                license_spdx_id="MIT",
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)

        result = await get_docs(
            _request(url=None, github_repo="https://github.com/owner/repo"),
            client,
        )

        assert result.source_method == SourceMethod.GITHUB
        assert len(result.pages) == 1
        assert result.pages[0].content == "# GH Only"
        assert result.ethics.license_spdx_id == "MIT"

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
                pages=[
                    _gh_page(
                        "discovered", "repo", "main", "docs/readme.md", "# Discovered"
                    )
                ],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                text='<html><a href="https://github.com/discovered/repo">GitHub</a></html>'
            )
        )

        result = await get_docs(_request(), client)

        assert result.source_method == SourceMethod.GITHUB
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
            "src.core.orchestrator.collect_sitemap_urls",
            return_value=[
                "https://docs.example.com/empty",
                "https://docs.example.com/real",
            ],
        )

        async def mock_get(url, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return mock_response(status_code=404)
            if url.endswith(".md"):
                return mock_response(status_code=404)
            if url == "https://docs.example.com/empty":
                return mock_response(
                    text="<html><body></body></html>",
                    content_type="text/html; charset=utf-8",
                )
            if url == "https://docs.example.com/real":
                return mock_response(
                    text=html_page("Real", "Has content"),
                    content_type="text/html; charset=utf-8",
                )
            return mock_response(text="<html>no github</html>")

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

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

        client = mocker.AsyncMock(spec=HttpClient)
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
                pages=[_gh_page("owner", "repo", "main", "docs/intro.md", "# Intro")],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)

        result = await get_docs(
            _request(github_repo="https://github.com/owner/repo"), client
        )

        assert result.source_method == SourceMethod.GITHUB
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
                pages=[_gh_page("owner", "repo", "main", "docs/intro.md", "# Docs")],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)

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
                pages=[
                    _gh_page(
                        "owner", "repo", "main", "packages/docs/intro.md", "# Docs"
                    )
                ],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)

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
                pages=[
                    _gh_page(
                        "owner", "repo", "main", "packages/docs/intro.md", "# Docs"
                    )
                ],
            ),
        )

        client = mocker.AsyncMock(spec=HttpClient)

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

        client = mocker.AsyncMock(spec=HttpClient)
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

        client = mocker.AsyncMock(spec=HttpClient)

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

        client = mocker.AsyncMock(spec=HttpClient)

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
            "src.core.orchestrator.collect_sitemap_urls",
            return_value=[],
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

        client = mocker.AsyncMock(spec=HttpClient)
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

        client = mocker.AsyncMock(spec=HttpClient)
        progress = mocker.AsyncMock()

        await get_docs(_request(), client, on_progress=progress)

        progress.assert_awaited_once_with(1, 1)
