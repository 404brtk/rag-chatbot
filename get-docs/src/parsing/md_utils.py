import re

_YAML_FM_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)
_TOML_FM_RE = re.compile(r"^\+\+\+\s*\n(.+?)\n\+\+\+\s*\n", re.DOTALL)
_YAML_TITLE_RE = re.compile(r"^title:\s*(.+)$", re.MULTILINE)
_TOML_TITLE_RE = re.compile(r"^title\s*=\s*(.+)$", re.MULTILINE)

_FM_PATTERNS = (
    (_YAML_FM_RE, _YAML_TITLE_RE),
    (_TOML_FM_RE, _TOML_TITLE_RE),
)


def extract_md_title(md: str) -> str:
    for fm_re, title_re in _FM_PATTERNS:
        fm = fm_re.match(md)
        if fm:
            title_match = title_re.search(fm.group(1))
            if title_match:
                return title_match.group(1).strip().strip("\"'")
            break

    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def strip_frontmatter(md: str) -> str:
    for fm_re, _ in _FM_PATTERNS:
        if fm_re.match(md):
            return fm_re.sub("", md, count=1)
    return md
