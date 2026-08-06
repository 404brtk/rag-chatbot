import logging
import os

import anydoc
import pymupdf
import pymupdf4llm

logger = logging.getLogger(__name__)

SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
        "application/msword",  # doc
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
        "application/vnd.ms-powerpoint",  # ppt
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
        "application/vnd.ms-excel",  # xls
        "text/csv",
        "application/rtf",
        "text/rtf",
        "application/epub+zip",
        "application/vnd.oasis.opendocument.text",  # odt
        "application/vnd.oasis.opendocument.spreadsheet",  # ods
        "application/vnd.oasis.opendocument.presentation",  # odp
    }
)

SUPPORTED_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".pdf",
        ".docx",
        ".doc",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".csv",
        ".rtf",
        ".epub",
        ".odt",
        ".ods",
        ".odp",
    }
)

TEXT_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".markdown",
        ".py",
        ".js",
        ".ts",
        ".json",
        ".html",
        ".css",
        ".yaml",
        ".yml",
        ".toml",
    }
)


def get_extension(filename: str) -> str:
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


def is_pdf(content_type: str = "", filename: str = "") -> bool:
    if content_type == "application/pdf":
        return True
    return get_extension(filename) == ".pdf"


def is_plain_text(content_type: str = "", filename: str = "") -> bool:
    if content_type in ("text/plain", "text/markdown"):
        return True
    ext = get_extension(filename)
    return ext in TEXT_EXTENSIONS


def is_supported_document(content_type: str = "", filename: str = "") -> bool:
    if content_type in SUPPORTED_CONTENT_TYPES:
        return True
    ext = get_extension(filename)
    return ext in SUPPORTED_EXTENSIONS or ext in TEXT_EXTENSIONS


def extract_pdf_to_markdown(file_source: str | bytes) -> str:
    if isinstance(file_source, bytes):
        doc = pymupdf.open(stream=file_source, filetype="pdf")
    else:
        doc = pymupdf.open(file_source)
    try:
        return pymupdf4llm.to_markdown(doc, show_progress=False)
    finally:
        doc.close()


def extract_anydoc_to_markdown(
    file_source: str | bytes, content_type: str = "", filename: str = ""
) -> str:
    ext = get_extension(filename).lstrip(".")

    try:
        if isinstance(file_source, bytes):
            if ext == "csv" or content_type == "text/csv":
                return anydoc.to_markdown_bytes(file_source, "csv")
            return anydoc.to_markdown_bytes(file_source)
        else:
            return anydoc.to_markdown(file_source)
    except anydoc.ConvertError as e:
        logger.warning(f"Anydoc conversion failed for '{filename or file_source}': {e}")
        raise ValueError(f"Could not parse document '{filename or 'file'}': {e}") from e
    except Exception as e:
        logger.exception(
            f"Unexpected error during anydoc conversion for '{filename or file_source}'"
        )
        raise ValueError(f"Error reading document: {e}") from e


def extract_text(
    file_source: str | bytes, content_type: str = "", filename: str = ""
) -> str:
    if is_plain_text(content_type, filename):
        if isinstance(file_source, bytes):
            return file_source.decode("utf-8", errors="ignore")
        with open(file_source, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if is_pdf(content_type, filename):
        return extract_pdf_to_markdown(file_source)

    if is_supported_document(content_type, filename):
        return extract_anydoc_to_markdown(file_source, content_type, filename)

    target_name = filename or content_type or "file"
    raise ValueError(
        f"Unsupported document format: '{target_name}'. "
        f"Supported types include: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, RTF, EPUB, ODT, TXT, MD."
    )
