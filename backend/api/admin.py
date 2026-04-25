from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Conversation, Message

admin.site.register(User, UserAdmin)

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'created_at')
    list_filter = ('user',)
    search_fields = ('title', 'user__username')
    list_select_related = ('user',)
    ordering = ('-created_at',)

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('content',)
    list_select_related = ('conversation',)
    ordering = ('-created_at',)

