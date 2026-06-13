import pytest

from documents.document_service import DocumentService, SearchResult
from documents.models import Document, DocumentChunk


def _make_embedding(*values, dim=384):
    vec = [0.0] * dim
    for i, v in enumerate(values):
        vec[i] = v
    return vec


@pytest.mark.django_db
class TestCreateDocumentChunks:
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

    def test_populates_word_count_and_search_vector(
        self, user_a, mock_embedding_service
    ):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384]
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="three word sentence",
        )

        service = DocumentService()
        service._create_document_chunks(document, ["three word sentence"])

        chunk = DocumentChunk.objects.get(document=document)
        assert chunk.word_count == 3
        assert chunk.search_vector is not None

    def test_prepends_source_url_when_present(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384]
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello",
            source_url="https://example.com/page",
        )

        service = DocumentService()
        service._create_document_chunks(document, ["Hello world"])

        chunk = DocumentChunk.objects.get(document=document)
        assert chunk.content == "Source: https://example.com/page\n\nHello world"

    def test_no_source_url_prefix_when_missing(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384]
        document = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="Hello",
        )

        service = DocumentService()
        service._create_document_chunks(document, ["Plain content"])

        chunk = DocumentChunk.objects.get(document=document)
        assert chunk.content == "Plain content"


@pytest.mark.django_db
class TestReciprocalRankFusion:
    def test_single_list(self):
        scores = DocumentService._reciprocal_rank_fusion(["a", "b", "c"], k=60)
        assert scores["a"] == pytest.approx(1 / 61)
        assert scores["b"] == pytest.approx(1 / 62)
        assert scores["c"] == pytest.approx(1 / 63)

    def test_overlapping_lists_boost_shared_items(self):
        scores = DocumentService._reciprocal_rank_fusion(["a", "b"], ["b", "c"], k=60)
        assert scores["b"] > scores["a"]
        assert scores["b"] > scores["c"]

    def test_empty_lists(self):
        scores = DocumentService._reciprocal_rank_fusion([], [], k=60)
        assert scores == {}


@pytest.mark.django_db
class TestKeywordBm25Search:
    def test_returns_empty_for_blank_query(self, user_a, mock_embedding_service):
        service = DocumentService()
        assert (
            service._keyword_bm25_search(user=user_a, english_query="", polish_query="")
            == {}
        )
        assert (
            service._keyword_bm25_search(
                user=user_a, english_query="   ", polish_query="   "
            )
            == {}
        )

    def test_multilingual_isolation(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384, [0.2] * 384]

        doc_en = Document.objects.create(
            user=user_a,
            filename="english.txt",
            content_type="text/plain",
            raw_text="The quick brown fox jumps over the lazy dog",
            language="english",
        )
        doc_pl = Document.objects.create(
            user=user_a,
            filename="polish.txt",
            content_type="text/plain",
            raw_text="Szybki brązowy lis przeskakuje nad leniwym psem",
            language="polish",
        )

        service = DocumentService()
        service._create_document_chunks(
            doc_en, ["The quick brown fox jumps over the lazy dog"]
        )
        service._create_document_chunks(
            doc_pl, ["Szybki brązowy lis przeskakuje nad leniwym psem"]
        )

        chunk_en_id = str(DocumentChunk.objects.get(document=doc_en).id)
        chunk_pl_id = str(DocumentChunk.objects.get(document=doc_pl).id)

        en_results = service._keyword_bm25_search(
            user=user_a, english_query="fox", polish_query=""
        )
        assert chunk_en_id in en_results
        assert chunk_pl_id not in en_results

        pl_results = service._keyword_bm25_search(
            user=user_a, english_query="", polish_query="lis"
        )
        assert chunk_pl_id in pl_results
        assert chunk_en_id not in pl_results

    def test_or_semantics_matches_partial_terms(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [
            [0.1] * 384,
            [0.2] * 384,
        ]

        doc = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="python web framework",
            language="english",
        )

        service = DocumentService()
        service._create_document_chunks(doc, ["python web framework"])

        results = service._keyword_bm25_search(
            user=user_a, english_query="python database", polish_query=""
        )
        chunk_id = str(DocumentChunk.objects.get(document=doc).id)
        assert chunk_id in results

    def test_english_stemming(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384]

        doc = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="The runners were running fast",
            language="english",
        )

        service = DocumentService()
        service._create_document_chunks(doc, ["The runners were running fast"])

        results = service._keyword_bm25_search(
            user=user_a, english_query="run", polish_query=""
        )
        assert len(results) == 1


@pytest.mark.django_db
class TestSearch:
    def test_returns_ordered_search_results(self, user_a, mock_embedding_service):
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

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].chunk_content == "python code example"
        assert results[1].chunk_content == "irrelevant text"
        assert results[0].score > results[1].score
        assert isinstance(results[0].score, float)
        assert results[0].document_id == str(document.id)
        assert results[0].document_filename == "test.txt"
        assert results[0].chunk_index == 0

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

    def test_bm25_only_results_included_via_rrf(self, user_a, mock_embedding_service):
        mock_embedding_service.embed_texts.return_value = [[0.1] * 384]
        mock_embedding_service.embed_query.return_value = _make_embedding(0.0, 0.0, 1.0)

        doc = Document.objects.create(
            user=user_a,
            filename="test.txt",
            content_type="text/plain",
            raw_text="django framework tutorial",
            language="english",
        )
        service = DocumentService()
        service._create_document_chunks(doc, ["django framework tutorial"])

        results = service.search(user=user_a, query="django")

        assert len(results) == 1
        assert results[0].chunk_content == "django framework tutorial"
