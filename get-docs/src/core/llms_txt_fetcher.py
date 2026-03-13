import re
from dataclasses import dataclass, field
import httpx

from src.core.robots_parser import RobotsParser, fetch_robots_txt
from src.models.responses import EthicsContext
from src.utils.http_client import HttpClient
from src.utils.logger import logger
from src.utils.url_utils import (
    extract_path,
    is_absolute_url,
    resolve_relative,
    url_path_parents,
)


@dataclass
class LlmsTxtLink:
    title: str
    url: str
    description: str | None = None
    section: str | None = None
    optional: bool = False


@dataclass
class LlmsTxtResult:
    source_url: str
    raw_content: str
    title: str | None = None
    summary: str | None = None
    links: list[LlmsTxtLink] = field(default_factory=list)
    is_full: bool = False


# regex for markdown link lines: "- [title](url)" with optional ": description"
_LINK_PATTERN = re.compile(
    r"^-\s*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)"
    r"(?:\s*:\s*(?P<desc>.+))?$"
)


def parse_llms_txt(
    content: str, source_url: str = "", is_full: bool = False
) -> LlmsTxtResult:
    """
    Handles the format:
        # Title
        > Summary blockquote
        Optional body text
        ## Section Name
        - [Link](url): description
        ## Optional
        - [Link](url): skippable
    """
    result = LlmsTxtResult(
        source_url=source_url,
        raw_content=content,
        is_full=is_full,
    )

    lines = content.splitlines()
    current_section: str | None = None
    in_optional = False
    summary_lines: list[str] = []
    reading_summary = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("# ") and not stripped.startswith("## "):
            if result.title is None:
                result.title = stripped[2:].strip()
                reading_summary = True
            continue

        if reading_summary and stripped.startswith(">"):
            summary_lines.append(stripped.lstrip("> ").strip())
            continue

        if reading_summary and summary_lines and not stripped.startswith(">"):
            reading_summary = False

        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            in_optional = current_section.lower() == "optional"
            continue

        match = _LINK_PATTERN.match(stripped)
        if match:
            url = match.group("url")
            if source_url and not is_absolute_url(url):
                url = resolve_relative(source_url, url)

            result.links.append(
                LlmsTxtLink(
                    title=match.group("title"),
                    url=url,
                    description=match.group("desc"),
                    section=current_section,
                    optional=in_optional,
                )
            )

    if summary_lines:
        result.summary = " ".join(summary_lines)

    return result


# paths to probe, in priority order (best first)
_LLMS_TXT_PATHS = (
    ("llms-full.txt", True),  # full md docs content all in one
    ("llms.txt", False),  # only links with description
)


async def fetch_llms_txt(
    base_url: str,
    client: HttpClient,
    robots: RobotsParser | None = None,
    timeout: float = 15,
    ethics: EthicsContext | None = None,
) -> LlmsTxtResult | None:
    if robots is None:
        robots = await fetch_robots_txt(base_url, client, timeout)

    for parent in url_path_parents(base_url):
        for filename, is_full in _LLMS_TXT_PATHS:
            url = parent.rstrip("/") + "/" + filename

            url_path = extract_path(url)
            if not robots.is_allowed(url_path):
                logger.debug(f"robots.txt blocks {url}")
                if ethics is not None:
                    ethics.pages_filtered_by_robots += 1
                continue
            if robots.is_ai_input_allowed(url_path) is False:
                logger.debug(f"AI-input signal blocks {url}")
                if ethics is not None:
                    ethics.pages_filtered_by_robots += 1
                continue

            try:
                resp = await client.get(url, follow_redirects=True, timeout=timeout)
                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("content-type", "")

                if "text/html" in content_type:
                    continue

                text = resp.text.strip()
                if not text:
                    continue

                return parse_llms_txt(text, source_url=url, is_full=is_full)

            except httpx.HTTPError:
                continue

    return None
