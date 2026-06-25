from django.contrib import admin
from .models import Document, DocumentChunk, GetDocsJob


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "user",
        "content_type",
        "language",
        "source_url",
        "status",
        "error_message",
        "created_at",
    )
    list_filter = ("status", "content_type", "language")
    search_fields = ("filename", "source_url", "user__email")
    list_select_related = ("user",)
    ordering = ("-created_at",)
    exclude = ("raw_text",)


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "word_count", "content_preview")
    search_fields = ("content",)
    list_select_related = ("document",)
    ordering = ("document", "chunk_index")
    exclude = ("embedding", "search_vector")

    def content_preview(self, obj):
        return obj.content[:100]

    content_preview.short_description = "Content"


@admin.register(GetDocsJob)
class GetDocsJobAdmin(admin.ModelAdmin):
    list_display = (
        "job_id",
        "user",
        "status",
        "url",
        "github_repo",
        "source_method",
        "pages_fetched",
        "pages_total",
        "error_message",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "source_method", "language")
    search_fields = ("job_id", "url", "github_repo", "user__email")
    list_select_related = ("user",)
    ordering = ("-created_at",)
