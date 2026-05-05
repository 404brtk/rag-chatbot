from rest_framework.pagination import CursorPagination


class ConversationCursorPagination(CursorPagination):
    ordering = "-last_message_at"


class MessageCursorPagination(CursorPagination):
    ordering = "created_at"
