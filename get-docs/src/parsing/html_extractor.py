import html
import re

from bs4 import BeautifulSoup, NavigableString, Tag

# tags that are unlikely to contain documentation content
NOISE_TAGS = {
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    "button",
}

# substrings to skip during parsing
NOISE_CLASSES_IDS = {
    "sidebar",
    "navigation",
    "breadcrumb",
    "breadcrumbs",
    "toc",
    "table-of-contents",
    "tableofcontents",
    "edit-on-github",
    "edit-page",
    "pagination",
    "prev-next",
    "page-nav",
    "footer",
    "header",
    "nav",
    "menu",
    "search",
    "ads",
    "banner",
    "cookie",
    "linenos",
    "linenodiv",
    "clipboard",
    "copy",
}

# selectors for extracting primary text; the first valid match is used
CONTENT_SELECTORS = [
    "article",
    "[role='main']",
    "main",
    ".docs-content",
    ".documentation",
    ".doc-content",
    ".markdown-body",
    ".md-content",
    ".rst-content",
    ".content",
    ".post-content",
    ".entry-content",
    ".page-content",
]

_STYLING_TAG_RE = re.compile(
    r"</?(?:font|span|b|i|u|em|strong|mark|small|s|del|ins)(?:\s[^>]*)?>",
    re.IGNORECASE,
)


def _find_largest_text_block(soup: BeautifulSoup) -> Tag | None:
    """fallback to the div with the max character count"""
    best: Tag | None = None
    best_length = 0

    for div in soup.find_all("div"):
        text_length = len(div.get_text(strip=True))
        if text_length > best_length:
            best_length = text_length
            best = div

    return best


def _auto_detect_content(soup: BeautifulSoup) -> Tag | None:
    for selector in CONTENT_SELECTORS:
        result = soup.select_one(selector)
        if result:
            return result

    return _find_largest_text_block(soup)


def _strip_noise(container: Tag) -> None:
    """remove non-functional elements, hidden styles and noise patterns"""
    for tag_name in NOISE_TAGS:
        for element in container.find_all(tag_name):
            element.decompose()

    # collect before decomposing to avoid modifying tree during iteration
    to_remove = []
    for element in container.find_all(True):
        classes = element.get("class", [])
        el_id = element.get("id", "")

        class_str = " ".join(classes).lower() if classes else ""
        id_str = el_id.lower() if el_id else ""

        for noise in NOISE_CLASSES_IDS:
            if noise in class_str or noise in id_str:
                to_remove.append(element)
                break

    for el in to_remove:
        el.decompose()

    to_remove = []
    for element in container.find_all(True):
        style = element.get("style", "")
        if "display:none" in style.replace(
            " ", ""
        ) or "visibility:hidden" in style.replace(" ", ""):
            to_remove.append(element)

    for el in to_remove:
        el.decompose()

    _clean_code_blocks(container)


def _clean_code_blocks(container: Tag) -> None:
    """extract clean, plain-text code from <pre> blocks."""
    for pre in container.find_all("pre"):
        code = pre.find("code")
        code_classes = code.get("class", []) if code else []

        raw = pre.decode_contents()
        # strip styling/highlighting tags and <code> wrappers, keep text
        cleaned = _STYLING_TAG_RE.sub("", raw)
        cleaned = re.sub(r"</?code[^>]*>", "", cleaned, flags=re.IGNORECASE)
        # unescape twice because sometimes the text is double-wrapped in html codes
        cleaned = html.unescape(cleaned)
        cleaned = _STYLING_TAG_RE.sub("", cleaned)
        cleaned = html.unescape(cleaned)

        # rebuild the block but keep the language class
        pre.clear()
        new_code = Tag(name="code")
        if code_classes:
            new_code["class"] = code_classes
        new_code.append(NavigableString(cleaned))
        pre.append(new_code)


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1:
        # remove headerlink anchors before extracting text
        for a in h1.find_all("a", class_="headerlink"):
            a.decompose()
        return h1.get_text(separator=" ", strip=True)

    title = soup.find("title")
    if title:
        return title.get_text(strip=True)

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    return ""


def extract_content(html: str, css_selector: str | None = None) -> Tag | None:
    soup = BeautifulSoup(html, "html.parser")

    if css_selector:
        container = soup.select_one(css_selector)
    else:
        container = _auto_detect_content(soup)

    if container is None:
        return None

    _strip_noise(container)
    return container
