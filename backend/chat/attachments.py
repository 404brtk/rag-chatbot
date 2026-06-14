import os
import uuid
from django.conf import settings
from django.core.files.storage import default_storage
import pymupdf
import pymupdf4llm


def save_local_attachment(file) -> dict:
    ext = os.path.splitext(file.name)[1]
    unique_name = f"{uuid.uuid4()}{ext}"
    saved_path = default_storage.save(f"attachments/{unique_name}", file)
    return {
        "id": unique_name,
        "name": file.name,
        "size": file.size,
        "mimeType": file.content_type,
        "saved_path": saved_path,
    }


def is_safe_attachment_path(filename: str) -> bool:
    if not filename:
        return False
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    if os.path.basename(filename) != filename:
        return False
    return True


def load_text_attachment(filename: str) -> str:
    if not is_safe_attachment_path(filename):
        return ""
    local_path = os.path.join(settings.MEDIA_ROOT, "attachments", filename)
    if not os.path.exists(local_path):
        return ""

    limit = 1024 * 100

    try:
        if filename.lower().endswith(".pdf"):
            doc = pymupdf.open(local_path)
            try:
                markdown_text = pymupdf4llm.to_markdown(doc, show_progress=False)
                if len(markdown_text) > limit:
                    return (
                        markdown_text[:limit]
                        + "\n[WARNING: File truncated to 100KB limit]"
                    )
                return markdown_text
            finally:
                doc.close()
        else:
            with open(local_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(limit)
                if f.read(1):
                    content += "\n[WARNING: File truncated to 100KB limit]"
                return content
    except Exception:
        return ""
