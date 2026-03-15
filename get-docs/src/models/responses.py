from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

from src.models.enums import SourceMethod, TaskState
from src.models.requests import GetDocsRequest


@dataclass
class DocPage:
    url: str
    title: str
    content: str
    source_method: SourceMethod


@dataclass
class EthicsContext:
    robots_crawl_delay_seconds: float | None = None
    content_signal_ai_input: bool | None = None
    license_spdx_id: str | None = None
    pages_filtered_by_robots: int = 0
    pages_filtered_by_content_signal: int = 0


@dataclass
class GetDocsResult:
    url: str
    pages: list[DocPage] = field(default_factory=list)
    source_method: SourceMethod | None = None
    github_repo: str | None = None
    ethics: EthicsContext = field(default_factory=EthicsContext)


class DocPageResponse(BaseModel):
    url: str
    title: str
    content: str
    content_length: int


class EthicsInfo(BaseModel):
    robots_crawl_delay_seconds: float | None = None
    content_signal_ai_input: bool | None = None
    license_spdx_id: str | None = None
    pages_filtered_by_robots: int = 0
    pages_filtered_by_content_signal: int = 0


class JobProgress(BaseModel):
    pages_fetched: int = 0
    pages_total: int | None = None


class CrawlCreateResponse(BaseModel):
    job_id: str
    status: TaskState
    created_at: datetime


class CrawlResponse(BaseModel):
    job_id: str
    status: TaskState
    created_at: datetime
    completed_at: datetime | None = None
    url: str | None = None
    github_repo: str | None = None
    source_method: SourceMethod | None = None
    progress: JobProgress | None = None

    # verbose-only fields (excluded from standard responses)
    request: GetDocsRequest | None = None
    ethics: EthicsInfo | None = None

    pages: list[DocPageResponse] = Field(default_factory=list)
