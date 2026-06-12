from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from rest_framework import serializers
from .models import (
    Conversation,
    Document,
    Message,
    UserApiKey,
    GetDocsJob,
    MessageAttachment,
)

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "password", "password_confirm"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


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


class UserApiKeySerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, source="encrypted_key")
    masked_key = serializers.CharField(read_only=True)

    class Meta:
        model = UserApiKey
        fields = ["id", "provider", "api_key", "masked_key", "created_at", "updated_at"]
        read_only_fields = ["id", "masked_key", "created_at", "updated_at"]

    def validate(self, attrs):
        user = self.context["request"].user
        provider = attrs.get("provider", getattr(self.instance, "provider", None))
        qs = UserApiKey.objects.filter(user=user, provider=provider)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"provider": f"You already have a key for '{provider}'."}
            )
        return attrs


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "filename",
            "content_type",
            "language",
            "source_url",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "filename",
            "content_type",
            "source_url",
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
