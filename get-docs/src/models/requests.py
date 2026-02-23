from pydantic import BaseModel, HttpUrl


class CrawlOptions(BaseModel):
    max_depth = 3  # recursion limit for following page links
    delay_seconds = 1.5
    max_pages = 100


class CrawlRequest(BaseModel):
    url: HttpUrl
    github_repo: str | None = None
    options: CrawlOptions = CrawlOptions()
