import asyncio
import logging
import re
from dataclasses import dataclass, field

import httpx

from src.utils.url_utils import strip_git_suffix

logger = logging.getLogger("get-docs")

# GitHub repo URL patterns:
#   https://github.com/owner/repo
#   https://github.com/owner/repo/tree/branch/path
#   github.com/owner/repo
_GITHUB_REPO_PATTERN = re.compile(
    r"(?:https?://)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s?#]+)"
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

# default branches to try, in order
DEFAULT_BRANCHES = ("main", "master")

_API_BASE = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"


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

# English subfolder names to look for, in priority order
_ENGLISH_FOLDERS = ("en", "en-us", "en-gb")


@dataclass
class GitHubFile:
    path: str
    content: str


@dataclass
class GitHubFetchResult:
    owner: str
    repo: str
    branch: str
    doc_folder: str | None
    files: list[GitHubFile] = field(default_factory=list)


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL."""
    match = _GITHUB_REPO_PATTERN.search(url)
    if not match:
        return None

    owner = match.group("owner")
    repo = strip_git_suffix(match.group("repo"))

    if owner.lower() in GITHUB_NON_REPO_PATHS:
        return None

    return (owner, repo)


def _find_doc_folder(tree_paths: list[str]) -> str | None:
    """Find the primary documentation folder from the repo tree."""
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


def _narrow_to_english(tree_paths: list[str], doc_folder: str | None) -> str | None:
    """Narrow a doc folder to its English subfolder if one exists."""
    if doc_folder is None:
        return None

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

    for lang in _ENGLISH_FOLDERS:
        if lang in child_dirs:
            return f"{doc_folder}/{lang}"

    return doc_folder


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


async def _fetch_repo_license(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    timeout: float,
) -> str | None:
    url = f"{_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = await client.get(
            url, headers=headers, follow_redirects=True, timeout=timeout
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        license_obj = data.get("license")
        if not license_obj:
            return None
        return license_obj.get("spdx_id")
    except (httpx.HTTPError, httpx.TimeoutException):
        return None


async def _fetch_tree(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    branch: str,
    timeout: float,
) -> list[dict] | None:
    """Fetch the recursive tree for a given branch."""
    url = f"{_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"Accept": "application/vnd.github+json"}

    resp = await client.get(
        url, headers=headers, follow_redirects=True, timeout=timeout
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    return data.get("tree", [])


async def _fetch_raw_file(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    branch: str,
    path: str,
    timeout: float,
) -> str | None:
    """Fetch a single file's raw content from raw.githubusercontent.com."""
    url = f"{_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
    resp = await client.get(url, follow_redirects=True, timeout=timeout)
    if resp.status_code != 200:
        return None
    return resp.text


async def fetch_github_docs(
    repo_url: str,
    client: httpx.AsyncClient,
    branch: str | None = None,
    timeout: float = 15,
    max_files: int = 500,
) -> GitHubFetchResult | None:
    """Fetch documentation files from a GitHub repository.

    1. Parses owner/repo from the URL.
    2. Fetches the full file tree via GitHub API.
    3. Identifies the docs folder and filters for doc files.
    4. Fetches each doc file from raw.githubusercontent.com.
    """
    parsed = parse_github_url(repo_url)
    if not parsed:
        return None

    owner, repo = parsed

    # check license before fetching any content
    spdx_id = await _fetch_repo_license(client, owner, repo, timeout)
    if not spdx_id or spdx_id == "NOASSERTION" or spdx_id not in ALLOWED_LICENSES:
        logger.info(f"Skipping {owner}/{repo}: license {spdx_id!r} not in allowed set")
        return None

    branches_to_try = [branch] if branch else list(DEFAULT_BRANCHES)
    tree_entries: list[dict] | None = None
    resolved_branch: str | None = None

    for b in branches_to_try:
        try:
            tree_entries = await _fetch_tree(client, owner, repo, b, timeout)
            if tree_entries is not None:
                resolved_branch = b
                break
        except (httpx.HTTPError, httpx.TimeoutException):
            continue

    if tree_entries is None or resolved_branch is None:
        return None

    all_paths = [entry["path"] for entry in tree_entries if entry.get("type") == "blob"]

    doc_folder = _find_doc_folder(all_paths)
    doc_folder = _narrow_to_english(all_paths, doc_folder)

    doc_paths = [p for p in all_paths if _is_doc_file(p, doc_folder)]

    if not doc_paths:
        return GitHubFetchResult(
            owner=owner,
            repo=repo,
            branch=resolved_branch,
            doc_folder=doc_folder,
        )

    doc_paths = doc_paths[:max_files]

    result = GitHubFetchResult(
        owner=owner,
        repo=repo,
        branch=resolved_branch,
        doc_folder=doc_folder,
    )

    # batch fetch to avoid overwhelming the server
    batch_size = 20
    for i in range(0, len(doc_paths), batch_size):
        batch = doc_paths[i : i + batch_size]
        tasks = [
            _fetch_raw_file(client, owner, repo, resolved_branch, path, timeout)
            for path in batch
        ]
        # gather concurrently
        contents = await asyncio.gather(*tasks, return_exceptions=True)

        for path, content in zip(batch, contents):
            if isinstance(content, str):
                result.files.append(GitHubFile(path=path, content=content))

    return result
