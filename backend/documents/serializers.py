from rest_framework import serializers
from .models import Document, GetDocsJob


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "filename",
            "content_type",
            "language",
            "source_url",
            "status",
            "error_message",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "filename",
            "content_type",
            "source_url",
            "status",
            "error_message",
            "created_at",
        ]


class GetDocsJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = GetDocsJob
        fields = [
            "id",
            "job_id",
            "url",
            "github_repo",
            "status",
            "language",
            "pages_fetched",
            "pages_total",
            "source_method",
            "max_pages",
            "max_depth",
            "delay_seconds",
            "timeout",
            "skip_llms_full",
            "fair_use",
            "created_at",
            "completed_at",
            "error_message",
        ]
        read_only_fields = [
            "id",
            "job_id",
            "status",
            "pages_fetched",
            "pages_total",
            "source_method",
            "created_at",
            "completed_at",
            "error_message",
        ]

    def validate(self, attrs):
        if not attrs.get("url") and not attrs.get("github_repo"):
            raise serializers.ValidationError(
                "Either 'url' or 'github_repo' must be provided."
            )
        return attrs
