import logging
import httpx

from django.conf import settings

from core.exceptions import TemporaryProviderError

logger = logging.getLogger(__name__)


class EmbeddingService:
    QUERY_PREFIX = "query: "
    PASSAGE_PREFIX = "passage: "

    _instance = None

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def dimensions(self) -> int:
        return settings.EMBEDDING_DIMENSIONS

    def _embed_raw(
        self, texts: list[str], context_msg: str = "embedding generation"
    ) -> list[list[float]]:
        url = f"{settings.TEI_EMBEDDING_URL.rstrip('/')}/embed"
        batch_size = 32
        all_embeddings = []

        try:
            with httpx.Client(timeout=60.0) as client:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i : i + batch_size]
                    response = client.post(
                        url,
                        json={"inputs": batch, "truncate": True},
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    embeddings = response.json()
                    if not isinstance(embeddings, list) or not all(
                        isinstance(emb, list) for emb in embeddings
                    ):
                        raise ValueError(
                            "Expected a list of lists of floats from TEI endpoint"
                        )
                    all_embeddings.extend(embeddings)
            return all_embeddings
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            logger.exception(f"TEI server error during {context_msg}")
            raise TemporaryProviderError("Embedding generation failed")
        except Exception:
            logger.exception(
                f"Failed to generate embeddings via TEI during {context_msg}"
            )
            raise TemporaryProviderError("Embedding generation failed")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed_raw(
            [f"{self.PASSAGE_PREFIX}{t}" for t in texts],
            context_msg="embedding generation",
        )

    def embed_query(self, query: str) -> list[float]:
        return self._embed_raw(
            [f"{self.QUERY_PREFIX}{query}"],
            context_msg="query embedding",
        )[0]
