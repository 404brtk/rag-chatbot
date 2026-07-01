import httpx
from unittest.mock import patch, MagicMock
import pytest

from documents.get_docs_client import GetDocsClient


@pytest.mark.django_db
class TestTriggerGetDocs:
    def test_returns_job_id_on_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "abc-123"}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            client = GetDocsClient()
            job_id = client.trigger_get_docs(url="https://example.com")

        assert job_id == "abc-123"

    def test_sends_all_params_in_payload(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "abc-123"}
        mock_response.raise_for_status.return_value = None

        with patch.object(
            httpx.Client, "post", return_value=mock_response
        ) as mock_post:
            client = GetDocsClient()
            client.trigger_get_docs(
                url="https://example.com",
                max_pages=50,
                max_depth=2,
                delay_seconds=1.0,
                crawl_timeout=30.0,
                skip_llms_full=True,
                fair_use=False,
            )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        assert payload["url"] == "https://example.com"
        assert payload["max_pages"] == 50
        assert payload["max_depth"] == 2
        assert payload["delay_seconds"] == 1.0
        assert payload["timeout"] == 30.0
        assert payload["skip_llms_full"] is True
        assert payload["fair_use"] is False

    def test_sends_github_repo_in_payload(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "abc-123"}
        mock_response.raise_for_status.return_value = None

        with patch.object(
            httpx.Client, "post", return_value=mock_response
        ) as mock_post:
            client = GetDocsClient()
            client.trigger_get_docs(github_repo="owner/repo")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["github_repo"] == "owner/repo"
        assert "url" not in payload

    def test_sends_github_token_in_payload(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"job_id": "abc-123"}
        mock_response.raise_for_status.return_value = None

        with patch.object(
            httpx.Client, "post", return_value=mock_response
        ) as mock_post:
            client = GetDocsClient()
            client.trigger_get_docs(
                github_repo="owner/repo", github_token="ghp_test123"
            )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["github_token"] == "ghp_test123"

    def test_raises_on_http_error(self):
        with patch.object(
            httpx.Client, "post", side_effect=httpx.HTTPError("Server error")
        ):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="Server error"):
                client.trigger_get_docs(url="https://example.com")

    def test_raises_on_malformed_json(self):
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="Malformed JSON response"):
                client.trigger_get_docs(url="https://example.com")

    def test_raises_on_non_dict_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="not a valid dictionary"):
                client.trigger_get_docs(url="https://example.com")

    def test_raises_on_missing_job_id(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "pending"}
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "post", return_value=mock_response):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="missing the 'job_id' key"):
                client.trigger_get_docs(url="https://example.com")


@pytest.mark.django_db
class TestGetDocsClientGetJobStatus:
    def test_returns_data_on_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "job_id": "abc-123",
            "status": "completed",
            "pages": [],
            "progress": {"pages_fetched": 0, "pages_total": 0},
        }
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "get", return_value=mock_response):
            client = GetDocsClient()
            result = client.get_job_status("abc-123")

        assert result["job_id"] == "abc-123"
        assert result["status"] == "completed"

    def test_raises_on_http_error(self):
        with patch.object(
            httpx.Client, "get", side_effect=httpx.HTTPError("Not found")
        ):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="Not found"):
                client.get_job_status("abc-123")

    def test_raises_on_malformed_json(self):
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "get", return_value=mock_response):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="Malformed JSON response"):
                client.get_job_status("abc-123")

    def test_raises_on_non_dict_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = "just a string"
        mock_response.raise_for_status.return_value = None

        with patch.object(httpx.Client, "get", return_value=mock_response):
            client = GetDocsClient()
            with pytest.raises(httpx.HTTPError, match="not a valid dictionary"):
                client.get_job_status("abc-123")
