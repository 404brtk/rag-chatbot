from src.utils.url_utils import (
    normalize_url,
    extract_domain,
    extract_path,
    resolve_relative,
    is_same_domain,
    path_starts_with,
    is_asset_url,
    is_absolute_url,
    strip_git_suffix,
)


class TestNormalizeUrl:
    def test_removes_trailing_slash(self):
        assert normalize_url("https://example.com/docs/") == "https://example.com/docs"

    def test_keeps_root_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_removes_fragment(self):
        assert (
            normalize_url("https://example.com/page#section")
            == "https://example.com/page"
        )

    def test_lowercases_scheme_and_host(self):
        assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"

    def test_keeps_non_default_port(self):
        assert (
            normalize_url("https://example.com:8080/page")
            == "https://example.com:8080/page"
        )

    def test_empty_path_becomes_root(self):
        assert normalize_url("https://example.com") == "https://example.com/"


class TestExtractDomain:
    def test_simple(self):
        assert (
            extract_domain("https://fastapi.tiangolo.com/tutorial")
            == "fastapi.tiangolo.com"
        )

    def test_with_port(self):
        assert extract_domain("http://localhost:8000/docs") == "localhost:8000"


class TestExtractPath:
    def test_simple(self):
        assert extract_path("https://example.com/docs/tutorial") == "/docs/tutorial"

    def test_root(self):
        assert extract_path("https://example.com/") == "/"


class TestResolveRelative:
    def test_relative_path(self):
        result = resolve_relative("https://example.com/docs/page", "../other")
        assert result == "https://example.com/other"

    def test_absolute_path(self):
        result = resolve_relative("https://example.com/docs/page", "/about")
        assert result == "https://example.com/about"

    def test_full_url_unchanged(self):
        result = resolve_relative("https://example.com/", "https://other.com/page")
        assert result == "https://other.com/page"


class TestIsSameDomain:
    def test_same(self):
        assert (
            is_same_domain("https://example.com/page", "https://example.com/other")
            is True
        )

    def test_different(self):
        assert (
            is_same_domain("https://example.com/page", "https://other.com/page")
            is False
        )

    def test_subdomain_is_different(self):
        assert (
            is_same_domain("https://sub.example.com/", "https://example.com/") is False
        )


class TestPathStartsWith:
    def test_match(self):
        assert path_starts_with("https://example.com/docs/tutorial", "/docs") is True

    def test_no_match(self):
        assert path_starts_with("https://example.com/blog/post", "/docs") is False

    def test_root(self):
        assert path_starts_with("https://example.com/anything", "/") is True


class TestIsAssetUrl:
    def test_pdf(self):
        assert is_asset_url("https://example.com/file.pdf") is True

    def test_image(self):
        assert is_asset_url("https://example.com/logo.png") is True

    def test_html_page(self):
        assert is_asset_url("https://example.com/docs/tutorial") is False

    def test_mailto(self):
        assert is_asset_url("mailto:test@example.com") is True

    def test_javascript(self):
        assert is_asset_url("javascript:void(0)") is True

    def test_css(self):
        assert is_asset_url("https://example.com/style.css") is True


class TestIsAbsoluteUrl:
    def test_https(self):
        assert is_absolute_url("https://example.com/page") is True

    def test_http(self):
        assert is_absolute_url("http://example.com/page") is True

    def test_relative_path(self):
        assert is_absolute_url("docs/page.md") is False

    def test_absolute_path_no_scheme(self):
        assert is_absolute_url("/docs/page") is False

    def test_protocol_relative(self):
        assert is_absolute_url("//example.com/page") is False

    def test_empty(self):
        assert is_absolute_url("") is False


class TestStripGitSuffix:
    def test_with_git_suffix(self):
        assert strip_git_suffix("my-repo.git") == "my-repo"

    def test_without_git_suffix(self):
        assert strip_git_suffix("my-repo") == "my-repo"

    def test_git_in_name(self):
        assert strip_git_suffix("my-git-repo") == "my-git-repo"

    def test_only_git(self):
        assert strip_git_suffix(".git") == ""

    def test_empty(self):
        assert strip_git_suffix("") == ""
