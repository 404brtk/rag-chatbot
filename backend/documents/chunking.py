import logging
import re
import threading
import tomllib
from dataclasses import dataclass

import pymupdf
import pymupdf4llm
import yaml
from django.conf import settings

logger = logging.getLogger(__name__)

HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$")
UNORDERED_LIST_RE = re.compile(r"^[-*+]\s+")
ORDERED_LIST_RE = re.compile(r"^\d+\.\s+")

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


class TokenizerLoader:
    _tokenizer = None
    _init_attempted = False
    _lock = threading.Lock()

    @classmethod
    def get_tokenizer(cls):
        if cls._init_attempted:
            return cls._tokenizer
        with cls._lock:
            if cls._init_attempted:
                return cls._tokenizer
            try:
                from transformers import AutoTokenizer

                cls._tokenizer = AutoTokenizer.from_pretrained(settings.EMBEDDING_MODEL)
                cls._tokenizer.model_max_length = 1_000_000
            except ImportError:
                logger.info(
                    "transformers package not installed, using character-based chunking"
                )
            except Exception:
                logger.exception(
                    "Failed to load tokenizer, using character-based chunking"
                )
            finally:
                cls._init_attempted = True
        return cls._tokenizer


def get_tokenizer():
    return TokenizerLoader.get_tokenizer()


def get_token_count(text: str) -> int:
    tok = get_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(text, add_special_tokens=False))
        except Exception:
            pass
    return int(len(text.split()) * 1.33)


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
    match = HEADER_RE.match(line)
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
    return bool(UNORDERED_LIST_RE.match(stripped) or ORDERED_LIST_RE.match(stripped))


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
            fence_header = line.strip()
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
            raw_code = "\n".join(content_lines).rstrip("\n")
            blocks.append(
                Block(kind="code", content=f"{fence_header}\n{raw_code}\n{fence_chars}")
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
                        i = lookahead
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

    tokenizer = get_tokenizer()
    if tokenizer is not None:
        try:
            token_ids = tokenizer.encode(text, add_special_tokens=False)
            if len(token_ids) <= chunk_size:
                return [text]

            chunks: list[str] = []
            start = 0
            while start < len(token_ids):
                end = start + chunk_size
                chunk_tokens = token_ids[start:end]
                decoded = tokenizer.decode(
                    chunk_tokens, skip_special_tokens=True
                ).strip()
                if decoded:
                    chunks.append(decoded)

                next_start = end - overlap
                if next_start <= start:
                    next_start = end
                start = next_start
                if start >= len(token_ids):
                    break
            return chunks
        except Exception:
            logger.exception(
                "Failed to chunk by tokens, falling back to character chunking."
            )

    char_chunk_size = chunk_size * 5
    char_overlap = overlap * 5

    if len(text) <= char_chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + char_chunk_size

        if end < len(text):
            boundary = _find_split_boundary(text, start, end)
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        next_start = end - char_overlap
        if next_start <= start:
            next_start = end
        start = next_start
        if start >= len(text):
            break

    return chunks


@dataclass(frozen=True, slots=True)
class ParentChunkData:
    content: str
    child_texts: list[str]
    header_breadcrumb: str | None = None


class MarkdownChunker:
    def __init__(
        self,
        parent_size: int | None = None,
        parent_overlap: int | None = None,
        child_size: int | None = None,
        child_overlap: int | None = None,
    ):
        self.parent_size = (
            parent_size
            if parent_size is not None
            else getattr(settings, "PARENT_CHUNK_SIZE", 1024)
        )
        self.parent_overlap = (
            parent_overlap
            if parent_overlap is not None
            else getattr(settings, "PARENT_CHUNK_OVERLAP", 200)
        )
        self.child_size = (
            child_size
            if child_size is not None
            else getattr(settings, "CHILD_CHUNK_SIZE", 256)
        )
        self.child_overlap = (
            child_overlap
            if child_overlap is not None
            else getattr(settings, "CHILD_CHUNK_OVERLAP", 32)
        )

    def _flush_parent(
        self,
        current_parts: list[str],
        header_path: list[tuple[int, str]],
        parents: list[tuple[str, str | None]],
    ) -> int:
        if not current_parts:
            return 0
        header_breadcrumb = (
            " > ".join(t for _, t in header_path) if header_path else None
        )
        header_lines = [f"{'#' * lvl} {t}" for lvl, t in header_path]
        assembled = "\n\n".join(header_lines + current_parts)
        parents.append((assembled, header_breadcrumb))
        current_parts.clear()
        return 0

    def chunk(self, text: str) -> tuple[list[ParentChunkData], dict]:
        meta, cleaned = extract_front_matter(text)
        blocks = _scan_markdown(cleaned)

        parents: list[tuple[str, str | None]] = []
        header_path: list[tuple[int, str]] = []
        current_parts: list[str] = []
        current_size = 0

        for block in blocks:
            if block.kind.startswith("h"):
                current_size = self._flush_parent(current_parts, header_path, parents)
                level = int(block.kind[1:])
                while header_path and header_path[-1][0] >= level:
                    header_path.pop()
                header_path.append((level, block.content))
                continue

            block_size = get_token_count(block.content)

            if current_size > 0 and current_size + block_size + 2 > self.parent_size:
                current_size = self._flush_parent(current_parts, header_path, parents)

            current_parts.append(block.content)
            current_size += block_size + (2 if len(current_parts) > 1 else 0)

        self._flush_parent(current_parts, header_path, parents)

        parent_data_list: list[ParentChunkData] = []
        for content, breadcrumb in parents:
            child_texts = chunk_text(
                content,
                chunk_size=self.child_size,
                overlap=self.child_overlap,
            )
            parent_data_list.append(
                ParentChunkData(
                    content=content,
                    child_texts=child_texts if child_texts else [content],
                    header_breadcrumb=breadcrumb,
                )
            )

        return parent_data_list, meta


def chunk_markdown(
    text: str,
) -> tuple[list[ParentChunkData], dict]:
    return MarkdownChunker().chunk(text)
