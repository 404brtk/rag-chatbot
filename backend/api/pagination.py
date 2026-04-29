from rest_framework.pagination import CursorPagination


class CreatedAtCursorPagination(CursorPagination):
    ordering = "-created_at"


class MessageCursorPagination(CreatedAtCursorPagination):
    ordering = "created_at"
