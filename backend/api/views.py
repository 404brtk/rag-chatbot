from rest_framework import generics, mixins, permissions, viewsets, status
from django.shortcuts import get_object_or_404
from rest_framework.response import Response

from .models import Conversation, Message
from .pagination import MessageCursorPagination
from .serializers import ConversationSerializer, MessageSerializer, RegisterSerializer
from .services import (
    InvalidInputError,
    TemporaryProviderError,
    PermanentProviderError,
    LLMConfig,
    get_chat_service,
)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MessageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MessageSerializer
    pagination_class = MessageCursorPagination

    def get_conversation(self):
        return get_object_or_404(
            Conversation, pk=self.kwargs["conversation_pk"], user=self.request.user
        )

    def get_queryset(self):
        self.get_conversation()
        return Message.objects.filter(conversation_id=self.kwargs["conversation_pk"])

    def create(self, request, *args, **kwargs):
        conversation = self.get_conversation()
        user_text = request.data.get("content")

        if not user_text:
            return Response(
                {"content": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = LLMConfig(
            provider="openai",
            model="gpt-5.4-mini",
            system_prompt=(
                "You are an expert Senior Developer and AI Coding Assistant. "
                "Always format your responses using Markdown. "
                "Whenever you write code, wrap it in a markdown code block with the correct language tag. "
                "Be brutally concise, direct, and avoid unnecessary apologies, fluff, or 'As an AI' disclaimers. "
                "If you do not know the answer, explicitly state 'I do not know'. "
                "Do not hallucinate."
            ),
        )

        service = get_chat_service()

        try:
            result = service.generate_reply(
                session_id=str(conversation.id),
                user_text=user_text,
                config=config,
            )
        except InvalidInputError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TemporaryProviderError as e:
            return Response(
                {
                    "error": f"AI service temporarily unavailable. Please try again: {str(e)}"
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PermanentProviderError as e:
            return Response(
                {"error": f"AI service encountered a permanent error: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "id": result.assistant_message_id,
                "role": "ai",
                "content": result.text,
                "provider": result.provider,
                "model": result.model,
                "usage": result.usage,
            },
            status=status.HTTP_201_CREATED,
        )
