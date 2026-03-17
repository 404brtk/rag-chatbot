import pytest

from src.core.link_crawler import extract_links, crawl_links
from src.core.robots_txt_parser import RobotsParser
from src.models.enums import SourceMethod
from src.models.requests import GetDocsRequest
from src.models.responses import EthicsContext
from tests.conftest import html_page, mock_http_client, mock_response


def _html_with_links(title: str, links: list[str], body: str = "") -> str:
    link_html = "\n".join(f'<a href="{url}">{url}</a>' for url in links)
    body_html = f"<p>{body}</p>" if body else ""
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><main><h1>{title}</h1>{body_html}{link_html}</main></body></html>"
    )


def _request(**kwargs):
    defaults = dict(url="https://docs.example.com/", max_pages=10, max_depth=3)
    defaults.update(kwargs)
    return GetDocsRequest(**defaults)


class TestExtractLinks:
    def test_extracts_absolute_links(self):
        html = (
            '<html><body><a href="https://docs.example.com/page">link</a></body></html>'
        )
        assert extract_links(html, "https://docs.example.com/") == [
            "https://docs.example.com/page"
        ]

    def test_resolves_relative_links(self):
        html = '<html><body><a href="guide/intro">link</a></body></html>'
        result = extract_links(html, "https://docs.example.com/docs/")
        assert result == ["https://docs.example.com/docs/guide/intro"]

    def test_skips_fragment_only(self):
        html = '<html><body><a href="#section">link</a></body></html>'
        assert extract_links(html, "https://docs.example.com/") == []

    def test_skips_rel_nofollow(self):
        html = '<html><body><a href="/page" rel="nofollow">link</a></body></html>'
        assert extract_links(html, "https://docs.example.com/") == []

    def test_skips_rel_ugc(self):
        html = '<html><body><a href="/page" rel="ugc">link</a></body></html>'
        assert extract_links(html, "https://docs.example.com/") == []

    def test_skips_rel_sponsored(self):
        html = '<html><body><a href="/page" rel="sponsored">link</a></body></html>'
        assert extract_links(html, "https://docs.example.com/") == []

    def test_ignores_rel_noreferrer(self):
        html = '<html><body><a href="/page" rel="noreferrer">link</a></body></html>'
        result = extract_links(html, "https://docs.example.com/")
        assert len(result) == 1

    def test_ignores_rel_noopener(self):
        html = '<html><body><a href="/page" rel="noopener">link</a></body></html>'
        result = extract_links(html, "https://docs.example.com/")
        assert len(result) == 1

    def test_skips_combined_rel_with_nofollow(self):
        html = (
            '<html><body><a href="/page" rel="noopener nofollow">link</a></body></html>'
        )
        assert extract_links(html, "https://docs.example.com/") == []

    def test_skips_asset_urls(self):
        html = '<html><body><a href="/file.pdf">pdf</a><a href="/img.png">img</a></body></html>'
        assert extract_links(html, "https://docs.example.com/") == []

    def test_skips_javascript_mailto_tel(self):
        html = (
            "<html><body>"
            '<a href="javascript:void(0)">js</a>'
            '<a href="mailto:a@b.com">mail</a>'
            '<a href="tel:123">tel</a>'
            "</body></html>"
        )
        assert extract_links(html, "https://docs.example.com/") == []


class TestCrawlLinks:
    @pytest.mark.asyncio
    async def test_discovers_pages_at_depth_1(self, mocker):
        page_a = _html_with_links("Home", ["/guide"], body="Welcome")
        page_b = html_page("Guide", "The guide content")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=page_a)
            if url == "https://docs.example.com/guide":
                return mock_response(text=page_b)
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(),
            ethics=EthicsContext(),
        )

        assert len(pages) == 2
        assert pages[0].source_method == SourceMethod.LINK_CRAWL

    @pytest.mark.asyncio
    async def test_respects_max_pages(self, mocker):
        links = [f"/page{i}" for i in range(10)]
        home = _html_with_links("Home", links, body="Welcome")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=home)
            return mock_response(text=html_page("Page", "Content"))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(max_pages=3),
            ethics=EthicsContext(),
        )

        assert len(pages) == 3

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, mocker):
        home = _html_with_links("Home", ["/a"], body="Home")
        page_a = _html_with_links("A", ["/a/b"], body="Page A")
        page_b = _html_with_links("B", ["/a/b/c"], body="Page B")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=home)
            if url == "https://docs.example.com/a":
                return mock_response(text=page_a)
            if url == "https://docs.example.com/a/b":
                return mock_response(text=page_b)
            if url == "https://docs.example.com/a/b/c":
                return mock_response(text=html_page("C", "Page C"))
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(max_depth=2),
            ethics=EthicsContext(),
        )

        urls = [p.url for p in pages]
        assert "https://docs.example.com/" in urls
        assert "https://docs.example.com/a" in urls
        assert "https://docs.example.com/a/b" not in urls

    @pytest.mark.asyncio
    async def test_filters_by_robots_txt(self, mocker):
        home = _html_with_links("Home", ["/secret", "/public"], body="Home")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=home)
            if url == "https://docs.example.com/public":
                return mock_response(text=html_page("Public", "Public page"))
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        robots = RobotsParser("User-agent: *\nDisallow: /secret")
        ethics = EthicsContext()

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=robots,
            options=_request(),
            ethics=ethics,
        )

        urls = [p.url for p in pages]
        assert "https://docs.example.com/public" in urls
        assert "https://docs.example.com/secret" not in urls
        assert ethics.pages_filtered_by_robots_txt >= 1

    @pytest.mark.asyncio
    async def test_skips_page_blocked_by_x_robots_tag(self, mocker):
        home = _html_with_links("Home", ["/blocked"], body="Home")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=home)
            if url == "https://docs.example.com/blocked":
                return mock_response(
                    text=html_page("Blocked", "Content"),
                    extra_headers={"x-robots-tag": "noindex"},
                )
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        ethics = EthicsContext()
        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(),
            ethics=ethics,
        )

        urls = [p.url for p in pages]
        assert "https://docs.example.com/blocked" not in urls
        assert ethics.pages_filtered_by_robots_tags >= 1

    @pytest.mark.asyncio
    async def test_does_not_extract_links_when_nofollow_header(self, mocker):
        home = _html_with_links("Home", ["/page"], body="Home content")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(
                    text=home,
                    extra_headers={"x-robots-tag": "nofollow"},
                )
            return mock_response(text=html_page("Page", "Content"))

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(),
            ethics=EthicsContext(),
        )

        assert len(pages) == 1
        assert pages[0].url == "https://docs.example.com/"
        assert "Home content" in pages[0].content

    @pytest.mark.asyncio
    async def test_stays_within_scope(self, mocker):
        home = _html_with_links(
            "Home",
            ["/docs/guide", "https://other.com/page", "/blog/post"],
            body="Home",
        )

        async def mock_get(url, **kwargs):
            if url in (
                "https://docs.example.com/docs/",
                "https://docs.example.com/docs",
            ):
                return mock_response(text=home)
            if url == "https://docs.example.com/docs/guide":
                return mock_response(text=html_page("Guide", "Guide content"))
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/docs/",
            client=client,
            robots=RobotsParser(""),
            options=_request(url="https://docs.example.com/docs/"),
            ethics=EthicsContext(),
        )

        urls = [p.url for p in pages]
        assert "https://docs.example.com/docs/guide" in urls
        assert "https://other.com/page" not in urls
        assert "https://docs.example.com/blog/post" not in urls

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self, mocker):
        home = _html_with_links("Home", ["/page", "/page", "/page"], body="Home")

        async def mock_get(url, **kwargs):
            if url == "https://docs.example.com/":
                return mock_response(text=home)
            if url == "https://docs.example.com/page":
                return mock_response(text=html_page("Page", "Content"))
            return mock_response(status_code=404)

        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=mock_get)

        pages = await crawl_links(
            base_url="https://docs.example.com/",
            client=client,
            robots=RobotsParser(""),
            options=_request(),
            ethics=EthicsContext(),
        )

        assert len(pages) == 2
