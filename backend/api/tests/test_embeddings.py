import threading
from unittest.mock import MagicMock, patch

import pytest

from api.embeddings import EmbeddingService


@pytest.fixture(autouse=True)
def _embedding_settings(settings):
    settings.EMBEDDING_DIMENSIONS = 384


@pytest.fixture
def mock_sentence_transformer():
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        mock_instance = MagicMock()
        mock_instance.get_sentence_embedding_dimension.return_value = 384

        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.1] * 384, [0.2] * 384]
        mock_instance.encode.return_value = mock_array

        mock_st.return_value = mock_instance
        yield mock_instance


class TestEmbeddingService:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._dimensions = None
        EmbeddingService._lock = threading.Lock()
        yield
        EmbeddingService._instance = None
        EmbeddingService._model = None
        EmbeddingService._dimensions = None
        EmbeddingService._lock = threading.Lock()

    def test_singleton_instance(self):
        instance1 = EmbeddingService.get_instance()
        instance2 = EmbeddingService.get_instance()
        assert instance1 is instance2

    def test_lazy_loading(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()
        assert service._model is None

        dim = service.dimensions
        assert dim == 384
        mock_sentence_transformer.get_sentence_embedding_dimension.assert_called_once()
        assert service._model is not None

    def test_embed_texts(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()
        texts = ["Text one", "Text two"]

        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.1] * 384, [0.2] * 384]
        mock_sentence_transformer.encode.return_value = mock_array

        embeddings = service.embed_texts(texts)

        assert len(embeddings) == 2
        assert len(embeddings[0]) == 384
        assert len(embeddings[1]) == 384
        mock_sentence_transformer.encode.assert_called_once_with(
            texts, normalize_embeddings=True, show_progress_bar=False
        )

    def test_embed_query(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()

        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.5] * 384]
        mock_sentence_transformer.encode.return_value = mock_array

        embedding = service.embed_query("A query")

        assert len(embedding) == 384
        mock_sentence_transformer.encode.assert_called_once_with(
            ["A query"], normalize_embeddings=True, show_progress_bar=False
        )

    def test_dimension_mismatch_raises(self, settings):
        settings.EMBEDDING_DIMENSIONS = 768

        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_instance = MagicMock()
            mock_instance.get_sentence_embedding_dimension.return_value = 384
            mock_st.return_value = mock_instance

            service = EmbeddingService.get_instance()
            with pytest.raises(RuntimeError, match="produces 384 dimensions"):
                service.dimensions

    def test_idempotent_load(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()

        service.dimensions
        mock_sentence_transformer.get_sentence_embedding_dimension.assert_called_once()

        service.embed_texts(["Another text"])
        mock_sentence_transformer.encode.assert_called_once()

        mock_sentence_transformer.get_sentence_embedding_dimension.assert_called_once()

    def test_embed_texts_with_unicode(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()

        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.3] * 384]
        mock_sentence_transformer.encode.return_value = mock_array

        embedding = service.embed_texts(["Café résumé naïve 🌍"])

        assert len(embedding) == 1
        assert len(embedding[0]) == 384

    def test_embed_query_empty_string(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()

        mock_array = MagicMock()
        mock_array.tolist.return_value = [[0.0] * 384]
        mock_sentence_transformer.encode.return_value = mock_array

        embedding = service.embed_query("")

        assert len(embedding) == 384
        mock_sentence_transformer.encode.assert_called_once_with(
            [""], normalize_embeddings=True, show_progress_bar=False
        )

    def test_encode_error_propagates(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()
        mock_sentence_transformer.encode.side_effect = RuntimeError("GPU OOM")

        with pytest.raises(RuntimeError, match="GPU OOM"):
            service.embed_texts(["Text"])

    def test_thread_safe_initialization(self, mock_sentence_transformer):
        service = EmbeddingService.get_instance()
        barrier = threading.Barrier(5)
        dimensions = []
        errors = []

        def worker():
            try:
                barrier.wait()
                dimensions.append(service.dimensions)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(dimensions) == 5
        assert all(d == 384 for d in dimensions)
        mock_sentence_transformer.get_sentence_embedding_dimension.assert_called_once()

    def test_missing_model_setting_raises(self, settings):
        del settings.EMBEDDING_MODEL

        with pytest.raises(AttributeError):
            EmbeddingService.get_instance().dimensions
