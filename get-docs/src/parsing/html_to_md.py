import re

from bs4 import Tag
from markdownify import MarkdownConverter

from src.parsing.mdx_strip import strip_mdx

_LANG_PREFIXES = ("language-", "lang-", "highlight-")


def _detect_code_language(el: Tag) -> str | None:
    sources = [el]
    if el.name == "pre":
        code = el.find("code")
        if code and isinstance(code, Tag):
            sources.insert(0, code)
    elif el.name == "code" and el.parent and isinstance(el.parent, Tag):
        sources.append(el.parent)

    for source in sources:
        classes = source.get("class") or []
        for cls in classes:
            cls_lower = cls.lower()
            for prefix in _LANG_PREFIXES:
                if cls_lower.startswith(prefix):
                    return cls_lower[len(prefix) :]
    return None


class _DocsMarkdownConverter(MarkdownConverter):
    def convert_pre(self, el: Tag, text: str, parent_tags: set) -> str:
        result = super().convert_pre(el, text, parent_tags)
        result = re.sub(r"```(\w*)\n\n", r"```\1\n", result)
        result = re.sub(r"\n\n```", "\n```", result)
        return result


_converter = _DocsMarkdownConverter(
    heading_style="ATX",
    code_language_callback=_detect_code_language,
)


def html_to_markdown(element: Tag) -> str:
    md = _converter.convert_soup(element)
    md = strip_mdx(md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()
