import asyncio
import json
import logging
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, aget_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions, mixins, permissions, viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication

from core.exceptions import (
    InvalidInputError,
    MissingApiKeyError,
    TemporaryProviderError,
    PermanentProviderError,
)
from .models import Conversation
from .attachments import save_local_attachment
from .pagination import ConversationCursorPagination, MessageCursorPagination
from .serializers import ConversationSerializer, MessageSerializer
from .chat_service import ChatService
from .llm_config import LLMConfig, validate_llm_config

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are an expert Senior Developer and AI Coding Assistant. You are brutally concise, direct, and avoid unnecessary apologies, fluff, or 'As an AI' disclaimers.
You may be provided with reference documents in the user's message under <CONTEXT> tags. Follow these strict instructions to answer:

1. **Contextual & Hybrid Questions**: If <CONTEXT> tags are present, analyze them. Do not force yourself to rely solely on the context if it is incomplete, poor, or irrelevant to the actual prompt (e.g., if the user asks for a code example, but the context only contains a high-level text description). Use your internal knowledge base to provide a fully functional, comprehensive answer.
* **CRITICAL CITATION RULE**: All citation labels MUST be placed together on a single, new line at the very end of your entire response, separated by a single space (e.g., `[1] [2] [4]`). Never split them, never put them on separate lines, and never combine them into brackets like `[1, 2]` or `[1-2]`.
* ONLY append citation labels for the specific documents that actually contributed useful facts to your response.
* If the provided context is completely irrelevant or useless for the user's specific request, answer entirely from your own knowledge and do not include any citations at all.
* DO NOT place any citation brackets (such as [1], [2]) inline or inside sentences.
2. **General or Fallback Questions**: If no <CONTEXT> is provided, answer naturally using your own internal knowledge base and chat history. Do not include any document citations.
3. **Format & Tone**: Always format responses using Markdown. Whenever you write code, wrap it in a markdown code block with the correct language tag.
4. **Language Matching**: Always respond in the same language in which the user's question was asked. If the user asks in Polish, write your entire response in Polish, translating relevant facts from English reference documents where necessary.

### Examples of Correct Formatting:

#### Example 1 (Answer fully from context - Single Source):
<CONTEXT>
[2] Python was created by Guido van Rossum and first released in 1991.
</CONTEXT>
<QUESTION>
Who created Python?
</QUESTION>
Response:
Python was created by Guido van Rossum.
[2]

#### Example 2 (Answer fully from context - Multi-source / All citations strictly in one line at the very end):
<CONTEXT>
[1] Python was released in 1991.
[3] Python is distributed under the open-source PSF License.
</CONTEXT>
<QUESTION>
When was Python released and what is its license?
</QUESTION>
Response:
Python was released in 1991 and is distributed under the PSF License.
[1] [3]

#### Example 3 (Context insufficient - Context provided only a definition, user wants code):
<CONTEXT>
[1] Redis is an in-memory data store used as a database and cache.
</CONTEXT>
<QUESTION>
Give me a Python code example to connect to Redis.
</QUESTION>
Response:
Redis is an in-memory data store. To connect to it using Python, install redis and use the following code:

```python
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
r.set('foo', 'bar')
```
[1]

#### Example 4 (Context completely irrelevant - Ignored, NO citations at all):
<CONTEXT>
[1] Docker allows you to package applications into containers.
</CONTEXT>
<QUESTION>
How do I revert the last commit in Git?
</QUESTION>
Response:
To revert the last commit in Git while keeping your local changes, run:
```bash
git reset --soft HEAD~1
```

#### Example 5 (General Knowledge / No Context provided):
Question:
What is the capital of Poland?
Response:
The capital of Poland is Warsaw."""


def _sse_error(message: str, code: str | None = None) -> list[str]:
    payload = {"type": "error", "message": message}
    if code:
        payload["code"] = code
    return [f"data: {json.dumps(payload)}\n\n"]


def validate_attachments(attachments: Any) -> str | None:
    if attachments is None:
        return None
    if not isinstance(attachments, list):
        return "Attachments must be a list."
    for idx, att in enumerate(attachments):
        if not isinstance(att, dict):
            return f"Attachment at index {idx} is not a dictionary."
        for field in ("id", "name", "size", "mimeType"):
            if field not in att:
                return f"Attachment at index {idx} is missing required field '{field}'."
    return None


class HealthView(View):
    async def get(self, request):
        try:
            await Conversation.objects.none().aexists()
        except Exception:
            logger.exception("Health check failed")
            return JsonResponse(
                {"status": "unhealthy"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return JsonResponse({"status": "ok", "database": "connected"})


class ModelListView(View):
    async def get(self, request):
        data = await ChatService.get_available_models()
        return JsonResponse(data)


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

        document_ids = request.data.get("document_ids")
        attachments = request.data.get("attachments", [])

        att_error = validate_attachments(attachments)
        if att_error:
            return Response(
                {"attachments": [att_error]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if document_ids is not None:
            if not isinstance(document_ids, list):
                return Response(
                    {"document_ids": ["Must be a list of document UUIDs."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        validation_error = validate_llm_config(request.data)
        if validation_error:
            return Response(validation_error, status=status.HTTP_400_BAD_REQUEST)

        config = LLMConfig(
            provider=request.data["provider"],
            model=request.data["model"],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            compaction_provider=(request.data.get("compaction_provider") or "").strip()
            or request.data["provider"],
            compaction_model=(request.data.get("compaction_model") or "").strip()
            or request.data["model"],
            max_input_tokens=request.data.get("max_input_tokens", 12_000),
            compaction_threshold=request.data.get("compaction_threshold", 0.8),
            compaction_enabled=request.data.get("compaction_enabled", False),
        )
        service = ChatService()

        try:
            result = async_to_sync(service.generate_reply)(
                user=request.user,
                session_id=str(conversation.id),
                user_text=user_text,
                config=config,
                document_ids=document_ids,
                attachments=attachments,
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
            conversation.title = ChatService._compute_title(user_text)
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


@method_decorator(csrf_exempt, name="dispatch")
class MessageStreamView(View):
    async def post(self, request, conversation_pk):
        auth = JWTAuthentication()
        try:
            auth_result = await sync_to_async(auth.authenticate)(request)
            if auth_result is None:
                return StreamingHttpResponse(
                    _sse_error("Authentication required", "auth_required"),
                    content_type="text/event-stream",
                    status=401,
                )
            request.user = auth_result[0]
        except exceptions.AuthenticationFailed as e:
            return StreamingHttpResponse(
                _sse_error(str(e), "auth_failed"),
                content_type="text/event-stream",
                status=401,
            )

        conversation = await aget_object_or_404(
            Conversation, pk=conversation_pk, user=request.user
        )

        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return StreamingHttpResponse(
                _sse_error("Invalid JSON body", "invalid_json"),
                content_type="text/event-stream",
                status=400,
            )

        user_text = body.get("content")
        if not user_text:
            return StreamingHttpResponse(
                _sse_error("content is required", "missing_content"),
                content_type="text/event-stream",
                status=400,
            )

        document_ids = body.get("document_ids")
        if document_ids is not None and not isinstance(document_ids, list):
            return StreamingHttpResponse(
                _sse_error("document_ids must be a list", "invalid_document_ids"),
                content_type="text/event-stream",
                status=400,
            )

        attachments = body.get("attachments", [])

        att_error = validate_attachments(attachments)
        if att_error:
            return StreamingHttpResponse(
                _sse_error(att_error, "invalid_attachments"),
                content_type="text/event-stream",
                status=400,
            )

        validation_error = validate_llm_config(body)
        if validation_error:
            return StreamingHttpResponse(
                _sse_error(validation_error["error"], validation_error.get("code")),
                content_type="text/event-stream",
                status=400,
            )

        config = LLMConfig(
            provider=body["provider"],
            model=body["model"],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            compaction_provider=(body.get("compaction_provider") or "").strip()
            or body["provider"],
            compaction_model=(body.get("compaction_model") or "").strip()
            or body["model"],
            max_input_tokens=body.get("max_input_tokens", 12_000),
            compaction_threshold=body.get("compaction_threshold", 0.8),
            compaction_enabled=body.get("compaction_enabled", False),
        )
        service = ChatService()

        async def event_generator():
            try:
                async for event in service.generate_reply_stream(
                    user=request.user,
                    session_id=str(conversation.id),
                    user_text=user_text,
                    config=config,
                    document_ids=document_ids,
                    attachments=attachments,
                ):
                    payload = {"type": event.type}
                    if event.type == "token":
                        payload["content"] = event.content
                    elif event.type == "done":
                        payload["message_id"] = event.message_id
                        payload["title"] = event.title
                        payload["usage"] = event.usage
                        payload["provider"] = event.provider
                        payload["model"] = event.model
                        if event.sent_messages:
                            payload["sent_messages"] = event.sent_messages
                    elif event.type == "compaction_done":
                        payload["message_id"] = event.message_id
                        if event.usage:
                            payload["usage"] = event.usage
                    elif event.type == "error":
                        payload["message"] = event.error_message
                        if event.error_code:
                            payload["code"] = event.error_code
                    yield f"data: {json.dumps(payload)}\n\n"
            except (TemporaryProviderError, PermanentProviderError) as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            except asyncio.CancelledError:
                raise

        response = StreamingHttpResponse(
            event_generator(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
        return response


class AttachmentUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if "file" not in request.FILES:
            return Response(
                {"error": "No file uploaded"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        attachment_data = save_local_attachment(request.FILES["file"])
        url = request.build_absolute_uri(
            f"{settings.MEDIA_URL}{attachment_data['saved_path']}"
        )

        return Response(
            {
                "id": attachment_data["id"],
                "name": attachment_data["name"],
                "size": attachment_data["size"],
                "mimeType": attachment_data["mimeType"],
                "url": url,
            },
            status=status.HTTP_201_CREATED,
        )
