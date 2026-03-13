import httpx
import pytest

from src.models.enums import ContentSignal
from src.core.robots_parser import RobotsParser, fetch_robots_txt
from tests.conftest import mock_http_client


class TestIsAllowed:
    def test_empty_allows_everything(self):
        parser = RobotsParser("")
        assert parser.is_allowed("/anything") is True

    def test_whitespace_only_allows_everything(self):
        parser = RobotsParser("   \n\n  \n   ")
        assert parser.is_allowed("/anything") is True

    def test_comments_only_allows_everything(self):
        content = "# comment\n# another comment\n"
        parser = RobotsParser(content)
        assert parser.is_allowed("/anything") is True

    def test_disallow_empty_means_allow_all(self):
        parser = RobotsParser("User-agent: *\nDisallow:\n")
        assert parser.is_allowed("/anything") is True

    def test_disallow_path(self):
        parser = RobotsParser("User-agent: *\nDisallow: /private/")
        assert parser.is_allowed("/public/") is True
        assert parser.is_allowed("/private/") is False
        assert parser.is_allowed("/private/secret") is False

    def test_disallow_root_blocks_everything(self):
        parser = RobotsParser("User-agent: *\nDisallow: /\n")
        assert parser.is_allowed("/") is False
        assert parser.is_allowed("/anything") is False

    def test_multiple_disallow(self):
        content = "User-agent: *\nDisallow: /a/\nDisallow: /b/\nDisallow: /c/"
        parser = RobotsParser(content)
        assert parser.is_allowed("/a/page") is False
        assert parser.is_allowed("/b/page") is False
        assert parser.is_allowed("/c/page") is False
        assert parser.is_allowed("/d/page") is True

    def test_allow_overrides_shorter_disallow(self):
        content = "User-agent: *\nDisallow: /docs/\nAllow: /docs/public/"
        parser = RobotsParser(content)
        assert parser.is_allowed("/docs/private") is False
        assert parser.is_allowed("/docs/public/page") is True

    def test_longer_disallow_overrides_allow(self):
        content = "User-agent: *\nAllow: /docs/\nDisallow: /docs/internal/"
        parser = RobotsParser(content)
        assert parser.is_allowed("/docs/page") is True
        assert parser.is_allowed("/docs/internal/page") is False

    def test_allow_specific_under_disallow_all(self):
        content = "User-agent: *\nDisallow: /\nAllow: /public/"
        parser = RobotsParser(content)
        assert parser.is_allowed("/private") is False
        assert parser.is_allowed("/public/page") is True

    def test_wildcard_in_rule(self):
        parser = RobotsParser("User-agent: *\nDisallow: /api/*/internal")
        assert parser.is_allowed("/api/v1/internal") is False
        assert parser.is_allowed("/api/v2/internal") is False
        assert parser.is_allowed("/api/v1/public") is True

    def test_dollar_end_anchor(self):
        parser = RobotsParser("User-agent: *\nDisallow: /*.json$")
        assert parser.is_allowed("/data.json") is False
        assert parser.is_allowed("/data.json/extra") is True
        assert parser.is_allowed("/data.html") is True

    def test_rules_without_user_agent_ignored(self):
        parser = RobotsParser("Disallow: /secret/\nAllow: /public/")
        assert parser.is_allowed("/secret/") is True


class TestUserAgent:
    def test_specific_agent_match(self):
        content = (
            "User-agent: *\nDisallow: /\n\nUser-agent: DocCrawler\nDisallow: /secret/\n"
        )
        parser = RobotsParser(content, user_agent="DocCrawler")
        assert parser.is_allowed("/public/") is True
        assert parser.is_allowed("/secret/page") is False

    def test_falls_back_to_wildcard(self):
        parser = RobotsParser("User-agent: *\nDisallow: /blocked/", user_agent="MyBot")
        assert parser.is_allowed("/blocked/page") is False

    def test_no_matching_group_allows_all(self):
        parser = RobotsParser("User-agent: GoogleBot\nDisallow: /", user_agent="MyBot")
        assert parser.is_allowed("/anything") is True

    def test_multiple_user_agents_single_group(self):
        content = "User-agent: Googlebot\nUser-agent: Bingbot\nDisallow: /private/"
        assert (
            RobotsParser(content, user_agent="Googlebot").is_allowed("/private/x")
            is False
        )
        assert (
            RobotsParser(content, user_agent="Bingbot").is_allowed("/private/x")
            is False
        )


class TestCrawlDelay:
    def test_present(self):
        parser = RobotsParser("User-agent: *\nCrawl-delay: 2.5")
        assert parser.get_crawl_delay() == 2.5

    def test_absent(self):
        parser = RobotsParser("User-agent: *\nDisallow: /")
        assert parser.get_crawl_delay() is None

    def test_invalid_ignored(self):
        parser = RobotsParser("User-agent: *\nCrawl-delay: abc")
        assert parser.get_crawl_delay() is None


class TestSitemaps:
    def test_extracts_multiple(self):
        content = (
            "User-agent: *\nDisallow: /\n"
            "Sitemap: https://example.com/sitemap1.xml\n"
            "Sitemap: https://example.com/sitemap2.xml"
        )
        parser = RobotsParser(content)
        assert parser.get_sitemaps() == [
            "https://example.com/sitemap1.xml",
            "https://example.com/sitemap2.xml",
        ]

    def test_none_present(self):
        assert RobotsParser("User-agent: *\nDisallow: /").get_sitemaps() == []

    def test_colon_in_url_preserved(self):
        parser = RobotsParser("Sitemap: https://example.com/sitemap.xml")
        assert parser.get_sitemaps() == ["https://example.com/sitemap.xml"]


class TestContentSignalsGlobal:
    def test_all_signals_parsed(self):
        content = "User-agent: *\nContent-Signal: ai-train=no, search=yes, ai-input=no\nAllow: /"
        parser = RobotsParser(content)
        assert parser.get_content_signal(ContentSignal.AI_TRAIN) is False
        assert parser.get_content_signal(ContentSignal.SEARCH) is True
        assert parser.get_content_signal(ContentSignal.AI_INPUT) is False

    def test_ai_input_yes(self):
        content = "User-agent: *\nContent-Signal: ai-input=yes\nAllow: /"
        assert RobotsParser(content).is_ai_input_allowed() is True

    def test_ai_input_no(self):
        content = "User-agent: *\nContent-Signal: ai-input=no\nAllow: /"
        assert RobotsParser(content).is_ai_input_allowed() is False

    def test_not_specified(self):
        assert RobotsParser("User-agent: *\nAllow: /").is_ai_input_allowed() is None

    def test_partial_signals(self):
        content = "User-agent: *\nContent-Signal: ai-input=yes\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is True
        assert parser.get_content_signal(ContentSignal.SEARCH) is None
        assert parser.get_content_signal(ContentSignal.AI_TRAIN) is None

    def test_multiple_content_signal_lines(self):
        content = (
            "User-agent: *\n"
            "Content-Signal: ai-input=yes\n"
            "Content-Signal: ai-train=no\n"
            "Content-Signal: search=yes\n"
            "Allow: /"
        )
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is True
        assert parser.get_content_signal(ContentSignal.AI_TRAIN) is False
        assert parser.get_content_signal(ContentSignal.SEARCH) is True


class TestContentSignalsPerPath:
    def test_different_paths(self):
        content = (
            "User-agent: *\n"
            "Content-Signal: /about ai-train=yes, ai-input=yes\n"
            "Content-Signal: /blog/ ai-train=no, ai-input=no\n"
            "Allow: /"
        )
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed("/about") is True
        assert parser.is_ai_input_allowed("/about/team") is True
        assert parser.is_ai_input_allowed("/blog/post-1") is False
        assert parser.get_content_signal(ContentSignal.AI_TRAIN, "/about") is True
        assert parser.get_content_signal(ContentSignal.AI_TRAIN, "/blog/x") is False

    def test_specific_path_overrides_global(self):
        content = (
            "User-agent: *\n"
            "Content-Signal: ai-input=no\n"
            "Content-Signal: /docs/ ai-input=yes\n"
            "Allow: /"
        )
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed("/") is False
        assert parser.is_ai_input_allowed("/random") is False
        assert parser.is_ai_input_allowed("/docs/tutorial") is True

    def test_unmatched_path_returns_none(self):
        content = "User-agent: *\nContent-Signal: /docs/ ai-input=yes\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed("/docs/page") is True
        assert parser.is_ai_input_allowed("/blog/page") is None

    def test_with_disallow(self):
        content = (
            "User-agent: *\n"
            "Content-Signal: ai-input=no\n"
            "Content-Signal: /docs/ ai-input=yes\n"
            "Disallow: /api/"
        )
        parser = RobotsParser(content)
        assert parser.is_allowed("/docs/tutorial") is True
        assert parser.is_allowed("/api/v1") is False
        assert parser.is_ai_input_allowed("/docs/tutorial") is True
        assert parser.is_ai_input_allowed("/blog/post") is False


class TestContentSignalsPerUserAgent:
    def test_specific_agent(self):
        content = (
            "User-agent: *\nContent-Signal: ai-input=no\nAllow: /\n\n"
            "User-agent: DocCrawler\nContent-Signal: ai-input=yes\nAllow: /"
        )
        assert (
            RobotsParser(content, user_agent="DocCrawler").is_ai_input_allowed() is True
        )
        assert (
            RobotsParser(content, user_agent="OtherBot").is_ai_input_allowed() is False
        )


class TestContentSignalsPresets:
    def test_search_only(self):
        content = "User-agent: *\nContent-Signal: ai-train=no, search=yes, ai-input=no\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_allowed("/page") is True
        assert parser.is_ai_input_allowed() is False
        assert parser.get_content_signal(ContentSignal.SEARCH) is True
        assert parser.get_content_signal(ContentSignal.AI_TRAIN) is False

    def test_allow_all(self):
        content = "User-agent: *\nContent-Signal: ai-train=yes, search=yes, ai-input=yes\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is True
        assert parser.get_content_signal(ContentSignal.AI_TRAIN) is True

    def test_disallow_all(self):
        content = "User-agent: *\nContent-Signal: ai-train=no, search=no, ai-input=no\nDisallow: /"
        parser = RobotsParser(content)
        assert parser.is_allowed("/anything") is False
        assert parser.is_ai_input_allowed() is False
        assert parser.get_content_signal(ContentSignal.SEARCH) is False

    def test_per_agent_targeting(self):
        content = (
            "User-agent: googlebot\n"
            "Content-Signal: ai-train=no, search=yes, ai-input=no\n"
            "Allow: /\n\n"
            "User-agent: bingbot\n"
            "Content-Signal: ai-train=no, search=yes, ai-input=no\n"
            "Allow: /"
        )
        parser = RobotsParser(content, user_agent="googlebot")
        assert parser.is_ai_input_allowed() is False
        assert parser.get_content_signal(ContentSignal.SEARCH) is True


class TestMalformed:
    def test_comments_stripped(self):
        content = "# comment\nUser-agent: * # inline\nDisallow: /secret/ # keep out"
        parser = RobotsParser(content)
        assert parser.is_allowed("/secret/page") is False
        assert parser.is_allowed("/public/") is True

    def test_garbage_lines_skipped(self):
        content = "User-agent: *\nthis is garbage\nDisallow: /private/\nalso garbage"
        assert RobotsParser(content).is_allowed("/private/page") is False

    def test_mixed_case_directives(self):
        parser = RobotsParser(
            "User-Agent: *\nDISALLOW: /private/\nAlLoW: /private/open/"
        )
        assert parser.is_allowed("/private/secret") is False
        assert parser.is_allowed("/private/open/page") is True

    def test_windows_line_endings(self):
        parser = RobotsParser("User-agent: *\r\nDisallow: /private/\r\n")
        assert parser.is_allowed("/private/page") is False

    def test_tabs_as_whitespace(self):
        parser = RobotsParser("User-agent:\t*\nDisallow:\t/private/")
        assert parser.is_allowed("/private/page") is False

    def test_content_signal_without_user_agent(self):
        parser = RobotsParser("Content-Signal: ai-input=yes\n\nUser-agent: *\nAllow: /")
        assert parser.is_ai_input_allowed() is None

    def test_empty_content_signal_value(self):
        parser = RobotsParser("User-agent: *\nContent-Signal:\nAllow: /")
        assert parser.is_ai_input_allowed() is None

    def test_content_signal_no_equals(self):
        parser = RobotsParser(
            "User-agent: *\nContent-Signal: ai-input, search\nAllow: /"
        )
        assert parser.is_ai_input_allowed() is None

    def test_invalid_signal_key_ignored(self):
        content = "User-agent: *\nContent-Signal: ai-input=yes, bogus=no, search=yes\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is True
        assert parser.get_content_signal(ContentSignal.SEARCH) is True

    def test_invalid_signal_value_ignored(self):
        content = "User-agent: *\nContent-Signal: ai-input=maybe, search=yes\nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is None
        assert parser.get_content_signal(ContentSignal.SEARCH) is True

    def test_extra_whitespace_in_signals(self):
        content = "User-agent: *\nContent-Signal:  ai-input=yes ,  search=no \nAllow: /"
        parser = RobotsParser(content)
        assert parser.is_ai_input_allowed() is True
        assert parser.get_content_signal(ContentSignal.SEARCH) is False

    def test_very_large_file(self):
        lines = ["User-agent: *"]
        for i in range(1000):
            lines.append(f"Disallow: /path{i}/")
        parser = RobotsParser("\n".join(lines))
        assert parser.is_allowed("/path500/page") is False
        assert parser.is_allowed("/other/page") is True


class TestCombined:
    def test_typical_docs_site(self):
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /search\n"
            "Disallow: /_next/\n"
            "Crawl-delay: 1\n\n"
            "Sitemap: https://docs.example.com/sitemap.xml"
        )
        parser = RobotsParser(content)
        assert parser.is_allowed("/docs/getting-started") is True
        assert parser.is_allowed("/search") is False
        assert parser.is_allowed("/_next/static/chunk.js") is False
        assert parser.get_crawl_delay() == 1.0
        assert parser.get_sitemaps() == ["https://docs.example.com/sitemap.xml"]
        assert parser.is_ai_input_allowed() is None

    def test_everything_together(self):
        content = (
            "User-agent: *\n"
            "Content-Signal: ai-input=no, search=yes\n"
            "Content-Signal: /docs/ ai-input=yes\n"
            "Disallow: /admin/\n"
            "Allow: /\n"
            "Crawl-delay: 2\n\n"
            "User-agent: DocCrawler\n"
            "Content-Signal: ai-input=yes, ai-train=no\n"
            "Allow: /\n\n"
            "Sitemap: https://example.com/sitemap.xml"
        )
        wildcard = RobotsParser(content)
        assert wildcard.is_allowed("/page") is True
        assert wildcard.is_allowed("/admin/panel") is False
        assert wildcard.is_ai_input_allowed("/") is False
        assert wildcard.is_ai_input_allowed("/docs/tutorial") is True
        assert wildcard.get_crawl_delay() == 2.0
        assert wildcard.get_sitemaps() == ["https://example.com/sitemap.xml"]

        specific = RobotsParser(content, user_agent="DocCrawler")
        assert specific.is_allowed("/anything") is True
        assert specific.is_ai_input_allowed() is True
        assert specific.get_content_signal(ContentSignal.AI_TRAIN) is False
        assert specific.get_crawl_delay() is None


def _mock_response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/plain; charset=utf-8",
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com"),
    )


class TestFetchRobotsTxt:
    @pytest.mark.asyncio
    async def test_fetches_and_parses(self, mocker):
        content = "User-agent: *\nDisallow: /private/\nCrawl-delay: 2"
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(text=content))

        parser = await fetch_robots_txt("https://example.com", client)

        assert parser.is_allowed("/public/") is True
        assert parser.is_allowed("/private/secret") is False
        assert parser.get_crawl_delay() == 2.0

    @pytest.mark.asyncio
    async def test_returns_permissive_on_404(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(return_value=_mock_response(status_code=404))

        parser = await fetch_robots_txt("https://example.com", client)

        assert parser.is_allowed("/anything") is True
        assert parser.get_crawl_delay() is None

    @pytest.mark.asyncio
    async def test_returns_permissive_on_network_error(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get = mocker.AsyncMock(side_effect=httpx.ConnectError("fail"))

        parser = await fetch_robots_txt("https://example.com", client)

        assert parser.is_allowed("/anything") is True
