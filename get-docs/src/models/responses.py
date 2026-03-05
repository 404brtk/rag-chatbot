from dataclasses import dataclass, field

from src.models.enums import SourceMethod


@dataclass
class DocPage:
    url: str
    title: str
    content: str
    source_method: SourceMethod


@dataclass
class GetDocsResult:
    url: str
    pages: list[DocPage] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source_method: SourceMethod | None = None
    github_repo: str | None = None
