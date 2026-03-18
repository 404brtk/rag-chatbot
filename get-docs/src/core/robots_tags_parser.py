from bs4 import BeautifulSoup
import httpx

BLOCKING_DIRECTIVES: frozenset[str] = frozenset()


class RobotsMetaBlocked(Exception):
    pass


def parse_robots_directives(value: str, bot_name: str | None = None) -> set[str]:
    directives: dict[str | None, set[str]] = {}
    context: str | None = None

    for token in value.split(","):
        token = token.strip()
        if not token:
            continue

        if ":" in token:
            name, directive = token.split(":", 1)
            context = name.strip().lower()
            directive = directive.strip().lower()
            if directive:
                directives.setdefault(context, set()).add(directive)
        else:
            directives.setdefault(context, set()).add(token.lower())

    result = directives.get(None, set())
    if bot_name is not None:
        result = result | directives.get(bot_name.lower(), set())
    return result


def is_response_blocked(resp: httpx.Response, bot_name: str | None = None) -> bool:
    values = resp.headers.get_list("x-robots-tag")
    for value in values:
        if parse_robots_directives(value, bot_name) & BLOCKING_DIRECTIVES:
            return True
    return False


def has_nofollow_header(resp: httpx.Response, bot_name: str | None = None) -> bool:
    for value in resp.headers.get_list("x-robots-tag"):
        if "nofollow" in parse_robots_directives(value, bot_name):
            return True
    return False


def _get_meta_directives(html: str, bot_name: str | None = None) -> set[str]:
    allowed_names = {"robots"}
    if bot_name is not None:
        allowed_names.add(bot_name.lower())
    soup = BeautifulSoup(html, "html.parser")
    result: set[str] = set()
    for meta in soup.find_all("meta", attrs={"name": True, "content": True}):
        if meta["name"].lower() not in allowed_names:
            continue
        result.update(d.strip().lower() for d in meta["content"].split(","))
    return result


def is_html_blocked(html: str, bot_name: str | None = None) -> bool:
    return bool(_get_meta_directives(html, bot_name) & BLOCKING_DIRECTIVES)


def check_html_meta(html: str, bot_name: str | None = None) -> tuple[bool, bool]:
    directives = _get_meta_directives(html, bot_name)
    return bool(directives & BLOCKING_DIRECTIVES), "nofollow" in directives


def has_nofollow_meta(html: str, bot_name: str | None = None) -> bool:
    return "nofollow" in _get_meta_directives(html, bot_name)
