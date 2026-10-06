from unittest.mock import patch, MagicMock
import pytest
import uuid

from core.exceptions import TemporaryProviderError
from documents.models import Document, GetDocsJob
from documents.tasks import poll_get_docs_job, process_document_embedding_task


@pytest.fixture(autouse=True)
def mock_embedding_task_delay():
    with patch("documents.tasks.process_document_embedding_task.delay") as mock:
        yield mock


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

        mock_doc = MagicMock()
        mock_doc.id = uuid.uuid4()
        mock_doc.meta = {}
        mock_process.return_value = mock_doc

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

        assert mock_process.call_count == 1
        expected_raw_text = (
            "# Page One\n*Source: [https://example.com/page/1](https://example.com/page/1)*\n\n# Page One Content"
            "\n\n---\n\n"
            "# Page Two\n*Source: [https://example.com/page/2](https://example.com/page/2)*\n\n# Page Two Content"
        )
        mock_process.assert_called_once_with(
            user=user_a,
            raw_text=expected_raw_text,
            content_type="text/markdown",
            filename="Docs: https://example.com",
            language="english",
            source_url="https://example.com",
        )
        assert mock_doc.meta["pages_count"] == 2
        assert len(mock_doc.meta["pages"]) == 2

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
        assert job.status == "failed"
        assert "No valid page content" in job.error_message

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

        mock_doc = MagicMock()
        mock_doc.id = uuid.uuid4()
        mock_doc.meta = {}
        mock_process.return_value = mock_doc

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
        assert mock_doc.meta["pages_count"] == 1

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

    def test_nonexistent_job_returns_silently(self):
        poll_get_docs_job(uuid.uuid4())


@pytest.mark.django_db
class TestProcessDocumentEmbeddingTask:
    def test_task_success(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 768]
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello world",
        )

        assert document.status == Document.Status.PENDING

        process_document_embedding_task(str(document.id))

        document.refresh_from_db()
        assert document.status == Document.Status.COMPLETED
        assert document.error_message is None
        assert document.chunks.count() == 1

    def test_task_document_does_not_exist(self):
        process_document_embedding_task("00000000-0000-0000-0000-000000000000")

    def test_task_embedding_failure(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.side_effect = TemporaryProviderError(
            "Service offline"
        )
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello world",
        )

        with pytest.raises(TemporaryProviderError, match="Service offline"):
            process_document_embedding_task(str(document.id))

        document.refresh_from_db()
        assert document.status == Document.Status.FAILED
        assert "Service offline" in document.error_message
