from rest_framework import generics, mixins, permissions, viewsets
from django.shortcuts import get_object_or_404
from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer, RegisterSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MessageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MessageSerializer

    def get_conversation(self):
        return get_object_or_404(
            Conversation, pk=self.kwargs["conversation_pk"], user=self.request.user
        )

    def get_queryset(self):
        return Message.objects.filter(
            conversation_id=self.kwargs["conversation_pk"],
            conversation__user=self.request.user,
        ).order_by("created_at")

    def perform_create(self, serializer):
        serializer.save(conversation=self.get_conversation())
