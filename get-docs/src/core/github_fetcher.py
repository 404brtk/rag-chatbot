import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from src.models.enums import SourceMethod
from src.models.responses import DocPage
from src.parsing.mdx_strip import strip_mdx
from src.utils.http_client import HttpClient
from src.utils.lang_utils import ENGLISH_FOLDERS, is_lang_code
from src.utils.logger import logger
from src.utils.url_utils import strip_git_suffix

# GitHub repo URL patterns:
#   https://github.com/owner/repo
#   https://github.com/owner/repo/tree/branch/path
#   github.com/owner/repo
_GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s?#]+)"
)

# /tree/<branch>/optional/path
_GITHUB_TREE_PATTERN = re.compile(
    r"(?:https?://)?github\.com/[^/\s]+/[^/\s?#]+/tree/(?P<branch>[^/\s?#]+)(?:/(?P<subpath>[^\s?#]+))?"
)

# file extensions we care about
DOC_EXTENSIONS = frozenset({".md", ".mdx", ".rst"})

# common documentation directory names, in priority order for folder detection
DOC_FOLDERS_PRIORITY = ("docs", "doc", "documentation", "guide", "guides", "content")
DOC_FOLDERS = frozenset(DOC_FOLDERS_PRIORITY)

# github paths that are NOT repos (e.g. github.com/features, github.com/pricing)
GITHUB_NON_REPO_PATHS = frozenset(
    {
        "features",
        "security",
        "pricing",
        "enterprise",
        "team",
        "customer-stories",
        "readme",
        "explore",
        "topics",
        "trending",
        "collections",
        "events",
        "sponsors",
        "settings",
        "login",
        "join",
        "about",
        "contact",
        "site",
        "orgs",
    }
)

# root-level files to always skip (lowercase comparison)
SKIP_FILES = frozenset(
    {
        "changelog.md",
        "changes.md",
        "contributing.md",
        "contributors.md",
        "code_of_conduct.md",
        "license.md",
        "licence.md",
        "license.rst",
        "licence.rst",
        "security.md",
        "pull_request_template.md",
        "issue_template.md",
    }
)

# directories to always skip
SKIP_DIRS = frozenset(
    {
        ".github",
        ".git",
        ".vscode",
        ".idea",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "venv",
        ".venv",
        "test",
        "tests",
        "benchmarks",
        "bench",
        "examples",
        "example",
    }
)

_API_BASE = "https://api.github.com"


# SPDX license ids we consider safe to fetch docs from
# it includes permissive and copyleft oss licenses
# repos with no license or unrecognized licenses are skipped.
ALLOWED_LICENSES = frozenset(
    {
        # Permissive
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "Unlicense",
        "Zlib",
        "PostgreSQL",
        "0BSD",
        "BlueOak-1.0.0",
        "BSL-1.0",
        # Weak Copyleft
        "MPL-2.0",
        "EPL-2.0",
        "LGPL-2.1-only",
        "LGPL-2.1-or-later",
        "LGPL-3.0-only",
        "LGPL-3.0-or-later",
        # Strong Copyleft
        "GPL-2.0-only",
        "GPL-2.0-or-later",
        "GPL-3.0-only",
        "GPL-3.0-or-later",
        "AGPL-3.0-only",
        "AGPL-3.0-or-later",
        # Creative Commons / Documentation
        "CC0-1.0",
        "CC-BY-3.0",
        "CC-BY-4.0",
        "CC-BY-SA-4.0",
        "Artistic-2.0",
    }
)


@dataclass
class ParsedGitHubURL:
    owner: str
    repo: str
    branch: str | None = None
    subpath: str | None = None


@dataclass
class GitHubFetchResult:
    owner: str
    repo: str
    branch: str | None = None
    doc_folder: str | None = None
    license_spdx_id: str | None = None
    pages: list[DocPage] = field(default_factory=list)
    rate_limited: bool = False


def parse_github_url(url: str) -> ParsedGitHubURL | None:
    """Extract owner, repo, and optional branch/subpath from a GitHub URL."""
    match = _GITHUB_REPO_PATTERN.search(url)
    if not match:
        return None

    owner = match.group("owner")
    repo = strip_git_suffix(match.group("repo"))

    if owner.lower() in GITHUB_NON_REPO_PATHS:
        return None

    tree_match = _GITHUB_TREE_PATTERN.search(url)
    branch = tree_match.group("branch") if tree_match else None
    subpath = tree_match.group("subpath") if tree_match else None
    if subpath:
        subpath = subpath.rstrip("/")

    return ParsedGitHubURL(owner=owner, repo=repo, branch=branch, subpath=subpath)


def _find_doc_folder(tree_paths: list[str], root_only: bool = False) -> str | None:
    """Find the primary documentation folder from the repo tree.

    When root_only is True only top-level directories are considered.
    When False it searches at all depths, preferring
    shallower folders and DOC_FOLDERS_PRIORITY
    """
    if root_only:
        top_level_dirs: set[str] = set()
        for path in tree_paths:
            parts = path.split("/")
            if len(parts) > 1:
                top_level_dirs.add(parts[0])

        for candidate in DOC_FOLDERS_PRIORITY:
            if candidate in top_level_dirs:
                return candidate
            for d in top_level_dirs:
                if d.lower() == candidate:
                    return d
        return None

    doc_dirs: set[str] = set()
    for path in tree_paths:
        parts = path.split("/")
        for i, part in enumerate(parts[:-1]):
            if part.lower() in DOC_FOLDERS:
                doc_dirs.add("/".join(parts[: i + 1]))

    if not doc_dirs:
        return None

    def _sort_key(d: str) -> tuple[int, int, str]:
        depth = d.count("/")
        name = d.split("/")[-1].lower()
        try:
            priority = DOC_FOLDERS_PRIORITY.index(name)
        except ValueError:
            priority = len(DOC_FOLDERS_PRIORITY)
        return (depth, priority, d.lower())

    top_level = [d for d in doc_dirs if d.count("/") == 0]
    candidates = top_level if top_level else list(doc_dirs)

    return min(candidates, key=_sort_key)


def _narrow_to_english(
    tree_paths: list[str], doc_folder: str | None
) -> tuple[str | None, set[str]]:
    """Narrow a doc folder to its English content."""
    if doc_folder is None:
        return None, set()

    prefix = doc_folder.lower() + "/"
    child_dirs: set[str] = set()
    for p in tree_paths:
        low = p.lower()
        if not low.startswith(prefix):
            continue
        remainder = low[len(prefix) :]
        slash_idx = remainder.find("/")
        if slash_idx > 0:
            child_dirs.add(remainder[:slash_idx])

    for lang in ENGLISH_FOLDERS:
        if lang in child_dirs:
            return f"{doc_folder}/{lang}", set()

    # no english subfolder. if there are multiple language-code dirs,
    # eng lives at the doc root - exclude the language subdirs.
    lang_dirs = {d for d in child_dirs if is_lang_code(d)}
    if len(lang_dirs) >= 2:
        exclude = {f"{doc_folder}/{d}" for d in lang_dirs}
        return doc_folder, exclude

    return doc_folder, set()


def _is_doc_file(path: str, doc_folder: str | None) -> bool:
    """Decide whether a tree entry is a documentation file we want to fetch."""
    parts = path.lower().split("/")
    filename = parts[-1]

    if not any(filename.endswith(ext) for ext in DOC_EXTENSIONS):
        return False

    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return False

    if doc_folder:
        return path.lower().startswith(doc_folder.lower() + "/")

    if len(parts) == 1:
        return filename not in SKIP_FILES

    if parts[0] in DOC_FOLDERS:
        return True

    return False


def _github_headers(token: str | None) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class _RateLimitExhausted(Exception):
    """Raised when GitHub API rate limit is hit"""


@dataclass
class _RepoMeta:
    spdx_id: str | None
    default_branch: str | None


async def _fetch_repo_meta(
    client: HttpClient,
    owner: str,
    repo: str,
    timeout: float,
    token: str | None = None,
) -> _RepoMeta:
    url = f"{_API_BASE}/repos/{owner}/{repo}"
    try:
        resp = await client.get(
            url,
            headers=_github_headers(token),
            follow_redirects=True,
            timeout=timeout,
        )
        if resp.status_code != 200:
            return _RepoMeta(spdx_id=None, default_branch=None)
        data = resp.json()
        license_obj = data.get("license")
        spdx_id = license_obj.get("spdx_id") if license_obj else None
        default_branch = data.get("default_branch")
        return _RepoMeta(spdx_id=spdx_id, default_branch=default_branch)
    except httpx.HTTPError:
        return _RepoMeta(spdx_id=None, default_branch=None)


async def _fetch_tree(
    client: HttpClient,
    owner: str,
    repo: str,
    branch: str,
    timeout: float,
    token: str | None = None,
) -> list[dict] | None:
    """Fetch the recursive tree for a given branch."""
    url = f"{_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"

    resp = await client.get(
        url,
        headers=_github_headers(token),
        follow_redirects=True,
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    return data.get("tree", [])


async def _fetch_file_content(
    client: HttpClient,
    owner: str,
    repo: str,
    branch: str,
    path: str,
    timeout: float,
    token: str | None = None,
) -> str | None:
    url = f"{_API_BASE}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    headers = _github_headers(token)
    headers["Accept"] = "application/vnd.github.raw+json"

    resp = await client.get(
        url,
        headers=headers,
        follow_redirects=True,
        timeout=timeout,
        max_retries=0,
    )

    if resp.status_code == 429:
        raise _RateLimitExhausted()

    if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
        raise _RateLimitExhausted()

    if resp.status_code != 200:
        return None
    return resp.text


async def fetch_github_docs(
    repo_url: str,
    client: HttpClient,
    timeout: float = 15,
    max_files: int = 300,
    doc_folder_override: str | None = None,
    root_only: bool = False,
    github_token: str | None = None,
    on_progress: Callable[[int, int | None], Awaitable[None]] | None = None,
) -> GitHubFetchResult | None:
    """Fetch documentation files from a GitHub repository.

    1. Parses owner/repo from the URL.
    2. Fetches the full file tree via GitHub API.
    3. Identifies the docs folder and filters for doc files.
    4. Fetches each doc file via the GitHub API.
    """
    parsed = parse_github_url(repo_url)
    if not parsed:
        return None

    owner, repo = parsed.owner, parsed.repo

    if not github_token:
        capped = min(max_files, 50)
        if max_files > 50:
            logger.warning(
                f"No GitHub token - capping file fetch to {capped} (from {max_files}). "
                "Set GETDOCS_GITHUB_TOKEN to increase this limit."
            )
        max_files = capped

    # check license before fetching any content
    meta = await _fetch_repo_meta(client, owner, repo, timeout, token=github_token)
    if (
        not meta.spdx_id
        or meta.spdx_id == "NOASSERTION"
        or meta.spdx_id not in ALLOWED_LICENSES
    ):
        logger.info(
            f"Skipping {owner}/{repo}: license {meta.spdx_id!r} not in allowed set"
        )
        return GitHubFetchResult(
            owner=owner,
            repo=repo,
            license_spdx_id=meta.spdx_id,
        )

    resolved_branch = parsed.branch or meta.default_branch
    if not resolved_branch:
        return None

    try:
        tree_entries = await _fetch_tree(
            client, owner, repo, resolved_branch, timeout, token=github_token
        )
    except httpx.HTTPError:
        return None

    if tree_entries is None:
        return None

    all_paths = [entry["path"] for entry in tree_entries if entry.get("type") == "blob"]

    if doc_folder_override:
        doc_folder = doc_folder_override
    else:
        doc_folder = _find_doc_folder(all_paths, root_only=root_only)

    if doc_folder is None and root_only:
        return None

    doc_folder, lang_excludes = _narrow_to_english(all_paths, doc_folder)

    doc_paths = [p for p in all_paths if _is_doc_file(p, doc_folder)]
    if lang_excludes:
        doc_paths = [
            p
            for p in doc_paths
            if not any(p.lower().startswith(ex.lower() + "/") for ex in lang_excludes)
        ]

    if not doc_paths:
        return GitHubFetchResult(
            owner=owner,
            repo=repo,
            branch=resolved_branch,
            doc_folder=doc_folder,
            license_spdx_id=meta.spdx_id,
        )

    doc_paths = doc_paths[:max_files]

    result = GitHubFetchResult(
        owner=owner,
        repo=repo,
        branch=resolved_branch,
        doc_folder=doc_folder,
        license_spdx_id=meta.spdx_id,
    )

    # abort remaining fetches early when the rate limit is hit.
    # the flag is checked before each sequential fetch via the closure.
    rate_limit_hit = False

    async def _fetch_one(path: str) -> str | None:
        nonlocal rate_limit_hit
        if rate_limit_hit:
            return None
        try:
            return await _fetch_file_content(
                client, owner, repo, resolved_branch, path, timeout, token=github_token
            )
        except _RateLimitExhausted:
            rate_limit_hit = True
            return None

    outcomes = await client.fetch_many(
        doc_paths,
        _fetch_one,
        on_progress=on_progress,
    )

    if rate_limit_hit:
        result.rate_limited = True
        logger.warning("GitHub rate limit hit - returning partial results")

    for path, content in outcomes:
        if not isinstance(content, str):
            continue
        page_url = f"https://github.com/{owner}/{repo}/blob/{resolved_branch}/{path}"
        # TODO: add rst-to-markdown conversion for .rst files
        page_content = strip_mdx(content) if path.endswith(".mdx") else content
        result.pages.append(
            DocPage(
                url=page_url,
                title=path,
                content=page_content,
                source_method=SourceMethod.GITHUB,
            )
        )

    return result
