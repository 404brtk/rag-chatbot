import re

# matches import/export lines (not inside code blocks)
_IMPORT_EXPORT_RE = re.compile(r"^(import|export)\s+", re.MULTILINE)

# matches opening JSX tags: <Component> or <Component prop="val">
_OPENING_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9.]*)\b[^>]*>\s*\n?")

# matches self-closing JSX tags: <Component /> or <Component prop="val" />
_SELF_CLOSING_TAG_RE = re.compile(r"<[A-Z][A-Za-z0-9.]*\b[^>]*/>\s*\n?")

# matches closing JSX tags: </Component>
_CLOSING_TAG_RE = re.compile(r"</[A-Z][A-Za-z0-9.]*>\s*\n?")

# matches JSX comments: {/* ... */} (single-line)
_JSX_COMMENT_INLINE_RE = re.compile(r"\{/\*.*?\*/\}")

# matches JSX comments spanning multiple lines: {/* ... \n ... */}
_JSX_COMMENT_MULTI_RE = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)


def strip_mdx(content: str) -> str:
    lines = content.split("\n")
    result: list[str] = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        if _IMPORT_EXPORT_RE.match(stripped):
            continue

        line = _JSX_COMMENT_INLINE_RE.sub("", line)
        line = _SELF_CLOSING_TAG_RE.sub("", line)
        line = _OPENING_TAG_RE.sub("", line)
        line = _CLOSING_TAG_RE.sub("", line)

        result.append(line)

    text = "\n".join(result)

    parts = re.split(r"(```.*?```)", text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        if i % 2 == 0:  # outside code blocks
            parts[i] = _JSX_COMMENT_MULTI_RE.sub("", part)
    text = "".join(parts)
    # collapse excessive blank lines left by removed tags/comments
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
