import httpx
import pytest

from src.utils.http_client import HttpClient
from tests.conftest import mock_response


@pytest.fixture()
def client(mocker):
    inner = mocker.AsyncMock(spec=httpx.AsyncClient)
    return HttpClient(inner, default_delay=0)


def _inner(client: HttpClient):
    return client._client


class TestRetryBehavior:
    @pytest.mark.asyncio
    async def test_success_no_retry(self, client):
        _inner(client).get = _inner(client).get.__class__(
            return_value=mock_response(text="ok")
        )

        resp = await client.get("https://example.com")
        assert resp.status_code == 200
        assert _inner(client).get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    async def test_retryable_status_triggers_retry(self, client, status_code):
        _inner(client).get = _inner(client).get.__class__(
            side_effect=[
                mock_response(status_code=status_code),
                mock_response(text="ok"),
            ]
        )

        resp = await client.get("https://example.com")
        assert resp.status_code == 200
        assert _inner(client).get.call_count == 2

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
        _inner(client).get = _inner(client).get.__class__(
            side_effect=[retry_resp, mock_response(text="ok")]
        )

        resp = await client.get("https://example.com")
        assert resp.status_code == 200
        sleep_mock.assert_awaited_once_with(7.0)

    @pytest.mark.asyncio
    async def test_max_retries_exhausted_returns_last_response(self, client):
        _inner(client).get = _inner(client).get.__class__(
            return_value=mock_response(status_code=500)
        )

        resp = await client.get("https://example.com", max_retries=2)
        assert resp.status_code == 500
        assert _inner(client).get.call_count == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status_code", [403, 404])
    async def test_non_retryable_status_returned_immediately(self, client, status_code):
        _inner(client).get = _inner(client).get.__class__(
            return_value=mock_response(status_code=status_code)
        )

        resp = await client.get("https://example.com")
        assert resp.status_code == status_code
        assert _inner(client).get.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("refused")]
    )
    async def test_transient_error_triggers_retry(self, client, exc):
        _inner(client).get = _inner(client).get.__class__(
            side_effect=[exc, mock_response(text="ok")]
        )

        resp = await client.get("https://example.com")
        assert resp.status_code == 200
        assert _inner(client).get.call_count == 2

    @pytest.mark.asyncio
    async def test_transient_error_exhausted_raises(self, client):
        _inner(client).get = _inner(client).get.__class__(
            side_effect=httpx.ReadTimeout("slow")
        )

        with pytest.raises(httpx.ReadTimeout):
            await client.get("https://example.com", max_retries=1)
        assert _inner(client).get.call_count == 2

    @pytest.mark.asyncio
    async def test_kwargs_passed_through(self, client):
        _inner(client).get = _inner(client).get.__class__(
            return_value=mock_response(text="ok")
        )

        await client.get(
            "https://example.com",
            follow_redirects=True,
            timeout=5.0,
            headers={"Accept": "text/html"},
        )
        _inner(client).get.assert_called_once_with(
            "https://example.com",
            follow_redirects=True,
            timeout=5.0,
            headers={"Accept": "text/html"},
        )


class TestThrottling:
    @pytest.mark.asyncio
    async def test_same_domain_requests_are_throttled(self, mocker):
        sleep_mock = mocker.patch(
            "src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock
        )
        inner = mocker.AsyncMock(spec=httpx.AsyncClient)
        inner.get = mocker.AsyncMock(return_value=mock_response(text="ok"))
        client = HttpClient(inner, default_delay=2.0)

        await client.get("https://example.com/a")
        await client.get("https://example.com/b")

        assert inner.get.call_count == 2
        throttle_sleeps = [c.args[0] for c in sleep_mock.call_args_list]
        assert len(throttle_sleeps) == 1
        assert throttle_sleeps[0] == pytest.approx(2.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_different_domains_throttled_independently(self, mocker):
        sleep_mock = mocker.patch(
            "src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock
        )
        inner = mocker.AsyncMock(spec=httpx.AsyncClient)
        inner.get = mocker.AsyncMock(return_value=mock_response(text="ok"))
        client = HttpClient(inner, default_delay=5.0)

        await client.get("https://example.com/a")
        await client.get("https://other.com/b")

        assert inner.get.call_count == 2
        sleep_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_domain_delay_overrides_default(self, mocker):
        sleep_mock = mocker.patch(
            "src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock
        )
        inner = mocker.AsyncMock(spec=httpx.AsyncClient)
        inner.get = mocker.AsyncMock(return_value=mock_response(text="ok"))
        client = HttpClient(inner, default_delay=1.0)
        client.set_domain_delay("example.com", 10.0)

        await client.get("https://example.com/a")
        await client.get("https://example.com/b")

        throttle_sleeps = [c.args[0] for c in sleep_mock.call_args_list]
        assert len(throttle_sleeps) == 1
        assert throttle_sleeps[0] == pytest.approx(10.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_zero_delay_skips_throttle(self, mocker):
        sleep_mock = mocker.patch(
            "src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock
        )
        inner = mocker.AsyncMock(spec=httpx.AsyncClient)
        inner.get = mocker.AsyncMock(return_value=mock_response(text="ok"))
        client = HttpClient(inner, default_delay=0)

        await client.get("https://example.com/a")
        await client.get("https://example.com/b")

        assert inner.get.call_count == 2
        sleep_mock.assert_not_awaited()


class TestAclose:
    @pytest.mark.asyncio
    async def test_delegates_to_inner_client(self, client):
        await client.aclose()
        _inner(client).aclose.assert_awaited_once()


class TestFetchMany:
    @pytest.fixture()
    def fetch_client(self, mocker):
        inner = mocker.AsyncMock(spec=httpx.AsyncClient)
        return HttpClient(inner, default_delay=0)

    @pytest.mark.asyncio
    async def test_runs_sequentially_not_concurrently(self, fetch_client):
        import asyncio

        active = 0
        max_active = 0

        async def fetch(item):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            active -= 1
            return item * 10

        results = await fetch_client.fetch_many(list(range(5)), fetch)

        assert max_active == 1
        assert len(results) == 5
        assert [item for item, _ in results] == [0, 1, 2, 3, 4]

    @pytest.mark.asyncio
    async def test_order_preserved(self, fetch_client):
        async def fetch(item):
            return item * 2

        results = await fetch_client.fetch_many([1, 2, 3, 4, 5], fetch)

        items = [item for item, _ in results]
        assert items == [1, 2, 3, 4, 5]
        values = [result for _, result in results]
        assert values == [2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    async def test_exceptions_returned_not_raised(self, fetch_client):
        async def fetch(item):
            if item == 2:
                raise ValueError("boom")
            return item * 10

        results = await fetch_client.fetch_many([1, 2, 3], fetch)

        assert len(results) == 3
        assert results[0] == (1, 10)
        assert results[1][0] == 2
        assert isinstance(results[1][1], ValueError)
        assert results[2] == (3, 30)

    @pytest.mark.asyncio
    async def test_continues_after_exception(self, fetch_client):
        async def fetch(item):
            if item == 1:
                raise RuntimeError("fail")
            return item

        results = await fetch_client.fetch_many([1, 2, 3], fetch)

        assert isinstance(results[0][1], RuntimeError)
        assert results[1] == (2, 2)
        assert results[2] == (3, 3)

    @pytest.mark.asyncio
    async def test_empty_items(self, fetch_client):
        async def fetch(item):
            return item

        results = await fetch_client.fetch_many([], fetch)
        assert results == []

    @pytest.mark.asyncio
    async def test_progress_called_for_each_item(self, fetch_client):
        progress_calls: list[tuple[int, int]] = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        async def fetch(item):
            return item

        await fetch_client.fetch_many(
            [1, 2, 3],
            fetch,
            on_progress=on_progress,
        )

        assert progress_calls == [(1, 3), (2, 3), (3, 3)]

    @pytest.mark.asyncio
    async def test_progress_offset_and_total(self, fetch_client):
        progress_calls: list[tuple[int, int]] = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        async def fetch(item):
            return item

        await fetch_client.fetch_many(
            [1, 2],
            fetch,
            on_progress=on_progress,
            progress_offset=5,
            progress_total=10,
        )

        assert progress_calls == [(6, 10), (7, 10)]

    @pytest.mark.asyncio
    async def test_progress_called_even_on_exception(self, fetch_client):
        progress_calls: list[tuple[int, int]] = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        async def fetch(item):
            if item == 2:
                raise ValueError("boom")
            return item

        await fetch_client.fetch_many(
            [1, 2, 3],
            fetch,
            on_progress=on_progress,
        )

        assert progress_calls == [(1, 3), (2, 3), (3, 3)]
