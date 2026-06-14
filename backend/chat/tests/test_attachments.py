from unittest.mock import MagicMock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from chat.attachments import load_text_attachment


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


@patch("chat.attachments.pymupdf.open")
@patch("chat.attachments.pymupdf4llm.to_markdown")
def test_load_text_attachment_pdf_small(
    mock_to_markdown, mock_pdf_open, temp_media_root
):
    file_path = temp_media_root / "doc.pdf"
    file_path.write_bytes(b"dummy pdf bytes")

    mock_doc = MagicMock()
    mock_pdf_open.return_value = mock_doc
    mock_to_markdown.return_value = "# Header\nSome content"

    content = load_text_attachment("doc.pdf")

    mock_pdf_open.assert_called_once_with(str(file_path))
    mock_to_markdown.assert_called_once_with(mock_doc, show_progress=False)
    mock_doc.close.assert_called_once()
    assert content == "# Header\nSome content"


@patch("chat.attachments.pymupdf.open")
@patch("chat.attachments.pymupdf4llm.to_markdown")
def test_load_text_attachment_pdf_large(
    mock_to_markdown, mock_pdf_open, temp_media_root
):
    file_path = temp_media_root / "large.pdf"
    file_path.write_bytes(b"dummy pdf bytes")

    mock_doc = MagicMock()
    mock_pdf_open.return_value = mock_doc

    limit = 1024 * 100
    large_md = "# Header\n" + "x" * (limit + 100)
    mock_to_markdown.return_value = large_md

    content = load_text_attachment("large.pdf")

    mock_pdf_open.assert_called_once_with(str(file_path))
    mock_to_markdown.assert_called_once_with(mock_doc, show_progress=False)
    mock_doc.close.assert_called_once()

    expected_content = large_md[:limit] + "\n[WARNING: File truncated to 100KB limit]"
    assert content == expected_content
