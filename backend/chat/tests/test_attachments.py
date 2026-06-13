from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status


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
