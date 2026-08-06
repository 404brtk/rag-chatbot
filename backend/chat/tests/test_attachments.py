import io
import os
from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.exceptions import ValidationError

from chat.attachments import load_text_attachment, save_local_attachment


@pytest.mark.django_db
class TestAttachmentUploadView:
    def test_upload_requires_auth(self, client):
        url = reverse("attachment-upload")
        file = SimpleUploadedFile(
            "test.png", b"fake image content", content_type="image/png"
        )
        response = client.post(url, {"file": file}, format="multipart")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_upload_success(self, auth_client_a):
        url = reverse("attachment-upload")
        file = SimpleUploadedFile(
            "test.png", b"fake image content", content_type="image/png"
        )

        with patch("chat.views.save_local_attachment") as mock_save:
            mock_save.return_value = {
                "id": "uuid-name.png",
                "name": "test.png",
                "size": 18,
                "mimeType": "image/png",
                "saved_path": "attachments/uuid-name.png",
            }
            response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "test.png"
        assert data["id"] == "uuid-name.png"
        assert "media/attachments/uuid-name.png" in data["url"]

    def test_upload_missing_file(self, auth_client_a):
        url = reverse("attachment-upload")
        response = auth_client_a.post(url, {}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"] == "No file uploaded"


@pytest.fixture
def temp_media_root(tmp_path, settings):
    media_dir = tmp_path / "media"
    attachments_dir = media_dir / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    settings.MEDIA_ROOT = str(media_dir)
    return attachments_dir


def test_load_text_attachment_not_exists(temp_media_root):
    assert load_text_attachment("does_not_exist.txt") == ""


def test_load_text_attachment_unsafe_path(temp_media_root):
    assert load_text_attachment("../secret.txt") == ""
    assert load_text_attachment("sub/folder.txt") == ""


def test_load_text_attachment_small_txt(temp_media_root):
    file_path = temp_media_root / "small.txt"
    file_path.write_text("hello world", encoding="utf-8")

    content = load_text_attachment("small.txt")
    assert content == "hello world"


def test_load_text_attachment_large_txt(temp_media_root):
    file_path = temp_media_root / "large.txt"
    limit = 1024 * 100
    large_content = "a" * (limit + 50)
    file_path.write_text(large_content, encoding="utf-8")

    content = load_text_attachment("large.txt")
    expected_content = "a" * limit + "\n[WARNING: File truncated to 100KB limit]"
    assert content == expected_content


@patch("chat.attachments.extract_text")
def test_load_text_attachment_pdf_small(mock_extract_text, temp_media_root):
    file_path = temp_media_root / "doc.pdf"
    file_path.write_bytes(b"dummy pdf bytes")

    mock_extract_text.return_value = "# Header\nSome content"

    content = load_text_attachment("doc.pdf")

    mock_extract_text.assert_called_once_with(
        str(file_path), content_type="", filename="doc.pdf"
    )
    assert content == "# Header\nSome content"


@patch("chat.attachments.extract_text")
def test_load_text_attachment_docx_small(mock_extract_text, temp_media_root):
    file_path = temp_media_root / "doc.docx"
    file_path.write_bytes(b"dummy docx bytes")

    mock_extract_text.return_value = "# Word Header\nWord content"

    content = load_text_attachment("doc.docx")

    mock_extract_text.assert_called_once_with(
        str(file_path), content_type="", filename="doc.docx"
    )
    assert content == "# Word Header\nWord content"


@patch("chat.attachments.extract_text")
def test_load_text_attachment_pdf_large(mock_extract_text, temp_media_root):
    file_path = temp_media_root / "large.pdf"
    file_path.write_bytes(b"dummy pdf bytes")

    limit = 1024 * 100
    large_md = "# Header\n" + "x" * (limit + 100)
    mock_extract_text.return_value = large_md

    content = load_text_attachment("large.pdf")

    mock_extract_text.assert_called_once_with(
        str(file_path), content_type="", filename="large.pdf"
    )

    expected_content = large_md[:limit] + "\n[WARNING: File truncated to 100KB limit]"
    assert content == expected_content


def generate_test_image(
    width: int, height: int, color=(255, 0, 0), format: str = "PNG"
) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format=format)
    buf.seek(0)
    return buf.getvalue()


class TestImageOptimization:
    def test_bypasses_non_image_files(self, temp_media_root):
        file = SimpleUploadedFile("test.txt", b"hello world", content_type="text/plain")
        res = save_local_attachment(file)

        assert res["name"] == "test.txt"
        assert res["mimeType"] == "text/plain"
        assert res["size"] == 11
        assert os.path.exists(os.path.join(settings.MEDIA_ROOT, res["saved_path"]))

    def test_rejects_tiny_images(self, temp_media_root):
        img_bytes = generate_test_image(150, 150)
        file = SimpleUploadedFile("tiny.png", img_bytes, content_type="image/png")

        with pytest.raises(ValidationError) as exc_info:
            save_local_attachment(file)

        assert "shortest edge (150px) is below the minimum limit of 200px" in str(
            exc_info.value
        )

    def test_optimizes_small_valid_image(self, temp_media_root):
        img_bytes = generate_test_image(300, 400, format="PNG")
        file = SimpleUploadedFile("photo.png", img_bytes, content_type="image/png")

        res = save_local_attachment(file)

        assert res["name"] == "photo.jpg"
        assert res["mimeType"] == "image/jpeg"

        local_path = os.path.join(settings.MEDIA_ROOT, res["saved_path"])
        assert os.path.exists(local_path)
        with Image.open(local_path) as saved_img:
            assert saved_img.format == "JPEG"
            assert saved_img.size == (300, 400)

    def test_resizes_large_image(self, temp_media_root):
        img_bytes = generate_test_image(3000, 1500, format="PNG")
        file = SimpleUploadedFile("large.png", img_bytes, content_type="image/png")

        res = save_local_attachment(file)

        assert res["name"] == "large.jpg"
        assert res["mimeType"] == "image/jpeg"

        local_path = os.path.join(settings.MEDIA_ROOT, res["saved_path"])
        assert os.path.exists(local_path)
        with Image.open(local_path) as saved_img:
            assert saved_img.format == "JPEG"
            assert saved_img.size == (2048, 1024)

    def test_graceful_fallback_for_corrupted_image(self, temp_media_root):
        file = SimpleUploadedFile(
            "broken.png", b"corrupted bytes", content_type="image/png"
        )

        res = save_local_attachment(file)

        assert res["name"] == "broken.png"
        assert res["mimeType"] == "image/png"
        assert res["size"] == 15
        assert os.path.exists(os.path.join(settings.MEDIA_ROOT, res["saved_path"]))
