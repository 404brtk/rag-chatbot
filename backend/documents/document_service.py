import logging
import asyncio
from dataclasses import dataclass
from asgiref.sync import sync_to_async

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db import connection
from django.db.models import Avg, Count
from pgvector.django import CosineDistance

from .chunking import (
    SUPPORTED_CONTENT_TYPES,
    chunk_markdown,
    chunk_text,
    extract_text,
)
from .embeddings import EmbeddingService
from .models import PG_REGCONFIG, Document, DocumentChunk

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_content: str
    document_id: str
    document_filename: str
    chunk_index: int
    score: float


class DocumentService:
    _polish_config_verified = None

    def __init__(self):
        self.embedding_service = EmbeddingService.get_instance()

    @classmethod
    def get_language_config(cls, language: str) -> str:
        if language == "polish":
            if cls._polish_config_verified is None:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'polish');"
                        )
                        exists = cursor.fetchone()[0]
                        cls._polish_config_verified = "polish" if exists else "simple"
                except Exception:
                    return "simple"
            return cls._polish_config_verified
        return PG_REGCONFIG.get(language, "simple")

    def _chunk_for_content_type(
        self, raw_text: str, content_type: str
    ) -> tuple[list[str], dict]:
        if content_type in ("text/markdown", "application/pdf"):
            return chunk_markdown(raw_text)
        return chunk_text(raw_text), {}

    def _create_document_chunks(self, document: Document, chunks: list[str]) -> None:
        if not chunks:
            logger.warning(
                f"No chunks to embed/save for document '{document.filename}'"
            )
            return
        source_url = document.source_url
        logger.debug(
            f"Generating embeddings for {len(chunks)} chunks of document '{document.filename}' (ID: {document.id})..."
        )
        embeddings = self.embedding_service.embed_texts(chunks)
        logger.debug("Generated embeddings. Storing chunks in database...")
        chunk_objects = [
            DocumentChunk(
                document=document,
                content=f"Source: {source_url}\n\n{chunk_content}"
                if source_url
                else chunk_content,
                chunk_index=i,
                embedding=embedding,
                word_count=len(chunk_content.split()),
            )
            for i, (chunk_content, embedding) in enumerate(zip(chunks, embeddings))
        ]
        DocumentChunk.objects.bulk_create(chunk_objects)
        logger.debug("Updating search vectors for search indexing...")
        DocumentChunk.objects.filter(document=document).update(
            search_vector=SearchVector(
                "content", config=self.get_language_config(document.language)
            )
        )

    def process_upload(self, user, file, language: str = "english") -> Document:
        content_type = file.content_type or ""
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(
                f"Unsupported file type: {content_type}. "
                f"Supported: {', '.join(sorted(SUPPORTED_CONTENT_TYPES))}"
            )

        if file.size > settings.FILE_UPLOAD_MAX_SIZE:
            max_mb = settings.FILE_UPLOAD_MAX_SIZE / (1024 * 1024)
            raise ValueError(f"File too large. Maximum size: {max_mb:.0f}MB")

        logger.debug(
            f"Processing uploaded file '{file.name}' (size={file.size} bytes, content_type={content_type}, language={language})"
        )
        file_bytes = file.read()
        raw_text = extract_text(file_bytes, content_type)

        if not raw_text.strip():
            raise ValueError("Could not extract any text from the file.")

        chunks, meta = self._chunk_for_content_type(raw_text, content_type)
        logger.debug(
            f"Split uploaded document '{file.name}' into {len(chunks)} chunk(s)"
        )

        document = Document.objects.create(
            user=user,
            filename=file.name,
            content_type=content_type,
            raw_text=raw_text,
            language=language,
            meta=meta,
        )

        self._create_document_chunks(document, chunks)
        logger.debug(
            f"Successfully uploaded, chunked, and indexed '{file.name}' (ID: {document.id}, chunks={len(chunks)})"
        )

        return document

    def process_text(
        self,
        user,
        raw_text: str,
        content_type: str,
        filename: str,
        language: str = "english",
        source_url: str | None = None,
    ) -> Document:
        if content_type not in ("text/plain", "text/markdown"):
            raise ValueError(
                f"Unsupported content type for text paste: {content_type}. "
                f"Supported: text/plain, text/markdown"
            )

        if not raw_text.strip():
            raise ValueError("Content cannot be empty.")

        logger.debug(
            f"Processing pasted text document '{filename}' (len={len(raw_text)} chars, content_type={content_type}, language={language})"
        )
        chunks, meta = self._chunk_for_content_type(raw_text, content_type)
        logger.debug(f"Split pasted document '{filename}' into {len(chunks)} chunk(s)")

        document = Document.objects.create(
            user=user,
            filename=filename,
            content_type=content_type,
            raw_text=raw_text,
            language=language,
            meta=meta,
            source_url=source_url,
        )

        self._create_document_chunks(document, chunks)
        logger.debug(
            f"Successfully pasted, chunked, and indexed '{filename}' (ID: {document.id}, chunks={len(chunks)})"
        )

        return document

    def _build_bm25_sql(self, doc_filter: str) -> str:
        lang_values = ", ".join(
            f"('{lang}'::varchar, '{self.get_language_config(lang)}'::regconfig)"
            for lang in PG_REGCONFIG.keys()
        )
        return f"""
WITH lang_config(language, regconfig) AS (
    VALUES {lang_values}
),
query_lexemes AS (
    SELECT 'english'::varchar AS language,
           unnest(tsvector_to_array(to_tsvector('english'::regconfig, %s))) AS lexeme
    UNION ALL
    SELECT 'polish'::varchar AS language,
           unnest(tsvector_to_array(to_tsvector('simple'::regconfig, %s))) AS lexeme
),
query_tsquery AS (
    SELECT ql.language,
           to_tsquery(lc.regconfig, string_agg(DISTINCT ql.lexeme, ' | ')) AS tsq
      FROM query_lexemes ql
      JOIN lang_config lc ON lc.language = ql.language
     GROUP BY ql.language, lc.regconfig
),
scope AS (
    SELECT dc.id AS chunk_id,
           d.language,
           dc.search_vector,
           dc.word_count
      FROM documents_documentchunk dc
      JOIN documents_document d ON d.id = dc.document_id
      JOIN query_tsquery qt ON qt.language = d.language
     WHERE d.user_id = %s
       {doc_filter}
       AND dc.search_vector @@ qt.tsq
),
term_freq AS (
    SELECT s.chunk_id,
           s.language,
           s.word_count,
           lex.lexeme,
           array_length(lex.positions, 1)::float AS tf
      FROM scope s,
           unnest(s.search_vector) AS lex(lexeme, positions, weights)
     WHERE (s.language, lex.lexeme) IN (SELECT language, lexeme FROM query_lexemes)
),
df_stats AS (
    SELECT tf.lexeme,
           tf.language,
           COUNT(DISTINCT tf.chunk_id)::float AS doc_freq
      FROM term_freq tf
     GROUP BY tf.lexeme, tf.language
),
term_idf AS (
    SELECT ql.lexeme,
           ql.language,
           ln((%s - COALESCE(ds.doc_freq, 0) + 0.5)
              / (COALESCE(ds.doc_freq, 0) + 0.5) + 1) AS idf
      FROM query_lexemes ql
      LEFT JOIN df_stats ds ON ds.lexeme = ql.lexeme AND ds.language = ql.language
)
SELECT tf.chunk_id,
       SUM(
           ti.idf
           * (tf.tf * (%s + 1))
           / (tf.tf + %s * (1.0 - %s + %s * tf.word_count / %s))
       ) AS bm25_score
  FROM term_freq tf
  JOIN term_idf ti ON ti.lexeme = tf.lexeme AND ti.language = tf.language
 GROUP BY tf.chunk_id
 ORDER BY bm25_score DESC
 LIMIT %s;
"""

    def _keyword_bm25_search(
        self,
        *,
        user,
        english_query: str,
        polish_query: str,
        document_ids: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, float]:
        if not english_query.strip() and not polish_query.strip():
            return {}

        k1 = settings.BM25_K1
        b = settings.BM25_B

        stats_qs = DocumentChunk.objects.filter(document__user=user)
        if document_ids:
            stats_qs = stats_qs.filter(document_id__in=document_ids)

        stats = stats_qs.aggregate(
            total_chunks=Count("id"),
            avg_dl=Avg("word_count"),
        )
        total_chunks = float(stats["total_chunks"] or 0)
        avg_dl = float(stats["avg_dl"] or 1.0)
        if avg_dl <= 0:
            avg_dl = 1.0

        doc_filter = ""
        params: list = []

        if document_ids:
            placeholders = ", ".join(["%s::uuid"] * len(document_ids))
            doc_filter = f"AND dc.document_id IN ({placeholders})"

        sql = self._build_bm25_sql(doc_filter)

        params.extend(
            [
                english_query,
                polish_query,
                str(user.id),
                *([str(d) for d in document_ids] if document_ids else []),
                total_chunks,
                k1,
                k1,
                b,
                b,
                avg_dl,
                limit,
            ]
        )

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return {str(row[0]): float(row[1]) for row in rows}

    async def _vector_search(
        self,
        user,
        query_embedding: list[float],
        document_ids: list[str] | None = None,
        limit: int = 50,
    ) -> list[DocumentChunk]:
        qs = DocumentChunk.objects.filter(document__user=user)
        if document_ids:
            qs = qs.filter(document_id__in=document_ids)
        return [
            chunk
            async for chunk in qs.annotate(
                distance=CosineDistance("embedding", query_embedding)
            )
            .select_related("document")
            .order_by("distance")[:limit]
        ]

    @staticmethod
    def _reciprocal_rank_fusion(
        *rank_lists: list[str],
        k: int = 60,
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for rank_list in rank_lists:
            for rank, chunk_id in enumerate(rank_list, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        return scores

    async def search(
        self,
        user,
        query: str | None = None,
        *,
        query_embedding: list[float] | None = None,
        refined_english_query: str | None = None,
        refined_polish_query: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        if query_embedding is None:
            if not query:
                raise ValueError("Either query or query_embedding must be provided.")
            query_embedding = await asyncio.to_thread(
                self.embedding_service.embed_query, query
            )

        if refined_english_query is None:
            refined_english_query = query or ""

        if refined_polish_query is None:
            refined_polish_query = query or ""

        pool = settings.HYBRID_RETRIEVAL_POOL
        logger.debug(
            f"Hybrid search started for user={user.id} query='{query or ''}' pool={pool}"
        )

        vector_task = self._vector_search(
            user, query_embedding, document_ids=document_ids, limit=pool
        )
        bm25_task = sync_to_async(self._keyword_bm25_search, thread_sensitive=False)(
            user=user,
            english_query=refined_english_query,
            polish_query=refined_polish_query,
            document_ids=document_ids,
            limit=pool,
        )

        vector_results, bm25_scores = await asyncio.gather(vector_task, bm25_task)
        vector_rank_list = [str(chunk.id) for chunk in vector_results]
        vector_map = {str(chunk.id): chunk for chunk in vector_results}

        for rank, chunk in enumerate(vector_results, start=1):
            logger.debug(
                f"[Vector Candidate] Rank {rank}: chunk_id={chunk.id} "
                f"distance={chunk.distance:.6f} similarity={1.0 - chunk.distance:.6f}"
            )

        bm25_rank_list = list(bm25_scores.keys())

        for rank, (chunk_id, score) in enumerate(bm25_scores.items(), start=1):
            logger.debug(
                f"[BM25 Candidate] Rank {rank}: chunk_id={chunk_id} score={score:.6f}"
            )

        logger.debug(
            f"Retrieved search candidates: vector={len(vector_results)}, bm25={len(bm25_scores)}"
        )

        rrf_scores = self._reciprocal_rank_fusion(
            vector_rank_list, bm25_rank_list, k=settings.RRF_K
        )

        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)[
            : settings.RAG_TOP_K
        ]

        missing_ids = [cid for cid in sorted_ids if cid not in vector_map]
        if missing_ids:
            logger.debug(
                f"Fetched {len(missing_ids)} BM25-exclusive chunks from DB: {missing_ids}"
            )
            extra_chunks = [
                chunk
                async for chunk in DocumentChunk.objects.filter(
                    id__in=missing_ids
                ).select_related("document")
            ]
            for chunk in extra_chunks:
                vector_map[str(chunk.id)] = chunk

        results = []
        for chunk_id in sorted_ids:
            chunk = vector_map.get(chunk_id)
            if chunk is None:
                continue
            results.append(
                SearchResult(
                    chunk_content=chunk.content,
                    document_id=str(chunk.document_id),
                    document_filename=chunk.document.filename,
                    chunk_index=chunk.chunk_index,
                    score=rrf_scores[chunk_id],
                )
            )

        for rank, chunk_id in enumerate(sorted_ids, start=1):
            v_rank = (
                vector_rank_list.index(chunk_id) + 1
                if chunk_id in vector_rank_list
                else "N/A"
            )
            b_rank = (
                bm25_rank_list.index(chunk_id) + 1
                if chunk_id in bm25_rank_list
                else "N/A"
            )
            logger.debug(
                f"[Fused RRF Candidate] Rank {rank}: chunk_id={chunk_id} "
                f"score={rrf_scores[chunk_id]:.6f} (vector_rank={v_rank}, bm25_rank={b_rank})"
            )

        logger.debug(
            f"Hybrid search summary: fused={len(rrf_scores)}, returned={len(results)}"
        )

        return results
