import logging
import httpx
from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone
from django.db import transaction

from .models import GetDocsJob, Document
from .get_docs_client import GetDocsClient
from .document_service import DocumentService

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3.0  # wait 3 seconds between each poll to the microservice
MAX_ATTEMPTS = 200  # give up after 200 polls (=10min)
MAX_CONSECUTIVE_FAILURES = 5  # give up after 5 failed http calls in a row


def _fail_job(job: GetDocsJob, error_message: str):
    logger.error(f"Failing job {job.id}: {error_message}")
    job.status = GetDocsJob.Status.FAILED
    job.error_message = error_message
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_message", "completed_at"])


def _process_pages(
    get_docs_job: GetDocsJob,
    result: dict,
    pages_fetched: int,
    pages_total: int | None,
) -> None:
    pages = result.get("pages", [])
    logger.debug(
        f"GetDocs job {get_docs_job.job_id} completed. Consolidating {len(pages)} pages..."
    )

    combined_markdown_parts = []
    pages_meta = []

    for page in pages:
        url = page.get("url")
        title = page.get("title", "Untitled Section")
        content = page.get("content")

        if not content or not content.strip():
            logger.debug(f"Skipping empty page content for url: {url}")
            continue

        header_block = f"# {title}\n*Source: [{url}]({url})*\n\n"
        combined_markdown_parts.append(header_block + content.strip())
        pages_meta.append({"title": title, "url": url})

    if not combined_markdown_parts:
        _fail_job(get_docs_job, "No valid page content retrieved from microservice.")
        return

    full_raw_text = "\n\n---\n\n".join(combined_markdown_parts)

    root_target = get_docs_job.github_repo or get_docs_job.url or "Documentation Set"
    filename = f"Docs: {root_target}"
    if len(filename) > 255:
        filename = filename[:252] + "..."

    document_service = DocumentService()
    try:
        with transaction.atomic():
            doc = document_service.process_text(
                user=get_docs_job.user,
                raw_text=full_raw_text,
                content_type="text/markdown",
                filename=filename,
                language=get_docs_job.language,
                source_url=get_docs_job.url,
            )
            doc.meta["pages_count"] = len(pages_meta)
            doc.meta["pages"] = pages_meta
            doc.save(update_fields=["meta"])

        process_document_embedding_task.delay(doc.id)
    except Exception as process_err:
        logger.error(f"Failed to process consolidated document: {process_err}")
        _fail_job(
            get_docs_job,
            f"Failed to process consolidated document: {str(process_err)}",
        )
        return

    get_docs_job.status = GetDocsJob.Status.COMPLETED
    get_docs_job.pages_fetched = pages_fetched
    get_docs_job.pages_total = pages_total
    get_docs_job.source_method = result.get("source_method")
    get_docs_job.completed_at = timezone.now()
    get_docs_job.error_message = None

    get_docs_job.save(
        update_fields=[
            "status",
            "pages_fetched",
            "pages_total",
            "source_method",
            "completed_at",
            "error_message",
        ]
    )
    logger.debug(f"GetDocs job {get_docs_job.id} successfully marked as completed.")


@shared_task(bind=True, max_retries=None)
def poll_get_docs_job(
    self,
    get_docs_job_id: str,
    attempt: int = 1,
    consecutive_failures: int = 0,
) -> None:
    try:
        get_docs_job = GetDocsJob.objects.get(id=get_docs_job_id)

        if get_docs_job.status in (
            GetDocsJob.Status.COMPLETED,
            GetDocsJob.Status.FAILED,
        ):
            return

        if attempt > MAX_ATTEMPTS:
            _fail_job(get_docs_job, "Polling timed out after 10 minutes.")
            return

        client = GetDocsClient()

        try:
            result = client.get_job_status(get_docs_job.job_id)
            consecutive_failures = 0
        except httpx.HTTPError as e:
            consecutive_failures += 1
            logger.warning(
                f"Failed to poll microservice (Attempt {consecutive_failures}/{MAX_CONSECUTIVE_FAILURES}): {e}"
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                _fail_job(
                    get_docs_job,
                    f"Microservice unreachable after multiple attempts: {str(e)}",
                )
                return

            self.retry(
                args=[get_docs_job_id],
                kwargs={
                    "attempt": attempt + 1,
                    "consecutive_failures": consecutive_failures,
                },
                countdown=POLL_INTERVAL,
            )
            return

        status = result.get("status")

        if not status or status not in GetDocsJob.Status.values:
            logger.warning(
                f"Invalid or missing status '{status}' for job {get_docs_job.job_id}."
            )
            status = get_docs_job.status

        progress = result.get("progress") or {}
        pages_fetched = progress.get("pages_fetched", 0)
        pages_total = progress.get("pages_total")

        if status == GetDocsJob.Status.COMPLETED:
            _process_pages(get_docs_job, result, pages_fetched, pages_total)
            return

        if status == GetDocsJob.Status.FAILED:
            _fail_job(get_docs_job, "Job failed in microservice.")
            return

        get_docs_job.status = status
        get_docs_job.pages_fetched = pages_fetched
        get_docs_job.pages_total = pages_total
        get_docs_job.save(update_fields=["status", "pages_fetched", "pages_total"])

        self.retry(
            args=[get_docs_job_id],
            kwargs={"attempt": attempt + 1, "consecutive_failures": 0},
            countdown=POLL_INTERVAL,
        )

    except GetDocsJob.DoesNotExist:
        logger.warning(
            f"GetDocs job {get_docs_job_id} not found in DB. Exiting worker."
        )
    except Retry:
        raise
    except Exception as e:
        logger.exception(f"Unexpected task failure: {e}")
        try:
            get_docs_job = GetDocsJob.objects.get(id=get_docs_job_id)
            _fail_job(get_docs_job, f"Unexpected task failure: {str(e)}")
        except GetDocsJob.DoesNotExist:
            pass


@shared_task
def process_document_embedding_task(document_id: str) -> None:
    try:
        document = Document.objects.get(id=document_id)
        document.status = Document.Status.IN_PROGRESS
        document.save(update_fields=["status"])

        service = DocumentService()
        parents_data, meta = service._chunk_for_content_type(
            document.raw_text, document.content_type
        )
        if meta:
            document.meta = meta
            document.save(update_fields=["meta"])

        service._create_document_chunks(document, parents_data)

        document.status = Document.Status.COMPLETED
        document.error_message = None
        document.save(update_fields=["status", "error_message"])

    except Document.DoesNotExist:
        logger.warning(f"Document {document_id} not found. Exiting worker.")
    except Exception as e:
        logger.exception(f"Failed to process embedding for document {document_id}: {e}")
        try:
            document = Document.objects.get(id=document_id)
            document.status = Document.Status.FAILED
            document.error_message = str(e)
            document.save(update_fields=["status", "error_message"])
        except Document.DoesNotExist:
            pass
        raise
