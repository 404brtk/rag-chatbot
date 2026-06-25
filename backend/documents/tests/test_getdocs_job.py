import httpx
from unittest.mock import patch, MagicMock
import pytest
from django.urls import reverse
from rest_framework import status

from documents.models import GetDocsJob


@pytest.mark.django_db
class TestCreateGetDocsJob:
    @patch("django.db.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("documents.views.GetDocsClient")
    @patch("documents.views.poll_get_docs_job.delay")
    def test_create_success(
        self, mock_delay, mock_client_class, mock_on_commit, auth_client_a, user_a
    ):
        mock_client = mock_client_class.return_value
        mock_client.trigger_get_docs.return_value = (
            "8a5e3a89-2d4f-4d92-bf93-6c8a0026e2e5"
        )

        url = reverse("getdocs-job-list")
        payload = {
            "url": "https://example.com",
            "max_pages": 50,
            "max_depth": 2,
            "delay_seconds": 1.0,
            "language": "english",
        }

        response = auth_client_a.post(url, payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["job_id"] == "8a5e3a89-2d4f-4d92-bf93-6c8a0026e2e5"
        assert data["status"] == "pending"
        assert data["url"] == "https://example.com"
        assert data["language"] == "english"
        assert data["max_pages"] == 50
        assert data["max_depth"] == 2

        job = GetDocsJob.objects.get(id=data["id"])
        assert job.user == user_a

        mock_delay.assert_called_once_with(job.id)

    def test_create_missing_inputs(self, auth_client_a):
        url = reverse("getdocs-job-list")
        response = auth_client_a.post(url, {"language": "english"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Either 'url' or 'github_repo'" in response.json()["non_field_errors"][0]

    @patch("documents.views.GetDocsClient")
    def test_create_microservice_unavailable(self, mock_client_class, auth_client_a):
        mock_client = mock_client_class.return_value
        mock_client.trigger_get_docs.side_effect = httpx.RequestError(
            "Connection refused", request=MagicMock()
        )

        url = reverse("getdocs-job-list")
        payload = {"url": "https://example.com"}
        response = auth_client_a.post(url, payload, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Failed to trigger job" in response.json()["error"]
