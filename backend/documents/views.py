import logging
import httpx

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, viewsets, status
from rest_framework.response import Response

from core.exceptions import TemporaryProviderError
from .models import Document, DocumentLanguage, GetDocsJob
from .pagination import DocumentCursorPagination, GetDocsJobCursorPagination
from .serializers import DocumentSerializer, GetDocsJobSerializer
from .document_service import DocumentService
from .get_docs_client import GetDocsClient
from .tasks import poll_get_docs_job, process_document_embedding_task

logger = logging.getLogger(__name__)


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
            with transaction.atomic():
                document = service.process_upload(
                    user=request.user, file=file, language=language
                )

                def queue_task():
                    try:
                        process_document_embedding_task.delay(document.id)
                    except Exception as queue_err:
                        logger.exception(
                            f"Failed to queue Celery task for document {document.id}"
                        )
                        Document.objects.filter(id=document.id).update(
                            status=Document.Status.FAILED,
                            error_message=f"Broker queue error: {str(queue_err)}",
                        )

                transaction.on_commit(queue_task)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(document)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

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
            with transaction.atomic():
                document = service.process_text(
                    user=request.user,
                    raw_text=str(content),
                    content_type=content_type,
                    filename=filename,
                    language=language,
                )

                def queue_task():
                    try:
                        process_document_embedding_task.delay(document.id)
                    except Exception as queue_err:
                        logger.exception(
                            f"Failed to queue Celery task for document {document.id}"
                        )
                        Document.objects.filter(id=document.id).update(
                            status=Document.Status.FAILED,
                            error_message=f"Broker queue error: {str(queue_err)}",
                        )

                transaction.on_commit(queue_task)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(document)
        return Response(serializer.data, status=status.HTTP_202_ACCEPTED)

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
