import asyncio
import json
import logging
import httpx

from asgiref.sync import async_to_sync, sync_to_async
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, aget_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import exceptions, generics, mixins, permissions, viewsets, status
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication

from .document_service import DocumentService
from .models import Conversation, DocumentLanguage, GetDocsJob
from .pagination import (
    ConversationCursorPagination,
    MessageCursorPagination,
    DocumentCursorPagination,
    GetDocsJobCursorPagination,
)
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    DocumentSerializer,
    RegisterSerializer,
    UserApiKeySerializer,
    GetDocsJobSerializer,
)
from .chat_service import ChatService
from .get_docs_client import GetDocsClient
from .tasks import poll_get_docs_job
from .llm_config import (
    LLMConfig,
    InvalidInputError,
    MissingApiKeyError,
    TemporaryProviderError,
    PermanentProviderError,
    validate_llm_config,
)

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert Senior Developer and AI Coding Assistant. "
    "You will be provided with reference documents in the user's message. "
    "Use them to answer when relevant; ignore them if they are not relevant. "
    "Attribute facts to reference chunks by listing their labels (e.g., [1], [3]) "
    "together on a single new line at the very end of your response. Do not cite inline, "
    "do not quote verbatim, and never group or combine citations (e.g., do not output '[1, 2]' or '[1-2]'). "
    "Always format your responses using Markdown. "
    "Whenever you write code, wrap it in a markdown code block with the correct language tag. "
    "Be brutally concise, direct, and avoid unnecessary apologies, fluff, or 'As an AI' disclaimers. "
    "If you do not know the answer, explicitly state 'I do not know'. "
    "Do not hallucinate."
)


def _sse_error(message: str, code: str | None = None) -> list[str]:
    payload = {"type": "error", "message": message}
    if code:
        payload["code"] = code
    return [f"data: {json.dumps(payload)}\n\n"]


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


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


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

        language = request.data.get("language", DocumentLanguage.ENGLISH)
        if language not in DocumentLanguage.values:
            return Response(
                {
                    "language": [
                        f"Unsupported. Choose from: {', '.join(DocumentLanguage.values)}"
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = DocumentService()
        try:
            document = service.process_upload(
                user=request.user, file=file, language=language
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TemporaryProviderError as e:
            return Response(
                {
                    "error": f"AI service temporarily unavailable during processing: {str(e)}"
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PermanentProviderError as e:
            return Response(
                {"error": f"AI service permanent error during processing: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
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
        language = request.data.get("language", DocumentLanguage.ENGLISH)
        if language not in DocumentLanguage.values:
            return Response(
                {
                    "language": [
                        f"Unsupported. Choose from: {', '.join(DocumentLanguage.values)}"
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        service = DocumentService()
        try:
            document = service.process_text(
                user=request.user,
                raw_text=str(content),
                content_type=content_type,
                filename=filename,
                language=language,
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except TemporaryProviderError as e:
            return Response(
                {
                    "error": f"AI service temporarily unavailable during processing: {str(e)}"
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except PermanentProviderError as e:
            return Response(
                {"error": f"AI service permanent error during processing: {str(e)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        serializer = self.get_serializer(document)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def create(self, request, *args, **kwargs):
        if "file" in request.FILES:
            return self._handle_file_upload(request)
        return self._handle_text_paste(request)


class GetDocsJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = GetDocsJobSerializer
    pagination_class = GetDocsJobCursorPagination

    def get_queryset(self):
        return self.request.user.get_docs_jobs.all()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client = GetDocsClient()

        try:
            with transaction.atomic():
                get_docs_job = serializer.save(user=request.user)

                try:
                    job_id = client.trigger_get_docs(
                        url=get_docs_job.url,
                        github_repo=get_docs_job.github_repo,
                        max_pages=get_docs_job.max_pages,
                        max_depth=get_docs_job.max_depth,
                        delay_seconds=get_docs_job.delay_seconds,
                        crawl_timeout=get_docs_job.timeout,
                        skip_llms_full=get_docs_job.skip_llms_full,
                        fair_use=get_docs_job.fair_use,
                    )
                except httpx.HTTPStatusError as e:
                    error_msg = f"Failed to trigger job on get-docs microservice: Client error {e.response.status_code}. Response: {e.response.text}"
                    logger.error(error_msg)
                    raise TemporaryProviderError(error_msg)
                except httpx.HTTPError as e:
                    logger.exception("Failed to connect to get-docs microservice")
                    raise TemporaryProviderError(
                        f"Failed to trigger job on get-docs microservice: {str(e)}"
                    )

                get_docs_job.job_id = job_id
                get_docs_job.save(update_fields=["job_id"])

                def queue_task():
                    try:
                        poll_get_docs_job.delay(get_docs_job.id)
                    except Exception as queue_err:
                        logger.exception(
                            f"Failed to queue Celery task for job {get_docs_job.id}"
                        )
                        GetDocsJob.objects.filter(id=get_docs_job.id).update(
                            status=GetDocsJob.Status.FAILED,
                            error_message=f"Broker queue error: {str(queue_err)}",
                            completed_at=timezone.now(),
                        )

                transaction.on_commit(queue_task)

        except TemporaryProviderError as e:
            return Response(
                {"error": str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        response_serializer = self.get_serializer(get_docs_job)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
