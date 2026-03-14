import re

from src.utils.url_utils import extract_path

LANG_CODE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2,3})?$")
ENGLISH_FOLDERS = ("en", "en-us", "en-gb")


def is_lang_code(segment: str) -> bool:
    return bool(LANG_CODE_RE.match(segment))


def _has_lang_segment(parts: list[str]) -> str | None:
    for p in parts:
        if is_lang_code(p):
            return p
    return None


def _relative_parts(url: str, base_path: str) -> list[str]:
    path = extract_path(url)
    if path.startswith(base_path):
        path = path[len(base_path) :]
    return [p for p in path.strip("/").split("/") if p]


def filter_language_urls(urls: list[str], base_url: str) -> list[str]:
    if not urls:
        return urls

    base_path = extract_path(base_url).rstrip("/") + "/"

    all_lang_codes: set[str] = set()
    for url in urls:
        parts = _relative_parts(url, base_path)
        lang = _has_lang_segment(parts)
        if lang:
            all_lang_codes.add(lang)

    if len(all_lang_codes) < 2:
        return urls

    for enf in ENGLISH_FOLDERS:
        if enf in all_lang_codes:
            return [u for u in urls if enf in _relative_parts(u, base_path)]

    return [u for u in urls if _has_lang_segment(_relative_parts(u, base_path)) is None]
