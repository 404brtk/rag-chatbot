from rest_framework.pagination import CursorPagination


class DocumentCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20


class GetDocsJobCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20
