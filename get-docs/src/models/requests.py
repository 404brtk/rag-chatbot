from pydantic import BaseModel, HttpUrl, model_validator


class GetDocsRequest(BaseModel):
    url: HttpUrl | None = None
    github_repo: str | None = None
    github_token: str | None = None
    max_pages: int = 300
    max_depth: int = 3
    delay_seconds: float = 1.5
    timeout: float = 15.0
    skip_llms_full: bool = False

    @model_validator(mode="after")
    def at_least_one_source(self):
        if not self.url and not self.github_repo:
            raise ValueError("At least one of 'url' or 'github_repo' must be provided")
        return self
