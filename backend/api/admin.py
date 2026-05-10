from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Conversation, Document, DocumentChunk, Message, UserApiKey


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("email", "is_staff", "is_active", "date_joined")
    search_fields = ("email",)
    ordering = ("email",)


@admin.register(UserApiKey)
class UserApiKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "masked_key", "created_at", "updated_at")
    list_filter = ("provider",)
    search_fields = ("user__email",)
    list_select_related = ("user",)
    ordering = ("-updated_at",)
    exclude = ("encrypted_key",)

    def masked_key(self, obj):
        return obj.masked_key

    masked_key.short_description = "API Key"


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "status", "last_message_at", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "user__email")
    list_select_related = ("user",)
    ordering = ("-last_message_at",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "provider", "model", "created_at")
    list_filter = ("role", "provider")
    search_fields = ("content",)
    list_select_related = ("conversation",)
    ordering = ("-created_at",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("filename", "user", "content_type", "created_at")
    list_filter = ("content_type",)
    search_fields = ("filename", "user__email")
    list_select_related = ("user",)
    ordering = ("-created_at",)
    exclude = ("raw_text",)


@admin.register(DocumentChunk)
class DocumentChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "content_preview")
    search_fields = ("content",)
    list_select_related = ("document",)
    ordering = ("document", "chunk_index")
    exclude = ("embedding",)

    def content_preview(self, obj):
        return obj.content[:100]

    content_preview.short_description = "Content"
