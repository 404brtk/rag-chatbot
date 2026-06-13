from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, UserApiKey


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
