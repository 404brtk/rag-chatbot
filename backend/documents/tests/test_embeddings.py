import pytest
from unittest.mock import MagicMock, patch
import httpx

from documents.embeddings import EmbeddingService
from core.exceptions import TemporaryProviderError

DIM = 768


@pytest.fixture(autouse=True)
def _embedding_settings(settings):
    settings.EMBEDDING_DIMENSIONS = DIM
    settings.TEI_EMBEDDING_URL = "http://localhost:8002"


class TestEmbeddingService:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        EmbeddingService._instance = None
        yield
        EmbeddingService._instance = None

    def test_singleton_instance(self):
        instance1 = EmbeddingService.get_instance()
        instance2 = EmbeddingService.get_instance()
        assert instance1 is instance2

    def test_dimensions(self):
        service = EmbeddingService.get_instance()
        assert service.dimensions == DIM

    @pytest.fixture
    def mock_client(self):
        with patch("httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            yield client

    def test_embed_texts_sends_passage_prefix(self, mock_client):
        service = EmbeddingService.get_instance()
        texts = ["Text one", "Text two"]

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [[0.1] * DIM, [0.2] * DIM]
        mock_client.post.return_value = mock_response

        embeddings = service.embed_texts(texts)

        assert len(embeddings) == 2
        assert len(embeddings[0]) == DIM
        assert len(embeddings[1]) == DIM
        mock_client.post.assert_called_once_with(
            "http://localhost:8002/embed",
            json={
                "inputs": ["passage: Text one", "passage: Text two"],
                "truncate": True,
            },
            headers={"Content-Type": "application/json"},
        )

    def test_embed_query_sends_query_prefix(self, mock_client):
        service = EmbeddingService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [[0.5] * DIM]
        mock_client.post.return_value = mock_response

        embedding = service.embed_query("A query")

        assert len(embedding) == DIM
        mock_client.post.assert_called_once_with(
            "http://localhost:8002/embed",
            json={"inputs": ["query: A query"], "truncate": True},
            headers={"Content-Type": "application/json"},
        )

    def test_embed_texts_with_unicode(self, mock_client):
        service = EmbeddingService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [[0.3] * DIM]
        mock_client.post.return_value = mock_response

        embedding = service.embed_texts(["Café résumé naïve 🌍"])

        assert len(embedding) == 1
        assert len(embedding[0]) == DIM
        mock_client.post.assert_called_once_with(
            "http://localhost:8002/embed",
            json={
                "inputs": ["passage: Café résumé naïve 🌍"],
                "truncate": True,
            },
            headers={"Content-Type": "application/json"},
        )

    def test_embed_texts_empty_list(self):
        service = EmbeddingService.get_instance()
        assert service.embed_texts([]) == []

    def test_encode_error_propagates(self, mock_client):
        service = EmbeddingService.get_instance()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(TemporaryProviderError, match="Embedding generation failed"):
            service.embed_texts(["Text"])

    def test_4xx_error_raises_directly(self, mock_client):
        service = EmbeddingService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 422
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unprocessable Entity", request=MagicMock(), response=mock_response
        )
        mock_client.post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            service.embed_texts(["Text"])

    def test_5xx_error_raises_temporary(self, mock_client):
        service = EmbeddingService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_client.post.return_value = mock_response

        with pytest.raises(TemporaryProviderError, match="Embedding generation failed"):
            service.embed_texts(["Text"])

    def test_missing_dimensions_setting_raises(self, settings):
        del settings.EMBEDDING_DIMENSIONS

        service = EmbeddingService.get_instance()
        with pytest.raises(AttributeError):
            service.dimensions
