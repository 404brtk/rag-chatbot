from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import Conversation, Document, Message, UserApiKey

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


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "provider",
            "model",
            "usage",
            "meta",
            "created_at",
        ]
        read_only_fields = ["id", "provider", "model", "usage", "meta", "created_at"]


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
        fields = ["id", "filename", "content_type", "created_at"]
        read_only_fields = ["id", "filename", "content_type", "created_at"]
