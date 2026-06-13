from django.conf import settings
from rest_framework import serializers
from .models import Conversation, Message, MessageAttachment


class MessageAttachmentSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source="file_id")
    mimeType = serializers.CharField(source="mime_type")
    url = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()

    class Meta:
        model = MessageAttachment
        fields = ["id", "name", "size", "mimeType", "url", "kind"]

    def get_url(self, obj):
        request = self.context.get("request")
        url_path = f"{settings.MEDIA_URL}{obj.saved_path}"
        if request is not None:
            return request.build_absolute_uri(url_path)
        return url_path

    def get_kind(self, obj):
        if obj.mime_type.startswith("image/"):
            return "image"
        return "document"


class MessageSerializer(serializers.ModelSerializer):
    attachments = MessageAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "provider",
            "model",
            "raw_question",
            "context",
            "usage",
            "compacted",
            "truncated",
            "is_compaction_summary",
            "created_at",
            "attachments",
        ]
        read_only_fields = [
            "id",
            "provider",
            "model",
            "raw_question",
            "context",
            "usage",
            "compacted",
            "truncated",
            "is_compaction_summary",
            "created_at",
            "attachments",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "status", "created_at", "last_message_at"]
        read_only_fields = ["id", "status", "created_at", "last_message_at"]
