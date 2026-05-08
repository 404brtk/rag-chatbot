from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Conversation, Message


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("email", "is_staff", "is_active", "date_joined")
    search_fields = ("email",)
    ordering = ("email",)


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
