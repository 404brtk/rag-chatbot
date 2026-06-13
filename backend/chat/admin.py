from django.contrib import admin
from .models import Conversation, Message, MessageAttachment


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "last_message_at", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "user__email")
    list_select_related = ("user",)
    ordering = ("-last_message_at",)


class MessageAttachmentInline(admin.TabularInline):
    model = MessageAttachment
    extra = 0


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "conversation",
        "role",
        "provider",
        "model",
        "compacted",
        "truncated",
        "is_compaction_summary",
        "created_at",
    )
    list_filter = (
        "role",
        "provider",
        "compacted",
        "truncated",
        "is_compaction_summary",
    )
    search_fields = ("content", "raw_question")
    list_select_related = ("conversation",)
    ordering = ("-created_at",)
    inlines = [MessageAttachmentInline]


@admin.register(MessageAttachment)
class MessageAttachmentAdmin(admin.ModelAdmin):
    list_display = ("name", "message", "file_id", "mime_type", "size", "created_at")
    list_filter = ("mime_type",)
    search_fields = ("name", "file_id", "message__content")
    list_select_related = ("message",)
    ordering = ("-created_at",)
