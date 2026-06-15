import os
import uuid
import io
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import InMemoryUploadedFile
import pymupdf
import pymupdf4llm
from PIL import Image
from rest_framework.exceptions import ValidationError


def optimize_uploaded_image(
    file, max_longest_side: int = 2048, quality: int = 85
) -> InMemoryUploadedFile:
    if not file.content_type.startswith("image/"):
        return file

    try:
        img = Image.open(file)
    except Exception:
        return file

    width, height = img.size
    shortest_edge = min(width, height)
    if shortest_edge < 200:
        raise ValidationError(
            f"Image shortest edge ({shortest_edge}px) is below the minimum limit of 200px."
        )

    img.thumbnail((max_longest_side, max_longest_side), Image.Resampling.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    output = io.BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    output.seek(0)

    name_without_ext = os.path.splitext(file.name)[0]
    new_filename = f"{name_without_ext}.jpg"

    return InMemoryUploadedFile(
        file=output,
        field_name=file.field_name,
        name=new_filename,
        content_type="image/jpeg",
        size=output.getbuffer().nbytes,
        charset=file.charset,
    )


def save_local_attachment(file) -> dict:
    file = optimize_uploaded_image(file)

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
