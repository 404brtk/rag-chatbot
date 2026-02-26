from src.core.github_discovery import discover_github_repo


def _html(body: str) -> str:
    return f"<html><body>{body}</body></html>"


class TestBasicDiscovery:
    def test_finds_simple_github_link(self):
        html = _html('<a href="https://github.com/fastapi/fastapi">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/fastapi/fastapi"

    def test_finds_link_without_text_hint(self):
        html = _html('<a href="https://github.com/owner/repo">Click here</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_strips_trailing_path_components(self):
        html = _html(
            '<a href="https://github.com/owner/repo/tree/main/docs">Source</a>'
        )
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_strips_issues_path(self):
        html = _html('<a href="https://github.com/owner/repo/issues">Issues</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_returns_none_for_no_github_links(self):
        html = _html('<a href="https://example.com">Example</a>')
        assert discover_github_repo(html) is None

    def test_returns_none_for_empty_html(self):
        assert discover_github_repo("") is None

    def test_returns_none_for_no_links(self):
        html = _html("<p>No links here</p>")
        assert discover_github_repo(html) is None


class TestHintPriority:
    def test_prefers_hinted_link_over_unhinted(self):
        html = _html(
            '<a href="https://github.com/wrong/repo">Some text</a>'
            '<a href="https://github.com/right/repo">View on GitHub</a>'
        )
        assert discover_github_repo(html) == "https://github.com/right/repo"

    def test_github_in_link_text_is_hint(self):
        html = _html('<a href="https://github.com/owner/repo">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_source_code_text_is_hint(self):
        html = _html('<a href="https://github.com/owner/repo">Source Code</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_aria_label_hint(self):
        html = _html(
            '<a href="https://github.com/wrong/repo">Random</a>'
            '<a href="https://github.com/right/repo" aria-label="View on GitHub">X</a>'
        )
        assert discover_github_repo(html) == "https://github.com/right/repo"

    def test_title_attr_hint(self):
        html = _html(
            '<a href="https://github.com/wrong/repo">Random</a>'
            '<a href="https://github.com/right/repo" title="GitHub Repository">X</a>'
        )
        assert discover_github_repo(html) == "https://github.com/right/repo"

    def test_svg_icon_is_hint(self):
        html = _html(
            '<a href="https://github.com/wrong/repo">Text</a>'
            '<a href="https://github.com/right/repo"><svg></svg></a>'
        )
        assert discover_github_repo(html) == "https://github.com/right/repo"

    def test_github_img_alt_is_hint(self):
        html = _html(
            '<a href="https://github.com/wrong/repo">Text</a>'
            '<a href="https://github.com/right/repo">'
            '<img alt="GitHub logo" src="icon.png">'
            "</a>"
        )
        assert discover_github_repo(html) == "https://github.com/right/repo"

    def test_first_hinted_wins_when_multiple(self):
        html = _html(
            '<a href="https://github.com/first/repo">GitHub</a>'
            '<a href="https://github.com/second/repo">Source</a>'
        )
        assert discover_github_repo(html) == "https://github.com/first/repo"

    def test_first_unhinted_wins_when_no_hints(self):
        html = _html(
            '<a href="https://github.com/first/repo">Click</a>'
            '<a href="https://github.com/second/repo">Here</a>'
        )
        assert discover_github_repo(html) == "https://github.com/first/repo"


class TestNonRepoFiltering:
    def test_rejects_github_features_page(self):
        html = _html('<a href="https://github.com/features/actions">GitHub Actions</a>')
        assert discover_github_repo(html) is None

    def test_rejects_github_pricing_page(self):
        html = _html('<a href="https://github.com/pricing/team">Pricing</a>')
        assert discover_github_repo(html) is None

    def test_rejects_github_explore_page(self):
        html = _html('<a href="https://github.com/explore/trending">Explore</a>')
        assert discover_github_repo(html) is None

    def test_rejects_github_login_page(self):
        html = _html('<a href="https://github.com/login/oauth">Login</a>')
        assert discover_github_repo(html) is None

    def test_accepts_real_repo_alongside_non_repo(self):
        html = _html(
            '<a href="https://github.com/features/actions">Actions</a>'
            '<a href="https://github.com/owner/repo">Repo</a>'
        )
        assert discover_github_repo(html) == "https://github.com/owner/repo"


class TestEdgeCases:
    def test_git_suffix_stripped(self):
        html = _html('<a href="https://github.com/owner/repo.git">Source</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_http_scheme(self):
        html = _html('<a href="http://github.com/owner/repo">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_link_with_query_params(self):
        html = _html('<a href="https://github.com/owner/repo?tab=readme">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_link_with_fragment(self):
        html = _html('<a href="https://github.com/owner/repo#readme">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_multiple_github_links_same_repo(self):
        html = _html(
            '<a href="https://github.com/owner/repo/issues">Issues</a>'
            '<a href="https://github.com/owner/repo/pulls">PRs</a>'
            '<a href="https://github.com/owner/repo">GitHub</a>'
        )
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_handles_malformed_html(self):
        html = '<a href="https://github.com/owner/repo">GitHub'
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_link_text_case_insensitive(self):
        html = _html('<a href="https://github.com/owner/repo">VIEW ON GITHUB</a>')
        assert discover_github_repo(html) == "https://github.com/owner/repo"

    def test_owner_with_hyphens(self):
        html = _html('<a href="https://github.com/my-org/my-repo">GitHub</a>')
        assert discover_github_repo(html) == "https://github.com/my-org/my-repo"

    def test_no_href_attribute(self):
        html = _html('<a name="anchor">No href</a>')
        assert discover_github_repo(html) is None


class TestRealisticPages:
    def test_typical_doc_site_header(self):
        html = """
        <html><head><title>My Docs</title></head>
        <body>
            <nav>
                <a href="/">Home</a>
                <a href="/docs">Docs</a>
                <a href="/api">API</a>
                <a href="https://github.com/myorg/mylib" aria-label="GitHub">
                    <svg viewBox="0 0 16 16"><path d="M8 0C3.58..."></path></svg>
                </a>
            </nav>
            <main>
                <h1>Welcome to MyLib</h1>
                <p>Get started with our library.</p>
            </main>
            <footer>
                <a href="https://github.com/myorg/mylib/issues">Report a bug</a>
            </footer>
        </body></html>
        """
        assert discover_github_repo(html) == "https://github.com/myorg/mylib"

    def test_edit_on_github_link(self):
        html = """
        <html><body>
            <main>
                <h1>API Reference</h1>
                <p>Some documentation content.</p>
            </main>
            <aside>
                <a href="https://github.com/org/project/edit/main/docs/api.md">
                    Edit on GitHub
                </a>
            </aside>
        </body></html>
        """
        assert discover_github_repo(html) == "https://github.com/org/project"

    def test_page_with_many_non_github_links(self):
        html = """
        <html><body>
            <a href="https://example.com">Example</a>
            <a href="https://docs.python.org">Python Docs</a>
            <a href="https://pypi.org/project/mylib">PyPI</a>
            <a href="https://twitter.com/mylib">Twitter</a>
            <a href="https://github.com/myorg/mylib">Source Code</a>
            <a href="https://discord.gg/invite">Discord</a>
        </body></html>
        """
        assert discover_github_repo(html) == "https://github.com/myorg/mylib"
