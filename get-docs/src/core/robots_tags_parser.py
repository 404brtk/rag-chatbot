from bs4 import BeautifulSoup
import httpx

BLOCKING_DIRECTIVES = frozenset({"noindex", "none", "noarchive", "nosnippet"})


class RobotsMetaBlocked(Exception):
    pass


def parse_robots_directives(value: str, bot_name: str = "*") -> set[str]:
    bot_name = bot_name.lower()
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
    if bot_name != "*":
        result = result | directives.get(bot_name, set())
    return result


def is_response_blocked(resp: httpx.Response, bot_name: str = "*") -> bool:
    values = resp.headers.get_list("x-robots-tag")
    for value in values:
        if parse_robots_directives(value, bot_name) & BLOCKING_DIRECTIVES:
            return True
    return False


def is_html_blocked(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.find_all("meta", attrs={"name": True, "content": True}):
        if meta["name"].lower() != "robots":
            continue
        directives = {d.strip().lower() for d in meta["content"].split(",")}
        if directives & BLOCKING_DIRECTIVES:
            return True
    return False
