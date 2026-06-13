import httpx
from django.conf import settings
from typing import Any


class GetDocsClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url or getattr(settings, "GETDOCS_BASE_URL", "http://localhost:8001")
        ).rstrip("/")

    def trigger_get_docs(
        self,
        url: str | None = None,
        github_repo: str | None = None,
        max_pages: int = 150,
        max_depth: int = 3,
        delay_seconds: float = 1.5,
        crawl_timeout: float = 15.0,
        skip_llms_full: bool = False,
        fair_use: bool = True,
    ) -> str:
        endpoint = f"{self.base_url}/crawl"
        payload = {
            "max_pages": max_pages,
            "max_depth": max_depth,
            "delay_seconds": delay_seconds,
            "timeout": crawl_timeout,
            "skip_llms_full": skip_llms_full,
            "fair_use": fair_use,
        }
        if url:
            payload["url"] = url
        if github_repo:
            payload["github_repo"] = github_repo

        with httpx.Client() as client:
            response = client.post(endpoint, json=payload, timeout=10.0)
            response.raise_for_status()
            try:
                data = response.json()
            except (ValueError, TypeError) as json_err:
                raise httpx.HTTPError(
                    f"Malformed JSON response from get-docs microservice: {json_err}"
                )

            if not isinstance(data, dict):
                raise httpx.HTTPError(
                    "Response from get-docs microservice is not a valid dictionary"
                )

            if "job_id" not in data:
                raise httpx.HTTPError(
                    "Response from get-docs microservice is missing the 'job_id' key"
                )

            return data["job_id"]

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        endpoint = f"{self.base_url}/crawl/{job_id}"
        with httpx.Client() as client:
            response = client.get(endpoint, params={"verbose": "false"}, timeout=10.0)
            response.raise_for_status()
            try:
                data = response.json()
            except (ValueError, TypeError) as json_err:
                raise httpx.HTTPError(
                    f"Malformed JSON response from get-docs microservice: {json_err}"
                )

            if not isinstance(data, dict):
                raise httpx.HTTPError(
                    "Response from get-docs microservice is not a valid dictionary"
                )

            return data
