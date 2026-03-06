import re
from collections import Counter
from src.core.github_fetcher import parse_github_url
from src.utils.url_utils import extract_path

from bs4 import BeautifulSoup

# link text / aria-label hints that suggest a repo link (not a random github.com link)
_REPO_HINTS = frozenset(
    {
        "github",
        "source",
        "source code",
        "repository",
        "repo",
        "view on github",
        "edit on github",
        "star on github",
        "fork on github",
        "contribute",
        "view source",
    }
)


def discover_github_repo(html: str) -> str | None:
    """Scan an HTML page for a GitHub repository link.
    It looks through all <a> tags for hrefs pointing to github.com/{owner}/{repo}.
    Prioritizes links whose text or aria-label contains repo-related keywords
    (e.g. "GitHub", "Source", "View on GitHub").
    """
    soup = BeautifulSoup(html, "html.parser")
    links = soup.find_all("a", href=True)

    candidates: list[tuple[str, str, bool]] = []  # (owner, repo, has_hint)

    for link in links:
        href = link.get("href", "")
        if not isinstance(href, str):
            continue

        parsed = parse_github_url(href)
        if not parsed:
            continue

        owner, repo = parsed.owner, parsed.repo

        # skip urls that go deeper into github (issues, pulls, blob, etc.)
        # unless it's /tree/ (branch link) which still identifies the repo
        parsed_path = extract_path(href).strip("/").split("/")
        if len(parsed_path) > 2:
            sub = parsed_path[2]
            if sub not in ("tree", ""):
                # links to issues, pulls, blob, etc. are still valid repo indicators
                # but we deprioritize them vs direct repo links
                pass

        link_text = link.get_text(strip=True).lower()
        aria_label = str(link.get("aria-label") or "").lower()
        title_attr = str(link.get("title") or "").lower()

        has_hint = any(
            hint in text
            for hint in _REPO_HINTS
            for text in (link_text, aria_label, title_attr)
        )

        # also count github icon svgs or img tags as hints
        if link.find("svg") or link.find("img", alt=re.compile(r"github", re.I)):
            has_hint = True

        candidates.append((owner, repo, has_hint))

    if not candidates:
        return None

    repo_counts: Counter[tuple[str, str]] = Counter()
    for o, r, _h in candidates:
        repo_counts[(o.lower(), r.lower())] += 1

    # prefer hinted links
    # among hinted, prefer the most-referenced repo
    hinted = [(o, r) for o, r, h in candidates if h]
    if hinted:
        best = max(hinted, key=lambda x: repo_counts[(x[0].lower(), x[1].lower())])
        owner, repo = best
    else:
        (best_key, _count) = repo_counts.most_common(1)[0]
        for o, r, _h in candidates:
            if (o.lower(), r.lower()) == best_key:
                owner, repo = o, r
                break
        else:
            owner, repo = candidates[0][0], candidates[0][1]

    return f"https://github.com/{owner}/{repo}"
