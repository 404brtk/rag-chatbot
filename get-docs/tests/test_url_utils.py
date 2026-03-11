from src.utils.url_utils import (
    normalize_url,
    extract_origin,
    extract_domain,
    extract_path,
    resolve_relative,
    is_same_domain,
    is_asset_url,
    is_absolute_url,
    has_md_extension,
    strip_git_suffix,
    url_path_parents,
    make_url_prefix,
    is_url_within_scope,
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


class TestExtractOrigin:
    def test_root_url(self):
        assert extract_origin("https://example.com") == "https://example.com"

    def test_strips_path(self):
        assert (
            extract_origin("https://example.com/docs/en/home") == "https://example.com"
        )

    def test_preserves_subdomain(self):
        assert (
            extract_origin("https://docs.example.com/tutorial")
            == "https://docs.example.com"
        )

    def test_preserves_port(self):
        assert extract_origin("http://localhost:8000/docs") == "http://localhost:8000"

    def test_lowercases(self):
        assert extract_origin("HTTPS://Example.COM/Docs") == "https://example.com"


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


class TestHasMdExtension:
    def test_simple_md(self):
        assert has_md_extension("https://example.com/docs/intro.md") is True

    def test_trailing_slash(self):
        assert has_md_extension("https://example.com/docs/intro.md/") is True

    def test_no_extension(self):
        assert has_md_extension("https://example.com/docs/intro") is False

    def test_html_extension(self):
        assert has_md_extension("https://example.com/docs/intro.html") is False

    def test_md_in_path_segment(self):
        assert has_md_extension("https://example.com/docs.md/intro") is False

    def test_mdx_extension(self):
        assert has_md_extension("https://example.com/docs/intro.mdx") is False


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


class TestUrlPathParents:
    def test_deep_path(self):
        assert url_path_parents("https://example.com/docs/en/home") == [
            "https://example.com/docs/en/home",
            "https://example.com/docs/en",
            "https://example.com/docs",
            "https://example.com",
        ]

    def test_root_url(self):
        assert url_path_parents("https://example.com") == [
            "https://example.com",
        ]

    def test_root_with_slash(self):
        assert url_path_parents("https://example.com/") == [
            "https://example.com",
        ]

    def test_single_segment(self):
        assert url_path_parents("https://example.com/docs") == [
            "https://example.com/docs",
            "https://example.com",
        ]

    def test_trailing_slash(self):
        assert url_path_parents("https://example.com/docs/en/") == [
            "https://example.com/docs/en",
            "https://example.com/docs",
            "https://example.com",
        ]

    def test_preserves_port(self):
        assert url_path_parents("http://localhost:8000/a/b") == [
            "http://localhost:8000/a/b",
            "http://localhost:8000/a",
            "http://localhost:8000",
        ]


class TestMakeUrlPrefix:
    def test_deep_path(self):
        assert (
            make_url_prefix("https://example.com/docs/en/home")
            == "https://example.com/docs/en/home"
        )

    def test_trailing_slash(self):
        assert (
            make_url_prefix("https://example.com/docs/en/")
            == "https://example.com/docs/en"
        )

    def test_root_url(self):
        assert make_url_prefix("https://example.com/") == "https://example.com"

    def test_root_no_slash(self):
        assert make_url_prefix("https://example.com") == "https://example.com"

    def test_strips_html_extension(self):
        assert (
            make_url_prefix("https://example.com/docs/page.html")
            == "https://example.com/docs"
        )

    def test_strips_md_extension(self):
        assert (
            make_url_prefix("https://example.com/docs/intro.md")
            == "https://example.com/docs"
        )

    def test_strips_php_extension(self):
        assert (
            make_url_prefix("https://example.com/blog/post.php")
            == "https://example.com/blog"
        )

    def test_strips_any_extension(self):
        assert (
            make_url_prefix("https://example.com/docs/page.txt")
            == "https://example.com/docs"
        )

    def test_dot_in_middle_segment_preserved(self):
        assert (
            make_url_prefix("https://example.com/docs/v2.0/guide")
            == "https://example.com/docs/v2.0/guide"
        )

    def test_strips_query_and_fragment(self):
        assert (
            make_url_prefix("https://example.com/docs?lang=en#top")
            == "https://example.com/docs"
        )

    def test_preserves_port(self):
        assert (
            make_url_prefix("http://localhost:8000/docs/en")
            == "http://localhost:8000/docs/en"
        )

    def test_lowercases_scheme_and_host(self):
        assert make_url_prefix("HTTPS://Example.COM/Docs") == "https://example.com/Docs"

    def test_html_at_root(self):
        assert (
            make_url_prefix("https://example.com/index.html") == "https://example.com"
        )


class TestIsUrlWithinScope:
    def test_exact_match(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs/en", "https://example.com/docs/en"
            )
            is True
        )

    def test_child_path(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs/en/intro", "https://example.com/docs/en"
            )
            is True
        )

    def test_deep_child(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs/en/api/v2", "https://example.com/docs/en"
            )
            is True
        )

    def test_sibling_rejected(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs/de/intro", "https://example.com/docs/en"
            )
            is False
        )

    def test_prefix_substring_rejected(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs/english", "https://example.com/docs/en"
            )
            is False
        )

    def test_parent_rejected(self):
        assert (
            is_url_within_scope(
                "https://example.com/docs", "https://example.com/docs/en"
            )
            is False
        )

    def test_root_prefix_matches_all(self):
        assert (
            is_url_within_scope("https://example.com/anything", "https://example.com")
            is True
        )

    def test_different_domain_rejected(self):
        assert (
            is_url_within_scope(
                "https://other.com/docs/en", "https://example.com/docs/en"
            )
            is False
        )
