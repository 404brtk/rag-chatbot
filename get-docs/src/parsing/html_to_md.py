import io
import re

from bs4 import Tag
from markitdown import MarkItDown, StreamInfo

_markitdown = MarkItDown()
_STREAM_INFO = StreamInfo(mimetype="text/html", extension=".html", charset="utf-8")

_LANG_MARKER = "__CODE_LANG:"
_LANG_PREFIXES = ("language-", "lang-", "highlight-")


def _detect_code_language(code_tag: Tag) -> str:
    for source in (code_tag, code_tag.parent):
        if not source or not isinstance(source, Tag):
            continue
        classes = source.get("class", [])
        for cls in classes:
            cls_lower = cls.lower()
            for prefix in _LANG_PREFIXES:
                if cls_lower.startswith(prefix):
                    return cls_lower[len(prefix) :]
    return ""


def _inject_language_markers(element: Tag) -> None:
    for pre in element.find_all("pre"):
        code = pre.find("code")
        if not code:
            continue
        lang = _detect_code_language(code)
        if lang:
            existing = code.string or ""
            code.string = f"{_LANG_MARKER}{lang}__\n{existing}"


def _resolve_language_markers(md: str) -> str:
    return re.sub(
        rf"```\n{re.escape(_LANG_MARKER)}(\w+)__\n",
        r"```\1\n",
        md,
    )


def html_to_markdown(element: Tag) -> str:
    _inject_language_markers(element)
    html_bytes = str(element).encode("utf-8")
    stream = io.BytesIO(html_bytes)
    result = _markitdown.convert_stream(stream, stream_info=_STREAM_INFO)
    md = result.markdown or ""
    md = _resolve_language_markers(md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
