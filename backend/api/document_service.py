import logging
from dataclasses import dataclass

from django.conf import settings
from pgvector.django import CosineDistance

from .chunking import (
    SUPPORTED_CONTENT_TYPES,
    chunk_markdown,
    chunk_text,
    extract_text,
)
from .embeddings import EmbeddingService
from .models import Document, DocumentChunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_content: str
    document_id: str
    document_filename: str
    chunk_index: int
    distance: float


class DocumentService:
    def __init__(self):
        self.embedding_service = EmbeddingService.get_instance()

    def _chunk_for_content_type(
        self, raw_text: str, content_type: str
    ) -> tuple[list[str], dict]:
        if content_type in ("text/markdown", "application/pdf"):
            return chunk_markdown(raw_text)
        return chunk_text(raw_text), {}

    def _create_document_chunks(self, document: Document, chunks: list[str]) -> None:
        if not chunks:
            return
        embeddings = self.embedding_service.embed_texts(chunks)
        chunk_objects = [
            DocumentChunk(
                document=document,
                content=chunk_content,
                chunk_index=i,
                embedding=embedding,
            )
            for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings))
        ]
        DocumentChunk.objects.bulk_create(chunk_objects)

    def process_upload(self, user, file) -> Document:
        content_type = file.content_type or ""
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported file type: {content_type}. "
                f"Supported: {', '.join(sorted(SUPPORTED_CONTENT_TYPES))}"
            )

        if file.size > settings.FILE_UPLOAD_MAX_SIZE:
            max_mb = settings.FILE_UPLOAD_MAX_SIZE / (1024 * 1024)
            raise ValueError(f"File too large. Maximum size: {max_mb:.0f}MB")

        file_bytes = file.read()
        raw_text = extract_text(file_bytes, content_type)

        if not raw_text.strip():
            raise ValueError("Could not extract any text from the file.")

        chunks, meta = self._chunk_for_content_type(raw_text, content_type)

        document = Document.objects.create(
            user=user,
            filename=file.name,
            content_type=content_type,
            raw_text=raw_text,
            meta=meta,
        )

        self._create_document_chunks(document, chunks)

        return document

    def process_text(
        self, user, raw_text: str, content_type: str, filename: str
    ) -> Document:
        if content_type not in ("text/plain", "text/markdown"):
            raise ValueError(
                f"Unsupported content type for text paste: {content_type}. "
                f"Supported: text/plain, text/markdown"
            )

        if not raw_text.strip():
            raise ValueError("Content cannot be empty.")

        chunks, meta = self._chunk_for_content_type(raw_text, content_type)

        document = Document.objects.create(
            user=user,
            filename=filename,
            content_type=content_type,
            raw_text=raw_text,
            meta=meta,
        )

        self._create_document_chunks(document, chunks)

        return document

    def search(
        self,
        user,
        query: str,
        *,
        document_ids: list[str] | None = None,
    ) -> list[SearchResult]:

        query_embedding = self.embedding_service.embed_query(query)

        qs = DocumentChunk.objects.filter(document__user=user)

        logger.debug(f"Chunks for user: {qs.count()}")

        if document_ids:
            qs = qs.filter(document_id__in=document_ids)

        annotated = qs.annotate(distance=CosineDistance("embedding", query_embedding))
        logger.debug(
            f"Threshold: {settings.RAG_SIMILARITY_THRESHOLD:.4f}, "
            f"top_k: {settings.RAG_TOP_K}"
        )
        logger.debug(
            f"Distances (first 20): "
            f"{list(annotated.values_list('distance', 'content')[:20])}"
        )

        if settings.RAG_SIMILARITY_THRESHOLD < 1.0:
            qs_filtered = annotated.filter(
                distance__lt=settings.RAG_SIMILARITY_THRESHOLD
            )
        else:
            qs_filtered = annotated

        results = list(
            qs_filtered.select_related("document").order_by("distance")[
                : settings.RAG_TOP_K
            ]
        )
        logger.debug(f"After threshold filter: {len(results)} results")

        return [
            SearchResult(
                chunk_content=chunk.content,
                document_id=str(chunk.document_id),
                document_filename=chunk.document.filename,
                chunk_index=chunk.chunk_index,
                distance=chunk.distance,
            )
            for chunk in results
        ]
