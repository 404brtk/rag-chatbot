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


def _url_language(url: str, base_path: str, base_url_lang: str | None) -> str | None:
    parts = _relative_parts(url, base_path)
    lang = _has_lang_segment(parts)
    if lang:
        return lang
    if extract_path(url).startswith(base_path) and base_url_lang:
        return base_url_lang
    return None


def filter_language_urls(urls: list[str], base_url: str) -> list[str]:
    if not urls:
        return urls

    base_path = extract_path(base_url).rstrip("/") + "/"
    base_url_parts = [p for p in extract_path(base_url).strip("/").split("/") if p]
    base_url_lang = _has_lang_segment(base_url_parts)

    all_lang_codes: set[str] = set()
    for url in urls:
        lang = _url_language(url, base_path, base_url_lang)
        if lang:
            all_lang_codes.add(lang)

    if len(all_lang_codes) < 2:
        return urls

    for enf in ENGLISH_FOLDERS:
        if enf in all_lang_codes:
            return [
                u for u in urls if _url_language(u, base_path, base_url_lang) == enf
            ]

    return [u for u in urls if _url_language(u, base_path, base_url_lang) is None]
