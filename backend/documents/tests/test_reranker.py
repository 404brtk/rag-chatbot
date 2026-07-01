import pytest
from unittest.mock import MagicMock, patch
import httpx

from documents.reranker import RerankerService
from core.exceptions import TemporaryProviderError


@pytest.fixture(autouse=True)
def _reranker_settings(settings):
    settings.TEI_RERANKER_URL = "http://localhost:8003"


class TestRerankerService:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        RerankerService._instance = None
        yield
        RerankerService._instance = None

    def test_singleton_instance(self):
        instance1 = RerankerService.get_instance()
        instance2 = RerankerService.get_instance()
        assert instance1 is instance2

    @pytest.fixture
    def mock_client(self):
        with patch("httpx.Client") as mock_client_class:
            client = mock_client_class.return_value.__enter__.return_value
            yield client

    def test_rerank_sends_correct_payload(self, mock_client):
        service = RerankerService.get_instance()
        texts = ["Text one", "Text two"]

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"index": 0, "score": 0.9},
            {"index": 1, "score": 0.1},
        ]
        mock_client.post.return_value = mock_response

        results = service.rerank("Query text", texts)

        assert len(results) == 2
        assert results[0]["index"] == 0
        assert results[0]["score"] == 0.9
        assert results[1]["index"] == 1
        assert results[1]["score"] == 0.1

        mock_client.post.assert_called_once_with(
            "http://localhost:8003/rerank",
            json={
                "query": "Query text",
                "texts": ["Text one", "Text two"],
                "truncate": True,
            },
            headers={"Content-Type": "application/json"},
        )

    def test_rerank_empty_list(self):
        service = RerankerService.get_instance()
        assert service.rerank("Query", []) == []

    def test_rerank_error_propagates(self, mock_client):
        service = RerankerService.get_instance()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(TemporaryProviderError, match="Reranking failed"):
            service.rerank("Query", ["Text"])

    def test_4xx_error_raises_directly(self, mock_client):
        service = RerankerService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 422
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unprocessable Entity", request=MagicMock(), response=mock_response
        )
        mock_client.post.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            service.rerank("Query", ["Text"])

    def test_5xx_error_raises_temporary(self, mock_client):
        service = RerankerService.get_instance()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_client.post.return_value = mock_response

        with pytest.raises(
            TemporaryProviderError, match="Reranking failed due to server error"
        ):
            service.rerank("Query", ["Text"])

    def test_rerank_batches_inputs_and_adjusts_indices(self, mock_client):
        service = RerankerService.get_instance()
        texts = [f"Text {i}" for i in range(35)]

        batch1_resp = [{"index": i, "score": 0.5} for i in range(32)]
        batch2_resp = [{"index": i, "score": 0.8} for i in range(3)]

        mock_response1 = MagicMock(spec=httpx.Response)
        mock_response1.status_code = 200
        mock_response1.json.return_value = batch1_resp

        mock_response2 = MagicMock(spec=httpx.Response)
        mock_response2.status_code = 200
        mock_response2.json.return_value = batch2_resp

        mock_client.post.side_effect = [mock_response1, mock_response2]

        results = service.rerank("Query", texts)

        assert len(results) == 35

        for i in range(32):
            assert results[i]["index"] == i
            assert results[i]["score"] == 0.5

        for i in range(3):
            original_index = 32 + i
            assert results[original_index]["index"] == original_index
            assert results[original_index]["score"] == 0.8

        assert mock_client.post.call_count == 2

        first_call_args = mock_client.post.call_args_list[0]
        assert first_call_args[1]["json"]["texts"] == texts[:32]

        second_call_args = mock_client.post.call_args_list[1]
        assert second_call_args[1]["json"]["texts"] == texts[32:]
