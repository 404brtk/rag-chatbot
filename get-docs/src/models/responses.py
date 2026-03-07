from dataclasses import dataclass, field

from src.models.enums import SourceMethod


@dataclass
class DocPage:
    url: str
    title: str
    content: str
    source_method: SourceMethod


@dataclass
class EthicsContext:
    crawl_delay_seconds: float | None = None
    content_signal_ai_input: bool | None = None
    license_spdx_id: str | None = None
    license_allowed: bool | None = None
    pages_filtered_by_robots: int = 0
    pages_filtered_by_content_signal: int = 0


@dataclass
class GetDocsResult:
    url: str
    pages: list[DocPage] = field(default_factory=list)
    source_method: SourceMethod | None = None
    github_repo: str | None = None
    ethics: EthicsContext = field(default_factory=EthicsContext)
