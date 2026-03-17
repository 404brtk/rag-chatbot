from datetime import datetime, timezone

from src.models.enums import SourceMethod, TaskState
from src.models.requests import GetDocsRequest
from src.models.responses import (
    CrawlCreateResponse,
    CrawlResponse,
    DocPageResponse,
    EthicsContext,
    EthicsInfo,
    GetDocsResult,
    JobProgress,
)


class TestDocPageResponse:
    def test_serialization(self):
        page = DocPageResponse(
            url="https://example.com/docs",
            title="Docs",
            content="# Hello",
            content_length=7,
        )
        data = page.model_dump()
        assert data["content_length"] == 7


class TestEthicsInfo:
    def test_defaults(self):
        info = EthicsInfo()
        assert info.pages_filtered_by_robots_txt == 0
        assert info.pages_filtered_by_content_signal == 0
        assert info.robots_crawl_delay_seconds is None
        assert info.content_signal_ai_input is None
        assert info.license_spdx_id is None

    def test_with_values(self):
        info = EthicsInfo(
            robots_crawl_delay_seconds=2.0,
            license_spdx_id="MIT",
            pages_filtered_by_robots_txt=3,
            content_signal_ai_input=True,
            pages_filtered_by_content_signal=1,
        )
        data = info.model_dump()
        assert data["robots_crawl_delay_seconds"] == 2.0
        assert data["license_spdx_id"] == "MIT"
        assert data["pages_filtered_by_robots_txt"] == 3
        assert data["content_signal_ai_input"] is True
        assert data["pages_filtered_by_content_signal"] == 1


class TestEthicsContext:
    def test_mutable_counters(self):
        ctx = EthicsContext()
        ctx.pages_filtered_by_robots_txt += 2
        ctx.pages_filtered_by_content_signal += 1
        assert ctx.pages_filtered_by_robots_txt == 2
        assert ctx.pages_filtered_by_content_signal == 1


class TestGetDocsResult:
    def test_has_ethics(self):
        result = GetDocsResult(url="https://example.com")
        assert result.ethics is not None
        assert result.ethics.pages_filtered_by_robots_txt == 0


class TestCrawlCreateResponse:
    def test_serialization(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        resp = CrawlCreateResponse(
            job_id="abc-123",
            status=TaskState.PENDING,
            created_at=now,
        )
        data = resp.model_dump()
        assert data["job_id"] == "abc-123"
        assert data["status"] == "pending"
        assert "pages" not in data
        assert "ethics" not in data
        assert "request" not in data

    def test_roundtrip(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        resp = CrawlCreateResponse(
            job_id="abc-123",
            status=TaskState.PENDING,
            created_at=now,
        )
        json_str = resp.model_dump_json()
        restored = CrawlCreateResponse.model_validate_json(json_str)
        assert restored.job_id == "abc-123"
        assert restored.status == TaskState.PENDING


class TestCrawlResponse:
    def test_serialization_roundtrip(self):
        job = CrawlResponse(
            job_id="abc-123",
            status=TaskState.COMPLETED,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            source_method=SourceMethod.LLMS_TXT,
            pages=[
                DocPageResponse(
                    url="https://example.com/llms-full.txt",
                    title="Docs",
                    content="# Full",
                    content_length=6,
                )
            ],
            ethics=EthicsInfo(license_spdx_id="MIT"),
        )
        json_str = job.model_dump_json()
        restored = CrawlResponse.model_validate_json(json_str)
        assert restored.job_id == "abc-123"
        assert restored.status == TaskState.COMPLETED
        assert len(restored.pages) == 1
        assert restored.ethics.license_spdx_id == "MIT"

    def test_pending_job_minimal(self):
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.PENDING,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
        )
        data = job.model_dump()
        assert data["pages"] == []
        assert data["ethics"] is None
        assert data["progress"] is None

    def test_in_progress_with_progress(self):
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.IN_PROGRESS,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            progress=JobProgress(pages_fetched=10, pages_total=50),
        )
        data = job.model_dump()
        assert data["progress"]["pages_fetched"] == 10
        assert data["progress"]["pages_total"] == 50

    def test_verbose_fields_default_none(self):
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.PENDING,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert job.request is None
        assert job.ethics is None

    def test_verbose_fields_present_when_set(self):
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.COMPLETED,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            ethics=EthicsInfo(license_spdx_id="Apache-2.0"),
        )
        assert job.request is not None
        assert job.request.url is not None
        assert job.ethics.license_spdx_id == "Apache-2.0"

    def test_standard_response_excludes_verbose_fields(self):
        """Simulates what the GET endpoint does for non-verbose responses."""
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.COMPLETED,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            ethics=EthicsInfo(license_spdx_id="MIT"),
            pages=[
                DocPageResponse(
                    url="https://example.com/doc",
                    title="Doc",
                    content="# Doc",
                    content_length=5,
                )
            ],
        )
        # Exclude verbose fields (like the endpoint does)
        data = job.model_dump(exclude={"request", "ethics"})
        assert "request" not in data
        assert "ethics" not in data
        assert len(data["pages"]) == 1
        assert data["job_id"] == "xyz"

    def test_verbose_response_includes_all_fields(self):
        """Simulates what the GET endpoint does for verbose responses."""
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.COMPLETED,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            ethics=EthicsInfo(license_spdx_id="MIT"),
            pages=[
                DocPageResponse(
                    url="https://example.com/doc",
                    title="Doc",
                    content="# Doc",
                    content_length=5,
                )
            ],
        )
        data = job.model_dump()
        assert "request" in data
        assert "ethics" in data
        assert data["ethics"]["license_spdx_id"] == "MIT"
        assert len(data["pages"]) == 1

    def test_field_order_request_ethics_before_pages(self):
        """Verbose fields should appear before pages in serialized output."""
        job = CrawlResponse(
            job_id="xyz",
            status=TaskState.COMPLETED,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            request=GetDocsRequest(url="https://example.com"),
            ethics=EthicsInfo(),
            pages=[
                DocPageResponse(
                    url="https://example.com/doc",
                    title="Doc",
                    content="# Doc",
                    content_length=5,
                )
            ],
        )
        keys = list(job.model_dump().keys())
        assert keys.index("request") < keys.index("pages")
        assert keys.index("ethics") < keys.index("pages")
