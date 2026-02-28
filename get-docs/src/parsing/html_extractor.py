import html
import re

from bs4 import BeautifulSoup, NavigableString, Tag

from src.utils.url_utils import (
    is_absolute_url,
    is_asset_url,
    is_same_domain,
    normalize_url,
    resolve_relative,
)

# tags that are unlikely to contain documentation content
NOISE_TAGS = frozenset(
    {
        "nav",
        "header",
        "footer",
        "aside",
        "script",
        "style",
        "noscript",
        "button",
    }
)

# substrings to skip during parsing
NOISE_CLASSES_IDS = frozenset(
    {
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
)

# selectors for extracting primary text; the first valid match is used (order matters)
CONTENT_SELECTORS = (
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
)

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


def _build_labeled_fragments(
    labels: list[str],
    panels: list[Tag],
) -> list[Tag]:
    """Pair each tab label with its panel content and return them as flat elements."""
    fragments: list[Tag] = []

    for i, panel in enumerate(panels):
        label_text = labels[i] if i < len(labels) else f"Tab {i + 1}"

        p = Tag(name="p")
        strong = Tag(name="strong")
        strong.string = label_text
        p.append(strong)
        fragments.append(p)

        for child in list(panel.children):
            if isinstance(child, Tag):
                child.extract()
                fragments.append(child)
            elif isinstance(child, NavigableString) and child.strip():
                wrapper = Tag(name="p")
                wrapper.string = child.strip()
                fragments.append(wrapper)

    return fragments


def _replace_with_labeled_panels(
    target: Tag,
    labels: list[str],
    panels: list[Tag],
) -> None:
    """Swap a tab container for its flattened labeled contents."""
    fragments = _build_labeled_fragments(labels, panels)

    for frag in fragments:
        target.insert_before(frag)
    target.decompose()


def _flatten_tabbed_content(container: Tag) -> None:
    """Unpack tabbed UI into plain labeled sections so nothing is lost.

    Doc sites commonly hide code examples behind tabs (e.g. Python vs JS).
    The content is all in the DOM, just toggled by CSS — we flatten it out.
    """

    # Material for MkDocs
    for tabset in container.select("div.tabbed-set"):
        labels = [
            label.get_text(strip=True)
            for label in tabset.select(".tabbed-labels > label")
        ]
        panels = tabset.select(".tabbed-content > .tabbed-block")
        _replace_with_labeled_panels(tabset, labels, panels)

    # Sphinx Tabs
    for tabset in container.select("div.sphinx-tabs"):
        labels = [tab.get_text(strip=True) for tab in tabset.select(".sphinx-tabs-tab")]
        panels = tabset.select(".sphinx-tabs-panel")
        _replace_with_labeled_panels(tabset, labels, panels)

    # Bootstrap
    for nav in container.select("ul.nav-tabs"):
        tab_content = nav.find_next_sibling(class_="tab-content")
        if not tab_content:
            continue
        labels = [a.get_text(strip=True) for a in nav.select("a")]
        panels = tab_content.select(".tab-pane")
        _replace_with_labeled_panels(tab_content, labels, panels)
        nav.decompose()

    # ARIA tabs
    for tablist in container.select("[role='tablist']"):
        labels = [tab.get_text(strip=True) for tab in tablist.select("[role='tab']")]
        parent = tablist.parent
        if not parent:
            continue
        panels = parent.select("[role='tabpanel']")
        if not panels:
            continue
        fragments = _build_labeled_fragments(labels, panels)
        for frag in fragments:
            tablist.insert_before(frag)
        for panel in panels:
            panel.decompose()
        tablist.decompose()


def _flatten_definition_lists(container: Tag) -> None:
    """Flatten <dl> tags into regular paragraph and block siblings.

    This prevents Markitdown from misinterpreting nested code blocks.
    """
    for dl in container.find_all("dl"):
        for child in list(dl.children):
            if isinstance(child, Tag) and child.name == "dt":
                # convert term to a bold paragraph to preserve styling
                p = Tag(name="p")
                strong = Tag(name="strong")
                strong.string = child.get_text()
                p.append(strong)
                dl.insert_before(p)
            elif isinstance(child, Tag) and child.name == "dd":
                # promote contents to siblings to avoid indentation issues
                for dd_child in list(child.children):
                    dl.insert_before(dd_child)
        dl.decompose()


def _strip_noise(container: Tag) -> None:
    """remove non-functional elements, hidden styles and noise patterns"""

    # flatten tabs first while the DOM structure is still intact
    _flatten_tabbed_content(container)

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

    _flatten_definition_lists(container)
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


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue

        url = resolve_relative(base_url, href)

        if not is_absolute_url(url):
            continue
        if is_asset_url(url):
            continue
        if not is_same_domain(url, base_url):
            continue

        normalized = normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)

    return result


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
