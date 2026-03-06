import httpx
import pytest

from src.core.github_fetcher import (
    ALLOWED_LICENSES,
    GitHubFile,
    GitHubFetchResult,
    ParsedGitHubURL,
    parse_github_url,
    fetch_github_docs,
    _fetch_repo_meta,
    _is_doc_file,
    _find_doc_folder,
    _narrow_to_english,
    DOC_EXTENSIONS,
    DOC_FOLDERS,
    SKIP_FILES,
    SKIP_DIRS,
)
from tests.conftest import mock_response


class TestParseGithubUrl:
    def test_standard_url(self):
        result = parse_github_url("https://github.com/fastapi/fastapi")
        assert result == ParsedGitHubURL("fastapi", "fastapi")

    def test_url_with_trailing_slash(self):
        result = parse_github_url("https://github.com/pydantic/pydantic/")
        assert result == ParsedGitHubURL("pydantic", "pydantic")

    def test_url_with_tree_path(self):
        result = parse_github_url("https://github.com/owner/repo/tree/main/docs")
        assert result == ParsedGitHubURL("owner", "repo", branch="main", subpath="docs")

    def test_url_with_deep_tree_path(self):
        result = parse_github_url(
            "https://github.com/owner/repo/tree/main/packages/docs"
        )
        assert result == ParsedGitHubURL(
            "owner", "repo", branch="main", subpath="packages/docs"
        )

    def test_url_with_tree_branch_only(self):
        result = parse_github_url("https://github.com/owner/repo/tree/develop")
        assert result == ParsedGitHubURL("owner", "repo", branch="develop")

    def test_url_with_blob_path(self):
        result = parse_github_url("https://github.com/owner/repo/blob/main/README.md")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_url_without_scheme(self):
        result = parse_github_url("github.com/owner/repo")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_http_scheme(self):
        result = parse_github_url("http://github.com/owner/repo")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_dot_git_suffix_stripped(self):
        result = parse_github_url("https://github.com/owner/repo.git")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_rejects_non_github_url(self):
        result = parse_github_url("https://gitlab.com/owner/repo")
        assert result is None

    def test_rejects_empty_string(self):
        result = parse_github_url("")
        assert result is None

    def test_rejects_github_pages(self):
        result = parse_github_url("https://github.com/features/actions")
        assert result is None

    def test_rejects_explore_page(self):
        result = parse_github_url("https://github.com/explore/trending")
        assert result is None

    def test_rejects_settings_page(self):
        result = parse_github_url("https://github.com/settings/profile")
        assert result is None

    def test_case_insensitive_rejection(self):
        result = parse_github_url("https://github.com/Features/something")
        assert result is None

    def test_preserves_case_of_owner_and_repo(self):
        result = parse_github_url("https://github.com/FastAPI/FastAPI")
        assert result == ParsedGitHubURL("FastAPI", "FastAPI")

    def test_url_with_query_params(self):
        result = parse_github_url("https://github.com/owner/repo?tab=repositories")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_url_with_fragment(self):
        result = parse_github_url("https://github.com/owner/repo#readme")
        assert result == ParsedGitHubURL("owner", "repo")

    def test_embedded_in_text(self):
        result = parse_github_url(
            "Check out https://github.com/owner/repo for more info"
        )
        assert result == ParsedGitHubURL("owner", "repo")

    def test_only_owner_no_repo(self):
        result = parse_github_url("https://github.com/owner")
        assert result is None

    def test_owner_with_hyphens(self):
        result = parse_github_url("https://github.com/my-org/my-repo")
        assert result == ParsedGitHubURL("my-org", "my-repo")

    def test_owner_with_dots(self):
        result = parse_github_url("https://github.com/my.org/my.repo")
        assert result == ParsedGitHubURL("my.org", "my.repo")

    def test_trailing_slash_in_subpath_stripped(self):
        result = parse_github_url("https://github.com/owner/repo/tree/main/docs/")
        assert result == ParsedGitHubURL("owner", "repo", branch="main", subpath="docs")


class TestFindDocFolder:
    def test_finds_docs_folder(self):
        paths = ["docs/index.md", "src/main.py", "README.md"]
        assert _find_doc_folder(paths) == "docs"

    def test_finds_doc_folder(self):
        paths = ["doc/index.md", "src/main.py"]
        assert _find_doc_folder(paths) == "doc"

    def test_finds_documentation_folder(self):
        paths = ["documentation/index.md", "src/main.py"]
        assert _find_doc_folder(paths) == "documentation"

    def test_finds_guide_folder(self):
        paths = ["guide/intro.md", "src/main.py"]
        assert _find_doc_folder(paths) == "guide"

    def test_finds_content_folder(self):
        paths = ["content/intro.md", "src/main.py"]
        assert _find_doc_folder(paths) == "content"

    def test_prefers_docs_over_doc(self):
        paths = ["docs/a.md", "doc/b.md", "src/main.py"]
        assert _find_doc_folder(paths) == "docs"

    def test_no_doc_folder(self):
        paths = ["src/main.py", "README.md", "setup.py"]
        assert _find_doc_folder(paths) is None

    def test_empty_paths(self):
        assert _find_doc_folder([]) is None

    def test_root_only_files(self):
        paths = ["README.md", "setup.py", "main.py"]
        assert _find_doc_folder(paths) is None

    def test_case_insensitive_match(self):
        paths = ["Docs/index.md", "src/main.py"]
        assert _find_doc_folder(paths) == "Docs"

    def test_deeply_nested_docs_not_detected_as_top_level(self):
        paths = ["src/docs/index.md", "main.py"]
        result = _find_doc_folder(paths)
        assert result == "src/docs"

    def test_prefers_shallower_over_deeper_docs(self):
        paths = [
            "docs/index.md",
            "docs/en/docs/intro.md",
        ]
        assert _find_doc_folder(paths) == "docs"

    def test_prefers_content_over_nested_docs(self):
        paths = [
            "content/index.md",
            "content/docs/intro.md",
        ]
        assert _find_doc_folder(paths) == "content"

    def test_monorepo_docs_folder_detected(self):
        paths = ["packages/docs/quickstart.mdx", "packages/app/main.ts"]
        assert _find_doc_folder(paths) == "packages/docs"

    def test_root_only_finds_top_level_docs(self):
        paths = ["docs/index.md", "src/main.py"]
        assert _find_doc_folder(paths, root_only=True) == "docs"

    def test_root_only_ignores_nested_docs(self):
        paths = ["packages/docs/quickstart.mdx", "packages/app/main.ts"]
        assert _find_doc_folder(paths, root_only=True) is None

    def test_root_only_prefers_docs_over_doc(self):
        paths = ["docs/a.md", "doc/b.md", "src/main.py"]
        assert _find_doc_folder(paths, root_only=True) == "docs"

    def test_root_only_case_insensitive(self):
        paths = ["Docs/index.md", "src/main.py"]
        assert _find_doc_folder(paths, root_only=True) == "Docs"

    def test_root_only_no_doc_folder(self):
        paths = ["src/main.py", "README.md"]
        assert _find_doc_folder(paths, root_only=True) is None


class TestNarrowToEnglish:
    def test_picks_en_when_present(self):
        paths = [
            "docs/en/tutorial.md",
            "docs/de/tutorial.md",
            "docs/fr/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en"
        assert excludes == set()

    def test_no_en_with_lang_dirs_excludes_them(self):
        paths = [
            "docs/index.md",
            "docs/de/tutorial.md",
            "docs/fr/tutorial.md",
            "docs/ja/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs"
        assert excludes == {"docs/de", "docs/fr", "docs/ja"}

    def test_en_is_only_subfolder(self):
        paths = [
            "docs/en/tutorial.md",
            "docs/api/reference.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en"
        assert excludes == set()

    def test_no_en_subfolder_normal_folders(self):
        paths = [
            "docs/tutorial/intro.md",
            "docs/api/reference.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs"
        assert excludes == set()

    def test_none_doc_folder_returns_none(self):
        paths = ["README.md", "src/main.py"]
        folder, excludes = _narrow_to_english(paths, None)
        assert folder is None
        assert excludes == set()

    def test_prefers_en_over_en_us(self):
        paths = [
            "docs/en/tutorial.md",
            "docs/en-us/tutorial.md",
            "docs/fr/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en"
        assert excludes == set()

    def test_falls_back_to_en_us(self):
        paths = [
            "docs/en-us/tutorial.md",
            "docs/fr/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en-us"
        assert excludes == set()

    def test_falls_back_to_en_gb(self):
        paths = [
            "docs/en-gb/tutorial.md",
            "docs/fr/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en-gb"
        assert excludes == set()

    def test_case_insensitive_path_matching(self):
        paths = [
            "Docs/en/tutorial.md",
            "Docs/de/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "Docs")
        assert folder == "Docs/en"
        assert excludes == set()

    def test_empty_paths(self):
        folder, excludes = _narrow_to_english([], "docs")
        assert folder == "docs"
        assert excludes == set()

    def test_root_files_in_doc_folder_ignored(self):
        # root files directly under docs/ have no child dir — shouldn't crash
        paths = [
            "docs/index.md",
            "docs/en/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en"
        assert excludes == set()

    def test_fastapi_style_deep_nesting(self):
        paths = [
            "docs/en/docs/tutorial/first-steps.md",
            "docs/de/docs/tutorial/first-steps.md",
            "docs/fr/docs/tutorial/first-steps.md",
            "docs/zh/docs/tutorial/first-steps.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs/en"
        assert excludes == set()

    def test_kubernetes_style(self):
        paths = [
            "content/en/docs/concepts/intro.md",
            "content/zh-cn/docs/concepts/intro.md",
            "content/ko/docs/concepts/intro.md",
        ]
        folder, excludes = _narrow_to_english(paths, "content")
        assert folder == "content/en"
        assert excludes == set()

    def test_english_at_root_with_lang_subdirs(self):
        paths = [
            "docs/agents.mdx",
            "docs/config.mdx",
            "docs/ar/agents.mdx",
            "docs/ar/config.mdx",
            "docs/de/agents.mdx",
            "docs/de/config.mdx",
            "docs/fr/agents.mdx",
            "docs/fr/config.mdx",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs"
        assert excludes == {"docs/ar", "docs/de", "docs/fr"}

    def test_single_lang_dir_not_excluded(self):
        paths = [
            "docs/index.md",
            "docs/go/tutorial.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs"
        assert excludes == set()

    def test_deep_doc_folder_with_lang_subdirs(self):
        paths = [
            "packages/web/src/content/docs/agents.mdx",
            "packages/web/src/content/docs/ar/agents.mdx",
            "packages/web/src/content/docs/de/agents.mdx",
            "packages/web/src/content/docs/fr/agents.mdx",
        ]
        folder, excludes = _narrow_to_english(paths, "packages/web/src/content/docs")
        assert folder == "packages/web/src/content/docs"
        assert excludes == {
            "packages/web/src/content/docs/ar",
            "packages/web/src/content/docs/de",
            "packages/web/src/content/docs/fr",
        }

    def test_locale_codes_excluded(self):
        paths = [
            "docs/index.md",
            "docs/pt-br/index.md",
            "docs/zh-cn/index.md",
        ]
        folder, excludes = _narrow_to_english(paths, "docs")
        assert folder == "docs"
        assert excludes == {"docs/pt-br", "docs/zh-cn"}


class TestIsDocFile:
    # --- with doc folder ---

    def test_md_in_doc_folder(self):
        assert _is_doc_file("docs/guide.md", "docs") is True

    def test_mdx_in_doc_folder(self):
        assert _is_doc_file("docs/guide.mdx", "docs") is True

    def test_rst_in_doc_folder(self):
        assert _is_doc_file("docs/guide.rst", "docs") is True

    def test_nested_in_doc_folder(self):
        assert _is_doc_file("docs/api/reference.md", "docs") is True

    def test_python_file_in_doc_folder_rejected(self):
        assert _is_doc_file("docs/conf.py", "docs") is False

    def test_file_outside_doc_folder_rejected(self):
        assert _is_doc_file("src/readme.md", "docs") is False

    def test_root_file_rejected_when_doc_folder_exists(self):
        assert _is_doc_file("README.md", "docs") is False

    def test_doc_folder_case_insensitive(self):
        assert _is_doc_file("Docs/guide.md", "Docs") is True

    # --- without doc folder ---

    def test_root_md_accepted(self):
        assert _is_doc_file("README.md", None) is True

    def test_root_skip_file_changelog(self):
        assert _is_doc_file("CHANGELOG.md", None) is False

    def test_root_skip_file_contributing(self):
        assert _is_doc_file("CONTRIBUTING.md", None) is False

    def test_root_skip_file_license(self):
        assert _is_doc_file("LICENSE.md", None) is False

    def test_root_skip_file_code_of_conduct(self):
        assert _is_doc_file("CODE_OF_CONDUCT.md", None) is False

    def test_root_skip_file_security(self):
        assert _is_doc_file("SECURITY.md", None) is False

    def test_recognized_subfolder_accepted_without_doc_folder(self):
        assert _is_doc_file("docs/intro.md", None) is True

    def test_non_doc_extension_rejected(self):
        assert _is_doc_file("docs/script.py", None) is False

    def test_file_in_tests_dir_rejected(self):
        assert _is_doc_file("tests/test_readme.md", None) is False

    def test_file_in_github_dir_rejected(self):
        assert _is_doc_file(".github/PULL_REQUEST_TEMPLATE.md", None) is False

    def test_file_in_node_modules_rejected(self):
        assert _is_doc_file("node_modules/pkg/README.md", None) is False

    def test_file_in_pycache_rejected(self):
        assert _is_doc_file("__pycache__/something.md", None) is False

    def test_nested_skip_dir_rejected(self):
        assert _is_doc_file("docs/tests/fixture.md", "docs") is False

    def test_examples_dir_rejected(self):
        assert _is_doc_file("examples/tutorial.md", None) is False

    def test_empty_path(self):
        assert _is_doc_file("", None) is False

    def test_no_extension(self):
        assert _is_doc_file("docs/Makefile", "docs") is False

    def test_hidden_file(self):
        assert _is_doc_file("docs/.hidden.md", "docs") is True

    def test_deeply_nested_doc(self):
        assert _is_doc_file("docs/api/v2/endpoints/users.md", "docs") is True

    def test_narrowed_lang_folder_accepts_english(self):
        assert _is_doc_file("docs/en/tutorial.md", "docs/en") is True

    def test_narrowed_lang_folder_rejects_other_lang(self):
        assert _is_doc_file("docs/de/tutorial.md", "docs/en") is False

    def test_narrowed_lang_folder_accepts_nested(self):
        assert _is_doc_file("docs/en/api/reference.md", "docs/en") is True

    def test_narrowed_lang_folder_rejects_root_doc(self):
        assert _is_doc_file("docs/index.md", "docs/en") is False

    def test_file_in_unknown_subdir_without_doc_folder(self):
        # no doc folder, file in a non-recognized subdir
        assert _is_doc_file("src/notes.md", None) is False


class TestGitHubFetchResult:
    def test_default_empty_files(self):
        result = GitHubFetchResult(
            owner="owner", repo="repo", branch="main", doc_folder="docs"
        )
        assert result.files == []

    def test_files_stored(self):
        result = GitHubFetchResult(
            owner="owner",
            repo="repo",
            branch="main",
            doc_folder="docs",
            files=[GitHubFile(path="docs/intro.md", content="# Intro")],
        )
        assert len(result.files) == 1
        assert result.files[0].path == "docs/intro.md"
        assert result.files[0].content == "# Intro"

    def test_doc_folder_can_be_none(self):
        result = GitHubFetchResult(
            owner="owner", repo="repo", branch="main", doc_folder=None
        )
        assert result.doc_folder is None


class TestSkipLists:
    def test_all_skip_files_are_lowercase(self):
        for f in SKIP_FILES:
            assert f == f.lower(), f"SKIP_FILES entry not lowercase: {f}"

    def test_all_skip_dirs_are_lowercase(self):
        for d in SKIP_DIRS:
            assert d == d.lower(), f"SKIP_DIRS entry not lowercase: {d}"

    def test_doc_extensions_have_dots(self):
        for ext in DOC_EXTENSIONS:
            assert ext.startswith("."), f"DOC_EXTENSIONS entry missing dot: {ext}"

    def test_all_doc_folders_are_lowercase(self):
        for f in DOC_FOLDERS:
            assert f == f.lower(), f"DOC_FOLDERS entry not lowercase: {f}"


class TestFetchRepoMeta:
    @pytest.mark.asyncio
    async def test_returns_spdx_id_and_branch(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                json_data={
                    "license": {"spdx_id": "MIT", "name": "MIT License"},
                    "default_branch": "main",
                }
            )
        )
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.spdx_id == "MIT"
        assert meta.default_branch == "main"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_license(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                json_data={"license": None, "default_branch": "main"}
            )
        )
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.spdx_id is None
        assert meta.default_branch == "main"

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(return_value=mock_response(status_code=404))
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.spdx_id is None
        assert meta.default_branch is None

    @pytest.mark.asyncio
    async def test_returns_none_on_timeout(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.spdx_id is None
        assert meta.default_branch is None

    @pytest.mark.asyncio
    async def test_returns_noassertion(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                json_data={
                    "license": {"spdx_id": "NOASSERTION"},
                    "default_branch": "dev",
                }
            )
        )
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.spdx_id == "NOASSERTION"
        assert meta.default_branch == "dev"

    @pytest.mark.asyncio
    async def test_non_standard_default_branch(self, mocker):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)
        client.get = mocker.AsyncMock(
            return_value=mock_response(
                json_data={
                    "license": {"spdx_id": "MIT"},
                    "default_branch": "dev",
                }
            )
        )
        meta = await _fetch_repo_meta(client, "owner", "repo", 10)
        assert meta.default_branch == "dev"


class TestFetchGithubDocsLicenseGate:
    def _make_client(self, mocker, license_spdx_id):
        client = mocker.AsyncMock(spec=httpx.AsyncClient)

        async def mock_get(url, **kwargs):
            if "/repos/" in url and "/git/trees/" not in url:
                license_obj = {"spdx_id": license_spdx_id} if license_spdx_id else None
                return mock_response(
                    json_data={"license": license_obj, "default_branch": "main"}
                )
            if "/git/trees/" in url:
                return mock_response(
                    json_data={
                        "tree": [
                            {"path": "docs/intro.md", "type": "blob"},
                        ]
                    }
                )
            if "raw.githubusercontent.com" in url:
                return mock_response(text="# Intro\nHello")
            return mock_response(status_code=404)

        client.get = mocker.AsyncMock(side_effect=mock_get)
        return client

    @pytest.mark.asyncio
    async def test_no_license_blocks_fetch(self, mocker):
        client = self._make_client(mocker, None)
        result = await fetch_github_docs("https://github.com/owner/repo", client)
        assert result is None

    @pytest.mark.asyncio
    async def test_noassertion_blocks_fetch(self, mocker):
        client = self._make_client(mocker, "NOASSERTION")
        result = await fetch_github_docs("https://github.com/owner/repo", client)
        assert result is None

    @pytest.mark.asyncio
    async def test_permissive_license_allows_fetch(self, mocker):
        client = self._make_client(mocker, "MIT")
        result = await fetch_github_docs("https://github.com/owner/repo", client)
        assert result is not None
        assert len(result.files) == 1

    @pytest.mark.asyncio
    async def test_copyleft_license_allows_fetch(self, mocker):
        client = self._make_client(mocker, "GPL-3.0-only")
        result = await fetch_github_docs("https://github.com/owner/repo", client)
        assert result is not None

    @pytest.mark.asyncio
    async def test_unknown_license_blocks_fetch(self, mocker):
        client = self._make_client(mocker, "WTFPL")
        result = await fetch_github_docs("https://github.com/owner/repo", client)
        assert result is None


class TestAllowedLicenses:
    def test_common_permissive_licenses_included(self):
        for lic in ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"):
            assert lic in ALLOWED_LICENSES, f"{lic} should be allowed"

    def test_common_copyleft_licenses_included(self):
        for lic in ("GPL-3.0-only", "LGPL-3.0-only", "AGPL-3.0-only"):
            assert lic in ALLOWED_LICENSES, f"{lic} should be allowed"

    def test_public_domain_licenses_included(self):
        for lic in ("Unlicense", "CC0-1.0", "0BSD"):
            assert lic in ALLOWED_LICENSES, f"{lic} should be allowed"
