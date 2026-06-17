from collections import OrderedDict
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class ConversationCursorPagination(CursorPagination):
    ordering = "-last_message_at"
    page_size = 20

    def paginate_queryset(self, queryset, request, view=None):
        self.total_count = queryset.count()
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("count", getattr(self, "total_count", None)),
                    ("results", data),
                ]
            )
        )


class MessageCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 50
