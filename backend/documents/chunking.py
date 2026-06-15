import logging
import re
import tomllib
from dataclasses import dataclass

import pymupdf
import pymupdf4llm
import yaml

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "application/pdf",
    }
)


@dataclass(frozen=True, slots=True)
class Block:
    kind: str  # "h1".."h6", "code", "table", "list", "paragraph"
    content: str


def extract_pdf_to_markdown(file_source: str | bytes) -> str:
    if isinstance(file_source, bytes):
        doc = pymupdf.open(stream=file_source, filetype="pdf")
    else:
        doc = pymupdf.open(file_source)
    try:
        return pymupdf4llm.to_markdown(doc, show_progress=False)
    finally:
        doc.close()


def extract_text(file_bytes: bytes, content_type: str) -> str:
    if content_type in ("text/plain", "text/markdown"):
        return file_bytes.decode("utf-8")

    if content_type == "application/pdf":
        return extract_pdf_to_markdown(file_bytes)

    raise ValueError(f"Unsupported content type: {content_type}")


def _split_front_matter(text: str, delimiter: str, parser) -> tuple[dict, str]:
    parts = text.split("\n", 1)
    if len(parts) < 2:
        return {}, text

    header_line, rest = parts
    if not rest.strip():
        return {}, text

    close_idx = rest.find(f"\n{delimiter}")
    if close_idx == -1:
        return {}, text

    fm_text = rest[:close_idx]
    remaining = rest[close_idx + len(delimiter) + 1 :]

    try:
        meta = parser(fm_text) or {}
    except Exception:
        logger.warning("Failed to parse front matter")
        return {}, text

    return meta, remaining.lstrip("\n")


def extract_front_matter(text: str) -> tuple[dict, str]:
    stripped = text.lstrip()
    if not stripped:
        return {}, text

    first_line = stripped.split("\n", 1)[0]

    if first_line.startswith("---"):
        return _split_front_matter(stripped, "---", yaml.safe_load)
    if first_line.startswith("+++"):
        return _split_front_matter(stripped, "+++", tomllib.loads)

    return {}, text


def _is_header(line: str) -> tuple[int, str] | None:
    match = re.match(r"^(#{1,6})\s+(.+)$", line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    return None


def _is_code_fence(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    for base in ("```", "~~~"):
        if stripped.startswith(base):
            fence_end = len(base)
            while fence_end < len(stripped) and stripped[fence_end] == base[0]:
                fence_end += 1
            full_fence = stripped[:fence_end]
            lang = stripped[fence_end:].strip()
            return full_fence, lang
    return None


def _is_list_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    return bool(re.match(r"^[-*+]\s+", stripped) or re.match(r"^\d+\.\s+", stripped))


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and "|" in stripped[1:]


def _is_block_start(line: str) -> bool:
    return bool(
        _is_header(line)
        or _is_code_fence(line)
        or _is_table_line(line)
        or _is_list_line(line)
    )


def _scan_markdown(text: str) -> list[Block]:
    lines = text.split("\n")
    blocks: list[Block] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        header = _is_header(line)
        if header:
            level, title = header
            blocks.append(Block(kind=f"h{level}", content=title))
            i += 1
            continue

        fence = _is_code_fence(line)
        if fence:
            fence_chars, _ = fence
            content_lines: list[str] = []
            i += 1
            while i < len(lines):
                closing = lines[i].strip()
                if closing.startswith(fence_chars) and all(
                    c == fence_chars[0] for c in closing
                ):
                    i += 1
                    break
                content_lines.append(lines[i])
                i += 1
            blocks.append(
                Block(kind="code", content="\n".join(content_lines).rstrip("\n"))
            )
            continue

        if _is_table_line(line):
            table_lines: list[str] = []
            while i < len(lines) and _is_table_line(lines[i]):
                table_lines.append(lines[i])
                i += 1
            blocks.append(Block(kind="table", content="\n".join(table_lines)))
            continue

        if _is_list_line(line):
            list_lines: list[str] = [line]
            i += 1
            while i < len(lines):
                if lines[i].strip() == "":
                    lookahead = i + 1
                    while lookahead < len(lines) and not lines[lookahead].strip():
                        lookahead += 1
                    if lookahead < len(lines) and (
                        _is_list_line(lines[lookahead])
                        or lines[lookahead].startswith(("  ", "\t"))
                    ):
                        i += 1
                        continue
                    i += 1
                    break
                if lines[i].startswith(("  ", "\t")) or _is_list_line(lines[i]):
                    list_lines.append(lines[i])
                    i += 1
                else:
                    break
            blocks.append(Block(kind="list", content="\n".join(list_lines)))
            continue

        para_lines: list[str] = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i])
            i += 1
        blocks.append(Block(kind="paragraph", content="\n".join(para_lines)))

    return blocks


def _find_split_boundary(text: str, start: int, end: int) -> int:
    for separator in ("\n\n", "\n", ". ", " "):
        pos = text.rfind(separator, start, end)
        if pos > start:
            return pos + len(separator)
    return end


def chunk_text(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        if end < len(text):
            boundary = _find_split_boundary(text, start, end)
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
        if start >= len(text):
            break

    return chunks


class MarkdownChunker:
    def __init__(self, max_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
        self.max_size = max_size
        self.overlap = overlap
        self.chunks: list[str] = []
        self.header_path: list[tuple[int, str]] = []
        self.current_parts: list[str] = []
        self.current_size = 0
        self.overlap_buffer = ""

    def _add_part(self, part: str) -> None:
        if not self.current_parts and self.overlap_buffer:
            self.current_parts.append(self.overlap_buffer)
            self.current_size = len(self.overlap_buffer)
        if self.current_size > 0:
            self.current_size += 2
        self.current_parts.append(part)
        self.current_size += len(part)

    def _flush(self) -> None:
        if not self.current_parts:
            return
        header_lines = [f"{'#' * level} {title}" for level, title in self.header_path]
        assembled = "\n\n".join(header_lines + self.current_parts)
        self.chunks.append(assembled)

        content_only = "\n\n".join(self.current_parts)
        if len(content_only) > self.overlap:
            self.overlap_buffer = content_only[-self.overlap :]
        else:
            self.overlap_buffer = content_only

        self.current_parts = []
        self.current_size = 0

    def _add_block(self, block: Block) -> None:
        block_size = len(block.content)

        if block.kind == "paragraph" and block_size > self.max_size:
            if self.current_parts:
                self._flush()
            sub_chunks = chunk_text(
                block.content, chunk_size=self.max_size, overlap=self.overlap
            )
            for sub in sub_chunks:
                self._add_part(sub)
                self._flush()
            return

        if block_size > self.max_size and self.current_parts:
            self._flush()

        if self.current_size > 0 and self.current_size + block_size + 2 > self.max_size:
            if block_size > self.max_size:
                self._flush()
                self._add_part(block.content)
                self._flush()
            else:
                self._flush()
                self._add_part(block.content)
        else:
            self._add_part(block.content)

    def _handle_header(self, block: Block) -> None:
        self._flush()
        level = int(block.kind[1:])
        while self.header_path and self.header_path[-1][0] >= level:
            self.header_path.pop()
        self.header_path.append((level, block.content))
        self.overlap_buffer = ""

    def _process_blocks(self, blocks: list[Block]) -> list[str]:
        for block in blocks:
            if block.kind.startswith("h"):
                self._handle_header(block)
                continue
            self._add_block(block)
        self._flush()
        return self.chunks

    def chunk(self, text: str) -> tuple[list[str], dict]:
        meta, cleaned = extract_front_matter(text)
        blocks = _scan_markdown(cleaned)
        return self._process_blocks(blocks), meta


def chunk_markdown(
    text: str, max_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> tuple[list[str], dict]:
    return MarkdownChunker(max_size, overlap).chunk(text)
