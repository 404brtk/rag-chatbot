import json
import httpx


def mock_response(
    status_code: int = 200,
    text: str = "",
    content_type: str = "text/html; charset=utf-8",
    json_data: dict | list | None = None,
) -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode()
        return httpx.Response(
            status_code=status_code,
            content=content,
            headers={"content-type": "application/json"},
            request=httpx.Request("GET", "https://example.com"),
        )
    return httpx.Response(
        status_code=status_code,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com"),
    )


def html_page(title: str, body: str = "") -> str:
    body_html = f"<p>{body}</p>" if body else ""
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><main><h1>{title}</h1>{body_html}</main></body></html>"
    )
