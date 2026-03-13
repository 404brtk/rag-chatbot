import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import router
from src.core.llms_txt_fetcher import LlmsTxtResult
from src.core.robots_parser import RobotsParser
from src.utils.http_client import HttpClient


class FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def get(self, key):
        return self._store.get(key)

    async def aclose(self):
        pass


def _mock_http_client():
    client = AsyncMock(spec=HttpClient)
    client.get = AsyncMock(
        return_value=httpx.Response(
            status_code=404,
            text="",
            headers={"content-type": "text/plain"},
            request=httpx.Request("GET", "https://example.com"),
        )
    )
    return client


def _create_test_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.redis = FakeRedis()
        app.state.http_client = _mock_http_client()
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(router)
    return test_app


class TestCreateJob:
    def test_returns_202_with_job_id(self):
        with TestClient(_create_test_app()) as client:
            resp = client.post("/crawl", json={"url": "https://example.com"})
            assert resp.status_code == 202
            data = resp.json()
            assert "job_id" in data
            assert data["status"] == "pending"
            assert "request" not in data
            assert "pages" not in data
            assert "ethics" not in data

    def test_rejects_empty_request(self):
        with TestClient(_create_test_app()) as client:
            resp = client.post("/crawl", json={})
            assert resp.status_code == 422


class TestGetJob:
    def test_returns_pending_job(self):
        with TestClient(_create_test_app()) as client:
            resp = client.post("/crawl", json={"url": "https://example.com"})
            job_id = resp.json()["job_id"]

            resp = client.get(f"/crawl/{job_id}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["job_id"] == job_id
            assert "request" not in data
            assert "ethics" not in data

    def test_returns_404_for_unknown_job(self):
        with TestClient(_create_test_app()) as client:
            resp = client.get("/crawl/nonexistent-id")
            assert resp.status_code == 404


class TestJobCompletion:
    @pytest.mark.asyncio
    async def test_job_completes_with_pages(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://example.com/llms-full.txt",
                raw_content="# Full Docs",
                title="Docs",
                is_full=True,
            ),
        )

        with TestClient(_create_test_app()) as client:
            resp = client.post("/crawl", json={"url": "https://example.com"})
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            await asyncio.sleep(0.5)

            resp = client.get(f"/crawl/{job_id}")
            data = resp.json()
            assert data["status"] == "completed"
            assert len(data["pages"]) == 1
            assert data["pages"][0]["content"] == "# Full Docs"
            assert data["pages"][0]["content_length"] == 11
            assert "ethics" not in data
            assert "request" not in data

    @pytest.mark.asyncio
    async def test_verbose_returns_ethics_and_request(self, mocker):
        mocker.patch(
            "src.core.orchestrator.fetch_robots_txt",
            return_value=RobotsParser(""),
        )
        mocker.patch(
            "src.core.orchestrator.fetch_llms_txt",
            return_value=LlmsTxtResult(
                source_url="https://example.com/llms-full.txt",
                raw_content="# Full Docs",
                title="Docs",
                is_full=True,
            ),
        )

        with TestClient(_create_test_app()) as client:
            resp = client.post("/crawl", json={"url": "https://example.com"})
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            await asyncio.sleep(0.5)

            resp = client.get(f"/crawl/{job_id}", params={"verbose": "true"})
            data = resp.json()
            assert data["status"] == "completed"
            assert data["ethics"] is not None
            assert data["request"] is not None
            assert data["request"]["url"] == "https://example.com/"
