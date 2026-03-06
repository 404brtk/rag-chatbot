from dataclasses import dataclass, field
import re
import httpx

from src.models.enums import ContentSignal
from src.utils.url_utils import extract_origin


@dataclass
class _ContentSignalRule:
    path: str  # "/" means global, "/blog/" means path-specific
    signals: dict[ContentSignal, bool] = field(default_factory=dict)


@dataclass
class _RuleGroup:
    user_agents: list[str] = field(
        default_factory=list
    )  # default_factory is used to create a new list for each instance
    # without it, all instances would share the same list, because lists are mutable objects in Python
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)
    crawl_delay: float | None = None
    content_signals: list[_ContentSignalRule] = field(default_factory=list)


class RobotsParser:
    def __init__(self, robots_txt_content: str, user_agent: str = "*"):
        self._user_agent = user_agent.lower()
        self._allow: list[str] = []
        self._disallow: list[str] = []
        self._crawl_delay: float | None = None
        self._sitemaps: list[str] = []
        self._content_signals: list[_ContentSignalRule] = []
        self._parse(robots_txt_content)

    def _parse(self, content: str) -> None:
        groups: list[_RuleGroup] = []
        current_group: _RuleGroup | None = None
        sitemaps: list[str] = []

        for raw_line in content.splitlines():
            line = raw_line.split("#", 1)[
                0
            ].strip()  # remove comments and trim whitespace
            if not line:
                continue

            match = re.match(
                r"^([A-Za-z-]+)\s*:\s*(.*)$", line
            )  # match lines like "User-agent: *" or "Disallow: /private", etc.
            if not match:
                continue

            directive = match.group(1).lower()
            value = match.group(2).strip()

            if directive == "sitemap":
                sitemaps.append(value)
                continue

            if directive == "user-agent":
                if (
                    current_group is None
                    or current_group.allow
                    or current_group.disallow
                    or current_group.content_signals
                ):
                    current_group = _RuleGroup()
                    groups.append(current_group)
                current_group.user_agents.append(value.lower())
                continue

            if current_group is None:
                continue

            if directive == "content-signal":
                rule = self._parse_content_signal(value)
                if rule:
                    current_group.content_signals.append(rule)
            elif directive == "disallow" and value:
                current_group.disallow.append(value)
            elif directive == "allow" and value:
                current_group.allow.append(value)
            elif directive == "crawl-delay":
                try:
                    current_group.crawl_delay = float(value)
                except ValueError:
                    pass

        self._sitemaps = sitemaps
        matched = self._find_matching_group(groups)
        if matched:
            self._allow = matched.allow
            self._disallow = matched.disallow
            self._crawl_delay = matched.crawl_delay
            self._content_signals = matched.content_signals

    @staticmethod
    def _parse_content_signal(value: str) -> _ContentSignalRule | None:
        """
        Parse Content-Signal value. formats:
          "ai-train=no, search=yes, ai-input=no"
          "/blog/ ai-train=no, search=yes, ai-input=no"
        """
        value = value.strip()
        if not value:
            return None

        path = "/"
        signal_part = value

        if value.startswith("/"):
            parts = value.split(None, 1)
            if len(parts) == 2:
                path = parts[0]
                signal_part = parts[1]
            else:
                # just a path with no signals
                return None

        signals: dict[ContentSignal, bool] = {}
        valid_signals = {s.value for s in ContentSignal}

        for pair in signal_part.split(","):
            pair = pair.strip()
            if "=" not in pair:
                continue
            key, val = pair.split("=", 1)
            key = key.strip().lower()
            val = val.strip().lower()

            if key in valid_signals:
                if val == "yes":
                    signals[ContentSignal(key)] = True
                elif val == "no":
                    signals[ContentSignal(key)] = False

        if not signals:
            return None

        return _ContentSignalRule(path=path, signals=signals)

    def _find_matching_group(self, groups: list[_RuleGroup]) -> _RuleGroup | None:
        specific_match: _RuleGroup | None = (
            None  # specific user-agent match (higher priority)
        )
        wildcard_match: _RuleGroup | None = (
            None  # wildcard user-agent match ("*") - default for all bots
        )

        for group in groups:
            for ua in group.user_agents:
                if ua == self._user_agent:
                    specific_match = group
                elif ua == "*":
                    wildcard_match = group

        return specific_match or wildcard_match

    def is_allowed(self, url_path: str) -> bool:
        if not self._allow and not self._disallow:
            return True

        best_match_len = 0
        best_match_allowed = True

        for rule in self._allow:
            if self._path_matches(url_path, rule) and len(rule) >= best_match_len:
                best_match_len = len(rule)
                best_match_allowed = True

        for rule in self._disallow:
            if self._path_matches(url_path, rule) and len(rule) > best_match_len:
                best_match_len = len(rule)
                best_match_allowed = False

        return best_match_allowed

    @staticmethod
    def _path_matches(path: str, rule: str) -> bool:
        if rule.endswith("$"):
            pattern = re.escape(rule[:-1]).replace(r"\*", ".*") + "$"
            return bool(re.match(pattern, path))

        pattern = re.escape(rule).replace(r"\*", ".*")
        return bool(re.match(pattern, path))

    def get_crawl_delay(self) -> float | None:
        return self._crawl_delay

    def get_sitemaps(self) -> list[str]:
        return list(self._sitemaps)

    def get_content_signal(
        self, signal: ContentSignal, url_path: str = "/"
    ) -> bool | None:
        best_match: _ContentSignalRule | None = None
        best_match_len = -1

        for rule in self._content_signals:
            if url_path.startswith(rule.path) and len(rule.path) > best_match_len:
                if signal in rule.signals:
                    best_match = rule
                    best_match_len = len(rule.path)

        if best_match is None:
            return None

        return best_match.signals.get(signal)

    def is_ai_input_allowed(self, url_path: str = "/") -> bool | None:
        return self.get_content_signal(ContentSignal.AI_INPUT, url_path)


async def fetch_robots_txt(
    base_url: str, client: httpx.AsyncClient, timeout: float = 10
) -> RobotsParser:
    url = extract_origin(base_url) + "/robots.txt"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=timeout)
        if resp.status_code == 200:
            return RobotsParser(resp.text)
    except (httpx.HTTPError, httpx.TimeoutException):
        pass
    return RobotsParser("")
