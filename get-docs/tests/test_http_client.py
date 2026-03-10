import httpx
import pytest

from src.utils.http_client import get_with_retry
from tests.conftest import mock_response


@pytest.fixture()
def client(mocker):
    c = mocker.AsyncMock(spec=httpx.AsyncClient)
    return c


class TestGetWithRetry:
    @pytest.mark.asyncio
    async def test_success_no_retry(self, client):
        client.get = client.get.__class__(return_value=mock_response(text="ok"))

        resp = await get_with_retry(client, "https://example.com")
        assert resp.status_code == 200
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    async def test_retryable_status_triggers_retry(self, client, status_code):
        client.get = client.get.__class__(
            side_effect=[
                mock_response(status_code=status_code),
                mock_response(text="ok"),
            ]
        )

        resp = await get_with_retry(client, "https://example.com")
        assert resp.status_code == 200
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_after_header_respected(self, mocker, client):
        sleep_mock = mocker.patch(
            "src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock
        )

        retry_resp = httpx.Response(
            status_code=429,
            headers={"Retry-After": "7", "content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com"),
        )
        client.get = client.get.__class__(
            side_effect=[retry_resp, mock_response(text="ok")]
        )

        resp = await get_with_retry(client, "https://example.com")
        assert resp.status_code == 200
        sleep_mock.assert_awaited_once_with(7.0)

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_returns_last_response(self, client):
        client.get = client.get.__class__(return_value=mock_response(status_code=500))

        resp = await get_with_retry(client, "https://example.com", max_retries=2)
        assert resp.status_code == 500
        assert client.get.call_count == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404])
    async def test_non_retryable_status_returned_immediately(self, client, status_code):
        client.get = client.get.__class__(
            return_value=mock_response(status_code=status_code)
        )

        resp = await get_with_retry(client, "https://example.com")
        assert resp.status_code == status_code
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")]
    )
    async def test_transient_error_triggers_retry(self, client, exc):
        client.get = client.get.__class__(side_effect=[exc, mock_response(text="ok")])

        resp = await get_with_retry(client, "https://example.com")
        assert resp.status_code == 200
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_transient_error_exhausted_raises(self, client):
        client.get = client.get.__class__(side_effect=httpx.ReadTimeout("slow"))

        with pytest.raises(httpx.ReadTimeout):
            await get_with_retry(client, "https://example.com", max_retries=1)
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_kwargs_passed_through(self, client):
        client.get = client.get.__class__(return_value=mock_response(text="ok"))

        await get_with_retry(
            client,
            "https://example.com",
            follow_redirects=True,
            timeout=5.0,
            headers={"Accept": "text/html"},
        )
        client.get.assert_called_once_with(
            "https://example.com",
            follow_redirects=True,
            timeout=5.0,
            headers={"Accept": "text/html"},
        )
