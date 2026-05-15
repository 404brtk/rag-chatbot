from unittest.mock import patch

import pytest

from api.document_service import DocumentService, SearchResult
from api.models import Document, DocumentChunk


@pytest.fixture
def mock_embedding_service():
    with patch("api.document_service.EmbeddingService.get_instance") as mock:
        instance = mock.return_value
        instance.embed_texts.return_value = [[0.1] * 384]
        instance.embed_query.return_value = [0.1] * 384
        yield instance


def _make_embedding(*values, dim=384):
    vec = [0.0] * dim
    for i, v in enumerate(values):
        vec[i] = v
    return vec


class TestCreateDocumentChunks:
    @pytest.mark.django_db
    def test_bulk_creates_chunks_with_embeddings(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384, [0.2] * 384]
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello world",
        )

        service = DocumentService()
        service._create_document_chunks(document, ["Hello", "world"])

        chunks = DocumentChunk.objects.filter(document=document).order_by("chunk_index")
        assert chunks.count() == 2
        assert chunks[0].content == "Hello"
        assert chunks[0].chunk_index == 0
        assert list(chunks[0].embedding) == [0.1] * 384
        assert chunks[1].content == "world"
        assert chunks[1].chunk_index == 1
        assert list(chunks[1].embedding) == [0.2] * 384
        mock_embedding_service.embed_texts.assert_called_once_with(["Hello", "world"])

    @pytest.mark.django_db
    def test_skips_empty_chunks(self, user_a, mock_embedding_service):
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello",
        )

        service = DocumentService()
        service._create_document_chunks(document, [])

        assert DocumentChunk.objects.filter(document=document).count() == 0
        mock_embedding_service.embed_texts.assert_not_called()


@pytest.mark.django_db
class TestSearch:
    def test_returns_ordered_results(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_query.return_value = _make_embedding(1.0)
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello world python code",
        )
        DocumentChunk.objects.create(
            document=document,
            content="python code example",
            chunk_index=0,
            embedding=_make_embedding(1.0),
        )
        DocumentChunk.objects.create(
            document=document,
            content="irrelevant text",
            chunk_index=1,
            embedding=_make_embedding(0.0, 1.0),
        )

        service = DocumentService()
        results = service.search(user=user_a, query="python")

        assert len(results) == 1
        assert results[0].chunk_content == "python code example"
        assert results[0].document_id == str(document.id)
        assert results[0].document_filename == "test.txt"
        assert results[0].chunk_index == 0
        assert isinstance(results[0].distance, float)

    def test_filters_by_document_ids(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_query.return_value = _make_embedding(1.0)
        doc_a = Document.objects.create(
            user=user_a,
            filename="a.txt",
            content_type="text/plain",
            raw_text="doc a",
        )
        doc_b = Document.objects.create(
            user=user_a,
            filename="b.txt",
            content_type="text/plain",
            raw_text="doc b",
        )
        DocumentChunk.objects.create(
            document=doc_a,
            content="content a",
            chunk_index=0,
            embedding=_make_embedding(1.0),
        )
        DocumentChunk.objects.create(
            document=doc_b,
            content="content b",
            chunk_index=0,
            embedding=_make_embedding(1.0),
        )

        service = DocumentService()
        results = service.search(
            user=user_a, query="test", document_ids=[str(doc_a.id)]
        )

        assert len(results) == 1
        assert results[0].chunk_content == "content a"

    def test_isolates_by_user(self, user_a, user_b, mock_embedding_service):
        mock_embedding_service.embed_query.return_value = _make_embedding(1.0)
        doc = Document.objects.create(
            user=user_a,
            filename="secret.txt",
            content_type="text/plain",
            raw_text="secret",
        )
        DocumentChunk.objects.create(
            document=doc,
            content="secret content",
            chunk_index=0,
            embedding=_make_embedding(1.0),
        )

        service = DocumentService()
        results = service.search(user=user_b, query="secret")

        assert len(results) == 0

    def test_no_results_below_threshold(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_query.return_value = _make_embedding(1.0)
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="test",
        )
        DocumentChunk.objects.create(
            document=document,
            content="far away content",
            chunk_index=0,
            embedding=_make_embedding(0.0, 1.0),
        )

        service = DocumentService()
        results = service.search(user=user_a, query="test")

        assert len(results) == 0

    def test_returns_search_result_dataclass(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_query.return_value = _make_embedding(1.0)
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="test",
        )
        DocumentChunk.objects.create(
            document=document,
            content="test content",
            chunk_index=0,
            embedding=_make_embedding(1.0),
        )

        service = DocumentService()
        results = service.search(user=user_a, query="test")

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].distance < 0.3
