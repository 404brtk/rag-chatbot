from django.conf import settings
from django.db import models
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from pgvector.django import HnswIndex, VectorField
from core.models import UUIDModel


class DocumentLanguage(models.TextChoices):
    ENGLISH = "english", "English"
    POLISH = "polish", "Polish"

    @classmethod
    def get_pg_regconfig(cls, language: str) -> str:
        mapping = {
            cls.ENGLISH: "english",
            cls.POLISH: "polish",
        }
        return mapping.get(language, "simple")


class Document(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    raw_text = models.TextField()
    language = models.CharField(
        max_length=16,
        choices=DocumentLanguage.choices,
        default=DocumentLanguage.ENGLISH,
    )
    meta = models.JSONField(default=dict, blank=True)
    source_url = models.URLField(max_length=2000, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.filename


class DocumentChunk(UUIDModel):
    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="chunks"
    )
    content = models.TextField()
    chunk_index = models.PositiveIntegerField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIMENSIONS)
    search_vector = SearchVectorField(null=True)
    word_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["chunk_index"]
        indexes = [
            models.Index(fields=["document", "chunk_index"]),
            HnswIndex(
                name="chunk_embedding_idx",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(fields=["search_vector"], name="chunk_search_vector_idx"),
        ]

    def __str__(self):
        return f"{self.document.filename} chunk {self.chunk_index}"


class GetDocsJob(UUIDModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="get_docs_jobs",
    )
    job_id = models.CharField(max_length=255, unique=True, null=True)
    url = models.URLField(max_length=1000, null=True, blank=True)
    github_repo = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    language = models.CharField(
        max_length=16,
        choices=DocumentLanguage.choices,
        default=DocumentLanguage.ENGLISH,
    )
    pages_fetched = models.PositiveIntegerField(default=0)
    pages_total = models.PositiveIntegerField(null=True, blank=True)
    max_pages = models.PositiveIntegerField(default=150)
    max_depth = models.PositiveIntegerField(default=3)
    delay_seconds = models.FloatField(default=1.5)
    timeout = models.FloatField(default=15.0)
    skip_llms_full = models.BooleanField(default=False)
    fair_use = models.BooleanField(default=True)
    source_method = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"GetDocsJob {self.job_id} ({self.status})"
