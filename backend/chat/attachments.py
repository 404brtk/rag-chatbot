import os
import uuid
from django.conf import settings
from django.core.files.storage import default_storage


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
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(1024 * 100)
        except Exception:
            pass
    return ""
