import json
import httpx
import pytest

from src.utils.http_client import HttpClient


@pytest.fixture(autouse=True)
def _no_retry_sleep(mocker):
    mocker.patch("src.utils.http_client.asyncio.sleep", new_callable=mocker.AsyncMock)


def mock_http_client(mocker) -> tuple[HttpClient, httpx.AsyncClient]:
    inner = mocker.AsyncMock(spec=httpx.AsyncClient)
    client = HttpClient(inner, default_delay=0)
    return client, inner


def mock_response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/html; charset=utf-8",
    json_data: dict | list | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode()
        headers = {"content-type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers=headers,
            request=httpx.Request("GET", "https://example.com"),
        )
    headers = {"content-type": content_type}
    if extra_headers:
        headers.update(extra_headers)
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers=headers,
        request=httpx.Request("GET", "https://example.com"),
    )


def html_page(title: str, body: str = "") -> str:
    body_html = f"<p>{body}</p>" if body else ""
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><main><h1>{title}</h1>{body_html}</main></body></html>"
    )
