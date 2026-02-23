from enum import StrEnum


class TaskState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceMethod(StrEnum):
    LLMS_TXT = "llms_txt"
    GITHUB_RAW = "github_raw"
    SITEMAP_CRAWL = "sitemap_crawl"
    FULL_CRAWL = "full_crawl"
