from pydantic import BaseModel, HttpUrl


class CrawlOptions(BaseModel):
    max_depth: int = 3
    delay_seconds: float = 1.5
    max_pages: int = 100
    max_concurrent: int = 10


class CrawlRequest(BaseModel):
    url: HttpUrl
    github_repo: str | None = None
    options: CrawlOptions = CrawlOptions()
