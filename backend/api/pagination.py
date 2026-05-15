from rest_framework.pagination import CursorPagination


class ConversationCursorPagination(CursorPagination):
    ordering = "-last_message_at"
    page_size = 20


class MessageCursorPagination(CursorPagination):
    ordering = "created_at"
    page_size = 50


class DocumentCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20
