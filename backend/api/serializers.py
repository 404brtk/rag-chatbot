from rest_framework import serializers
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    conversation = serializers.PrimaryKeyRelatedField(
        queryset=Conversation.objects.all(), write_only=True
    )

    class Meta:
        model = Message
        fields = ["id", "conversation", "role", "content", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_conversation(self, value):
        if value.user != self.context["request"].user:
            raise serializers.ValidationError("Invalid conversation.")
        return value


class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "messages"]
        read_only_fields = ["id", "created_at"]
