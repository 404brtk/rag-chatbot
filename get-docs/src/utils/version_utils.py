import re

from src.utils.url_utils import extract_path

VERSION_RE = re.compile(r"^v?\d+(?:\.\d+)*(?:\.x)?$")
LATEST_KEYWORDS = frozenset({"current", "latest", "next", "stable", "main"})


def parse_version(segment: str) -> tuple[int, ...] | None:
    if segment in LATEST_KEYWORDS:
        return (9999,)
    if segment.startswith("version-"):
        segment = segment[8:]
    m = re.match(r"^v?(\d+(?:\.\d+)*)(?:\.x)?$", segment)
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def find_version_index(parts: list[str]) -> int | None:
    for i, part in enumerate(parts):
        if part in LATEST_KEYWORDS or VERSION_RE.match(part):
            return i
    return None


def dedupe_versioned_urls(urls: list[str]) -> list[str]:
    groups: dict[tuple[str, str], dict[str, list[str]]] = {}
    ungrouped: list[str] = []

    for url in urls:
        path = extract_path(url)
        parts = [p for p in path.strip("/").split("/") if p]

        version_idx = find_version_index(parts)
        if version_idx is None:
            ungrouped.append(url)
            continue

        prefix = "/".join(parts[:version_idx])
        suffix = "/".join(parts[version_idx + 1 :])
        key = (prefix, suffix)
        groups.setdefault(key, {}).setdefault(parts[version_idx], []).append(url)

    result = list(ungrouped)
    for versions in groups.values():
        if len(versions) == 1:
            for url_list in versions.values():
                result.extend(url_list)
            continue

        best_seg = None
        best_ver: tuple[int, ...] = (-1,)
        for ver_seg in versions:
            ver = parse_version(ver_seg)
            if ver is not None and ver > best_ver:
                best_ver = ver
                best_seg = ver_seg

        if best_seg is not None:
            result.extend(versions[best_seg])
        else:
            for url_list in versions.values():
                result.extend(url_list)

    return result
