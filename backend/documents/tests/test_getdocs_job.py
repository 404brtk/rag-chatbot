import httpx
import uuid
from unittest.mock import patch, MagicMock
import pytest
from django.urls import reverse
from rest_framework import status

from documents.models import GetDocsJob, Document
from documents.tasks import poll_get_docs_job


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


@pytest.mark.django_db
class TestPollGetDocsJob:
    @patch("documents.tasks.GetDocsClient")
    @patch("documents.tasks.DocumentService.process_text")
    def test_completed_job_ingests_all_pages(
        self, mock_process, mock_client_class, user_a
    ):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "completed",
            "source_method": "sitemap_crawl",
            "progress": {"pages_fetched": 2, "pages_total": 2},
            "pages": [
                {
                    "url": "https://example.com/page/1",
                    "title": "Page One",
                    "content": "# Page One Content",
                },
                {
                    "url": "https://example.com/page/2",
                    "title": "Page Two",
                    "content": "# Page Two Content",
                },
            ],
        }

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-success",
            url="https://example.com",
            language="english",
            status="pending",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "completed"
        assert job.pages_fetched == 2
        assert job.pages_total == 2
        assert job.source_method == "sitemap_crawl"
        assert job.completed_at is not None
        assert job.error_message is None

        assert mock_process.call_count == 2
        mock_process.assert_any_call(
            user=user_a,
            raw_text="# Page One Content",
            content_type="text/markdown",
            filename="Page One - example.com/page/1",
            language="english",
            source_url="https://example.com/page/1",
        )
        mock_process.assert_any_call(
            user=user_a,
            raw_text="# Page Two Content",
            content_type="text/markdown",
            filename="Page Two - example.com/page/2",
            language="english",
            source_url="https://example.com/page/2",
        )

    @patch("documents.tasks.GetDocsClient")
    def test_no_pages_skips_ingestion(self, mock_client_class, user_a):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "completed",
            "progress": {"pages_fetched": 0, "pages_total": 0},
            "pages": [],
        }

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-empty",
            url="https://example.com",
            language="english",
            status="pending",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "completed"
        assert job.pages_fetched == 0

    @patch("documents.tasks.GetDocsClient")
    @patch("documents.tasks.DocumentService.process_text")
    def test_empty_page_content_is_skipped(
        self, mock_process, mock_client_class, user_a
    ):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "completed",
            "progress": {"pages_fetched": 1, "pages_total": 1},
            "pages": [
                {
                    "url": "https://example.com/page/1",
                    "title": "Empty Page",
                    "content": "",
                },
                {
                    "url": "https://example.com/page/2",
                    "title": "Good Page",
                    "content": "# Valid Content",
                },
            ],
        }

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-empty-page",
            url="https://example.com",
            language="english",
            status="pending",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "completed"
        mock_process.assert_called_once()

    @patch("documents.tasks.GetDocsClient")
    def test_failed_in_microservice(self, mock_client_class, user_a):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "failed",
            "progress": {"pages_fetched": 0, "pages_total": 0},
            "pages": [],
        }

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-failed",
            url="https://example.com",
            language="english",
            status="pending",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "failed"
        assert "failed in microservice" in job.error_message.lower()
        assert job.completed_at is not None

    @patch("documents.tasks.GetDocsClient")
    @patch("documents.tasks.DocumentService.process_text")
    def test_partial_ingestion_failure(self, mock_process, mock_client_class, user_a):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "completed",
            "progress": {"pages_fetched": 2, "pages_total": 2},
            "pages": [
                {
                    "url": "https://example.com/page/good",
                    "title": "Good Page",
                    "content": "# Good Content",
                },
                {
                    "url": "https://example.com/page/bad",
                    "title": "Bad Page",
                    "content": "# Bad Content",
                },
            ],
        }

        def fail_bad_page(user, raw_text, content_type, filename, language):
            if "bad" in filename.lower():
                raise ValueError("Simulated ingestion failure")

        mock_process.side_effect = fail_bad_page

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-partial-fail",
            url="https://example.com",
            language="english",
            status="pending",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "completed"
        assert "Processing completed with partial failures" in job.error_message
        assert "Bad Page" in job.error_message

        assert mock_process.call_count == 2

    @patch("documents.tasks.GetDocsClient")
    @patch("documents.tasks.DocumentService.process_text")
    def test_skips_already_ingested_page(self, mock_process, mock_client_class, user_a):
        mock_client = mock_client_class.return_value
        mock_client.get_job_status.return_value = {
            "status": "completed",
            "progress": {"pages_fetched": 1, "pages_total": 1},
            "pages": [
                {
                    "url": "https://example.com/page/1",
                    "title": "Already There",
                    "content": "# Duplicate Content",
                },
            ],
        }

        job = GetDocsJob.objects.create(
            user=user_a,
            job_id="test-job-dup-check",
            url="https://example.com",
            language="english",
            status="pending",
        )

        Document.objects.create(
            user=user_a,
            filename="Already There - example.com/page/1",
            content_type="text/markdown",
            raw_text="# Already ingested",
            language="english",
        )

        poll_get_docs_job(job.id)

        job.refresh_from_db()
        assert job.status == "completed"

        mock_process.assert_not_called()

    def test_nonexistent_job_returns_silently(self):
        poll_get_docs_job(uuid.uuid4())
