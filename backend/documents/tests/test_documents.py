from unittest.mock import patch, AsyncMock

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status

from documents.models import Document, DocumentChunk, DocumentLanguage
from documents.document_service import SearchResult


@pytest.mark.django_db
class TestDocumentViewSet:
    @patch("django.db.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("documents.views.process_document_embedding_task.delay")
    def test_upload_text_file(self, mock_delay, mock_on_commit, auth_client_a, user_a):
        url = reverse("document-list")
        file = SimpleUploadedFile("test.txt", b"Hello world", content_type="text/plain")
        response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["filename"] == "test.txt"
        assert data["status"] == "pending"

        doc = Document.objects.get(id=data["id"])
        assert doc.raw_text == "Hello world"
        mock_delay.assert_called_once_with(doc.id)

    def test_upload_empty_file_returns_error(self, auth_client_a):
        url = reverse("document-list")
        file = SimpleUploadedFile("empty.txt", b"", content_type="text/plain")
        response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Could not extract" in response.json()["error"]

    @patch("django.db.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("documents.views.process_document_embedding_task.delay")
    @patch("documents.document_service.extract_text", return_value="Extracted PDF text")
    def test_upload_pdf_file(
        self, mock_extract, mock_delay, mock_on_commit, auth_client_a, user_a
    ):
        url = reverse("document-list")
        file = SimpleUploadedFile(
            "test.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["filename"] == "test.pdf"
        assert data["content_type"] == "application/pdf"
        assert data["status"] == "pending"
        mock_extract.assert_called_once()
        mock_delay.assert_called_once()

    def test_upload_unsupported_file(self, auth_client_a):
        url = reverse("document-list")
        file = SimpleUploadedFile(
            "test.exe", b"dummy", content_type="application/octet-stream"
        )
        response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Unsupported file type" in response.json()["error"]

    def test_upload_file_too_large(self, auth_client_a, settings):
        settings.FILE_UPLOAD_MAX_SIZE = 10
        url = reverse("document-list")
        file = SimpleUploadedFile("test.txt", b"12345678901", content_type="text/plain")
        response = auth_client_a.post(url, {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "File too large" in response.json()["error"]

    def test_list_documents_only_own(
        self, auth_client_a, user_a, user_b, mock_embedding_service
    ):
        Document.objects.create(
            user=user_a, filename="mine.txt", content_type="text/plain", raw_text="123"
        )
        Document.objects.create(
            user=user_b,
            filename="theirs.txt",
            content_type="text/plain",
            raw_text="456",
        )

        url = reverse("document-list")
        response = auth_client_a.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["filename"] == "mine.txt"

    def test_delete_document_cascades_to_chunks(self, auth_client_a, user_a):
        doc = Document.objects.create(
            user=user_a, filename="mine.txt", content_type="text/plain", raw_text="123"
        )
        DocumentChunk.objects.create(
            document=doc,
            content="123",
            chunk_index=0,
            embedding=[0.0] * settings.EMBEDDING_DIMENSIONS,
        )

        assert DocumentChunk.objects.count() == 1

        url = reverse("document-detail", kwargs={"pk": doc.pk})
        response = auth_client_a.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Document.objects.count() == 0
        assert DocumentChunk.objects.count() == 0

    def test_cannot_delete_other_users_document(self, auth_client_a, user_b):
        doc = Document.objects.create(
            user=user_b,
            filename="theirs.txt",
            content_type="text/plain",
            raw_text="123",
        )

        url = reverse("document-detail", kwargs={"pk": doc.pk})
        response = auth_client_a.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Document.objects.count() == 1

    @patch("django.db.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("documents.views.process_document_embedding_task.delay")
    def test_paste_text_plain(self, mock_delay, mock_on_commit, auth_client_a, user_a):
        url = reverse("document-list")
        response = auth_client_a.post(
            url,
            {
                "content": "Hello pasted text",
                "content_type": "text/plain",
                "filename": "notes.txt",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["filename"] == "notes.txt"
        assert data["content_type"] == "text/plain"
        assert data["status"] == "pending"

        doc = Document.objects.get(id=data["id"])
        assert doc.raw_text == "Hello pasted text"
        mock_delay.assert_called_once_with(doc.id)

    @patch("django.db.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("documents.views.process_document_embedding_task.delay")
    def test_paste_text_markdown(
        self, mock_delay, mock_on_commit, auth_client_a, user_a
    ):
        url = reverse("document-list")
        response = auth_client_a.post(
            url,
            {
                "content": "# Title\n\nBody text.",
                "content_type": "text/markdown",
                "filename": "doc.md",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["filename"] == "doc.md"
        assert data["content_type"] == "text/markdown"
        assert data["status"] == "pending"

        doc = Document.objects.get(id=data["id"])
        assert "# Title" in doc.raw_text
        mock_delay.assert_called_once_with(doc.id)

    def test_paste_text_missing_content(self, auth_client_a):
        url = reverse("document-list")
        response = auth_client_a.post(
            url,
            {"content_type": "text/plain"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.json()

    def test_paste_text_invalid_content_type(self, auth_client_a):
        url = reverse("document-list")
        response = auth_client_a.post(
            url,
            {"content": "Hello", "content_type": "application/pdf"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content_type" in response.json()

    def test_paste_text_empty_content(self, auth_client_a):
        url = reverse("document-list")
        response = auth_client_a.post(
            url,
            {"content": "   ", "content_type": "text/plain"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "content" in response.json()


class TestDocumentLanguage:
    def test_english_returns_english(self):
        assert DocumentLanguage.get_pg_regconfig("english") == "english"

    def test_polish_returns_polish(self):
        assert DocumentLanguage.get_pg_regconfig("polish") == "polish"

    def test_unknown_language_defaults_to_simple(self):
        assert DocumentLanguage.get_pg_regconfig("spanish") == "simple"


@pytest.mark.django_db
class TestDocumentRetrieveView:
    def test_retrieve_missing_query_returns_400(self, client):
        url = reverse("document-retrieve")
        response = client.post(url, data={}, content_type="application/json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Error: 'query' field is required" in response.content.decode()

    @pytest.mark.django_db
    @patch("documents.views.DocumentService.search", new_callable=AsyncMock)
    def test_retrieve_success_returns_markdown(self, mock_search, client, user_a):
        mock_search.return_value = [
            SearchResult(
                chunk_content="Sample mock content Alpha.",
                document_id="mock-doc-id-1",
                document_filename="doc_alpha.md",
                chunk_index=0,
                score=0.95,
                source_url=None,
            ),
            SearchResult(
                chunk_content="Sample mock content Beta.",
                document_id="mock-doc-id-2",
                document_filename="doc_beta.md",
                chunk_index=1,
                score=0.85,
                source_url="https://example.com/docs/beta",
            ),
        ]

        url = reverse("document-retrieve")
        response = client.post(
            url,
            data={"query": "test query"},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "text/markdown"
        content = response.content.decode()
        assert "sources:" in content
        assert "- doc_alpha.md" in content
        assert "- https://example.com/docs/beta" in content
        assert "### Source: doc_alpha.md" in content
        assert "Sample mock content Alpha." in content

    @pytest.mark.django_db
    @patch("documents.views.DocumentService.search", new_callable=AsyncMock)
    def test_retrieve_empty_results(self, mock_search, client, user_a):
        mock_search.return_value = []
        url = reverse("document-retrieve")
        response = client.post(
            url,
            data={"query": "test query"},
            content_type="application/json",
        )

        assert response.status_code == status.HTTP_200_OK
        content = response.content.decode()
        assert "sources: []" in content
        assert "No relevant documentation found." in content
