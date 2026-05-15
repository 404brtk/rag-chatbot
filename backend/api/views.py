import logging

from django.db import connection
from rest_framework import generics, mixins, permissions, viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .document_service import DocumentService
from .models import Conversation
from .pagination import (
    ConversationCursorPagination,
    MessageCursorPagination,
    DocumentCursorPagination,
)
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    DocumentSerializer,
    RegisterSerializer,
    UserApiKeySerializer,
)
from .chat_service import (
    LLMConfig,
    ChatService,
    InvalidInputError,
    MissingApiKeyError,
    TemporaryProviderError,
    PermanentProviderError,
)


class HealthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            logger = logging.getLogger(__name__)
            logger.exception("Health check failed")
            return Response(
                {"status": "unhealthy"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({"status": "ok", "database": "connected"})


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    pagination_class = ConversationCursorPagination
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return self.request.user.conversations.all()

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
        conversation = self.get_conversation()
        return conversation.messages.all()

    def create(self, request, *args, **kwargs):
        conversation = self.get_conversation()
        user_text = request.data.get("content")

        if not user_text:
            return Response(
                {"content": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        provider = request.data.get("provider", "openai")
        model_name = request.data.get("model", "gpt-5.4-mini")
        document_ids = request.data.get("document_ids")

        if document_ids is not None:
            if not isinstance(document_ids, list):
                return Response(
                    {"document_ids": ["Must be a list of document UUIDs."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        config = LLMConfig(
            provider=provider,
            model=model_name,
            system_prompt=(
                "You are an expert Senior Developer and AI Coding Assistant. "
                "You will be provided with reference documents in the user's message. "
                "Use them to answer when relevant; ignore them if they are not relevant. "
                "When you draw on information from the provided documents, cite the "
                "relevant chunks using the [1], [2], etc. notation matching their labels. "
                "Use citations to attribute knowledge, not as verbatim quotes. "
                "Always format your responses using Markdown. "
                "Whenever you write code, wrap it in a markdown code block with the correct language tag. "
                "Be brutally concise, direct, and avoid unnecessary apologies, fluff, or 'As an AI' disclaimers. "
                "If you do not know the answer, explicitly state 'I do not know'. "
                "Do not hallucinate."
            ),
        )

        service = ChatService()

        try:
            result = service.generate_reply(
                user=request.user,
                session_id=str(conversation.id),
                user_text=user_text,
                config=config,
                document_ids=document_ids,
            )
        except MissingApiKeyError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_403_FORBIDDEN,
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

        if not conversation.title:
            stripped = user_text.strip()
            if len(stripped) <= 50:
                conversation.title = stripped
            else:
                truncated = stripped[:50]
                if " " in truncated:
                    truncated = truncated.rsplit(" ", 1)[0]
                conversation.title = truncated + "..."
            conversation.save(update_fields=["title"])

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


class UserApiKeyViewSet(viewsets.ModelViewSet):
    serializer_class = UserApiKeySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return self.request.user.api_keys.all()

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class DocumentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DocumentSerializer
    pagination_class = DocumentCursorPagination

    def get_queryset(self):
        return self.request.user.documents.all()

    def _handle_file_upload(self, request):
        file = request.FILES.get("file")
        if not file:
            return Response(
                {"file": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = DocumentService()
        try:
            document = service.process_upload(user=request.user, file=file)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(document)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _handle_text_paste(self, request):
        content = request.data.get("content")
        if not content or not str(content).strip():
            return Response(
                {"content": ["This field is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        content_type = request.data.get("content_type", "text/plain")
        if content_type not in ("text/plain", "text/markdown"):
            return Response(
                {"content_type": ["Must be text/plain or text/markdown."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        filename = request.data.get("filename", "pasted-text.txt")

        service = DocumentService()
        try:
            document = service.process_text(
                user=request.user,
                raw_text=str(content),
                content_type=content_type,
                filename=filename,
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(document)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def create(self, request, *args, **kwargs):
        if "file" in request.FILES:
            return self._handle_file_upload(request)
        return self._handle_text_paste(request)
