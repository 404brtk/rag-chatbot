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
    SINGLE_PAGE = "single_page"


class ContentSignal(StrEnum):
    """Check https://contentsignals.org/"""

    SEARCH = "search"
    """Building a search index and providing search results
    (e.g., returning hyperlinks and short excerpts from your website's contents).
    Search does not include providing AI-generated search summaries."""

    AI_INPUT = "ai-input"
    """
    Inputting content into one or more AI models
    (e.g., retrieval augmented generation, grounding, or other real-time
    taking of content for generative AI search answers).
    """

    AI_TRAIN = "ai-train"
    """
    Training or fine-tuning AI models.
    """
