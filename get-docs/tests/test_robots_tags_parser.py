import httpx
import pytest

from src.core.page_fetcher import _fetch_html, probe_and_fetch
from src.core.robots_tags_parser import (
    RobotsMetaBlocked,
    check_html_meta,
    has_nofollow_header,
    is_html_blocked,
    is_response_blocked,
    parse_robots_directives,
)
from src.models.enums import SourceMethod
from tests.conftest import mock_http_client, mock_response


def _response(headers: list[tuple[str, str]]) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        text="",
        headers=headers,
        request=httpx.Request("GET", "https://example.com"),
    )


class TestParseRobotsDirectives:
    def test_single_noindex(self):
        assert parse_robots_directives("noindex") == {"noindex"}

    def test_multiple_directives(self):
        assert parse_robots_directives("noindex, nofollow") == {"noindex", "nofollow"}

    def test_case_insensitive(self):
        assert parse_robots_directives("NoIndex, NoFollow") == {"noindex", "nofollow"}

    def test_bot_targeted_ignored_for_global(self):
        result = parse_robots_directives("BadBot: noindex, nofollow")
        assert result == set()

    def test_bot_targeted_matched(self):
        result = parse_robots_directives("get-docs: noindex", bot_name="get-docs")
        assert result == {"noindex"}

    def test_global_plus_bot_targeted(self):
        result = parse_robots_directives(
            "nofollow, get-docs: noindex", bot_name="get-docs"
        )
        assert result == {"nofollow", "noindex"}

    def test_bot_targeted_case_insensitive(self):
        result = parse_robots_directives("Get-Docs: noindex", bot_name="get-docs")
        assert result == {"noindex"}

    def test_other_bot_ignored(self):
        result = parse_robots_directives("otherbot: noindex", bot_name="get-docs")
        assert result == set()

    def test_context_tracking(self):
        result = parse_robots_directives(
            "BadBot: noindex, nofollow, googlebot: nofollow"
        )
        assert result == set()

    def test_context_tracking_with_matching_bot(self):
        result = parse_robots_directives(
            "BadBot: noindex, nofollow, get-docs: none", bot_name="get-docs"
        )
        assert result == {"none"}

    def test_empty_value(self):
        assert parse_robots_directives("") == set()

    def test_none_directive(self):
        assert parse_robots_directives("none") == {"none"}


class TestIsResponseBlocked:
    def test_noindex_blocks(self):
        resp = _response([("x-robots-tag", "noindex")])
        assert is_response_blocked(resp) is True

    def test_none_blocks(self):
        resp = _response([("x-robots-tag", "none")])
        assert is_response_blocked(resp) is True

    def test_nofollow_does_not_block(self):
        resp = _response([("x-robots-tag", "nofollow")])
        assert is_response_blocked(resp) is False

    def test_noarchive_does_not_block(self):
        resp = _response([("x-robots-tag", "noarchive")])
        assert is_response_blocked(resp) is False

    def test_nosnippet_does_not_block(self):
        resp = _response([("x-robots-tag", "nosnippet")])
        assert is_response_blocked(resp) is False

    def test_no_header(self):
        resp = _response([])
        assert is_response_blocked(resp) is False

    def test_multiple_headers(self):
        resp = _response(
            [
                ("x-robots-tag", "nofollow"),
                ("x-robots-tag", "noindex"),
            ]
        )
        assert is_response_blocked(resp) is True

    def test_bot_targeted_blocks(self):
        resp = _response([("x-robots-tag", "get-docs: noindex")])
        assert is_response_blocked(resp, bot_name="get-docs") is True

    def test_bot_targeted_other_bot_does_not_block(self):
        resp = _response([("x-robots-tag", "otherbot: noindex")])
        assert is_response_blocked(resp, bot_name="get-docs") is False


class TestHasNofollowHeader:
    def test_nofollow_header(self):
        resp = _response([("x-robots-tag", "nofollow")])
        assert has_nofollow_header(resp) is True

    def test_noindex_header_not_nofollow(self):
        resp = _response([("x-robots-tag", "noindex")])
        assert has_nofollow_header(resp) is False

    def test_none_not_nofollow(self):
        resp = _response([("x-robots-tag", "none")])
        assert has_nofollow_header(resp) is False

    def test_bot_targeted_nofollow(self):
        resp = _response([("x-robots-tag", "get-docs: nofollow")])
        assert has_nofollow_header(resp, bot_name="get-docs") is True

    def test_no_header(self):
        resp = _response([])
        assert has_nofollow_header(resp) is False


class TestIsHtmlBlocked:
    def test_noindex_blocks(self):
        html = '<html><head><meta name="robots" content="noindex"></head><body></body></html>'
        assert is_html_blocked(html) is True

    def test_none_blocks(self):
        html = (
            '<html><head><meta name="robots" content="none"></head><body></body></html>'
        )
        assert is_html_blocked(html) is True

    def test_nofollow_does_not_block(self):
        html = '<html><head><meta name="robots" content="nofollow"></head><body></body></html>'
        assert is_html_blocked(html) is False

    def test_noarchive_does_not_block(self):
        html = '<html><head><meta name="robots" content="noarchive"></head><body></body></html>'
        assert is_html_blocked(html) is False

    def test_nosnippet_does_not_block(self):
        html = '<html><head><meta name="robots" content="nosnippet"></head><body></body></html>'
        assert is_html_blocked(html) is False

    def test_no_meta_tag(self):
        html = "<html><head><title>Test</title></head><body></body></html>"
        assert is_html_blocked(html) is False

    def test_mixed_directives(self):
        html = '<html><head><meta name="robots" content="nofollow, noindex"></head><body></body></html>'
        assert is_html_blocked(html) is True

    def test_case_insensitive(self):
        html = '<html><head><meta name="robots" content="NoIndex"></head><body></body></html>'
        assert is_html_blocked(html) is True

    def test_other_meta_name_ignored(self):
        html = '<html><head><meta name="description" content="noindex"></head><body></body></html>'
        assert is_html_blocked(html) is False

    def test_bot_targeted_blocks(self):
        html = '<html><head><meta name="get-docs" content="noindex"></head><body></body></html>'
        assert is_html_blocked(html, bot_name="get-docs") is True

    def test_bot_targeted_other_bot_does_not_block(self):
        html = '<html><head><meta name="otherbot" content="noindex"></head><body></body></html>'
        assert is_html_blocked(html, bot_name="get-docs") is False


class TestCheckHtmlMeta:
    def test_noindex_blocked_no_nofollow(self):
        html = '<html><head><meta name="robots" content="noindex"></head><body></body></html>'
        blocked, nofollow = check_html_meta(html)
        assert blocked is True
        assert nofollow is False

    def test_nofollow_not_blocked(self):
        html = '<html><head><meta name="robots" content="nofollow"></head><body></body></html>'
        blocked, nofollow = check_html_meta(html)
        assert blocked is False
        assert nofollow is True

    def test_both_noindex_and_nofollow(self):
        html = '<html><head><meta name="robots" content="noindex, nofollow"></head><body></body></html>'
        blocked, nofollow = check_html_meta(html)
        assert blocked is True
        assert nofollow is True

    def test_clean_page(self):
        html = "<html><head><title>Test</title></head><body></body></html>"
        blocked, nofollow = check_html_meta(html)
        assert blocked is False
        assert nofollow is False

    def test_bot_targeted_nofollow(self):
        html = '<html><head><meta name="get-docs" content="nofollow"></head><body></body></html>'
        blocked, nofollow = check_html_meta(html, bot_name="get-docs")
        assert blocked is False
        assert nofollow is True

    def test_other_bot_nofollow_ignored(self):
        html = '<html><head><meta name="otherbot" content="nofollow"></head><body></body></html>'
        blocked, nofollow = check_html_meta(html, bot_name="get-docs")
        assert blocked is False
        assert nofollow is False


class TestPageFetcherIntegration:
    @pytest.mark.asyncio
    async def test_fetch_html_raises_on_x_robots_tag(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get.return_value = mock_response(
            text="<html><head><title>Hi</title></head><body><main>content</main></body></html>",
            extra_headers={"x-robots-tag": "noindex"},
        )
        with pytest.raises(RobotsMetaBlocked):
            await _fetch_html(
                "https://example.com/page", client, 10, SourceMethod.SITEMAP_CRAWL
            )

    @pytest.mark.asyncio
    async def test_fetch_html_raises_on_meta_robots(self, mocker):
        client, inner = mock_http_client(mocker)
        html = '<html><head><meta name="robots" content="noindex"><title>Hi</title></head><body><main>content</main></body></html>'
        inner.get.return_value = mock_response(text=html)
        with pytest.raises(RobotsMetaBlocked):
            await _fetch_html(
                "https://example.com/page", client, 10, SourceMethod.SITEMAP_CRAWL
            )

    @pytest.mark.asyncio
    async def test_probe_and_fetch_no_fallback_when_blocked(self, mocker):
        client, inner = mock_http_client(mocker)
        inner.get.return_value = mock_response(
            text="",
            content_type="text/plain",
            extra_headers={"x-robots-tag": "noindex"},
        )
        with pytest.raises(RobotsMetaBlocked):
            await probe_and_fetch(
                "https://example.com/docs/page", client, 10, SourceMethod.SITEMAP_CRAWL
            )
        assert inner.get.call_count == 1
