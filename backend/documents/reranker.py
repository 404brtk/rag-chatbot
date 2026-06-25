import logging
import httpx

from django.conf import settings
from core.exceptions import TemporaryProviderError

logger = logging.getLogger(__name__)


class RerankerService:
    _instance = None

    @classmethod
    def get_instance(cls) -> "RerankerService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def rerank(
        self, query: str, texts: list[str], context_msg: str = "document reranking"
    ) -> list[dict]:
        if not texts:
            return []

        url = f"{settings.TEI_RERANKER_URL.rstrip('/')}/rerank"
        batch_size = 32
        all_results = []

        try:
            with httpx.Client(timeout=60.0) as client:
                for i in range(0, len(texts), batch_size):
                    batch = texts[i : i + batch_size]
                    response = client.post(
                        url,
                        json={
                            "query": query,
                            "texts": batch,
                            "truncate": True,
                        },
                        headers={"Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    batch_results = response.json()
                    if not isinstance(batch_results, list):
                        raise ValueError(
                            "Expected a list of reranking results from TEI"
                        )

                    for item in batch_results:
                        item["index"] = item["index"] + i
                        all_results.append(item)

            return all_results
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500:
                raise
            logger.exception(f"TEI reranker server error during {context_msg}")
            raise TemporaryProviderError("Reranking failed due to server error")
        except Exception:
            logger.exception(f"Failed to connect to TEI reranker during {context_msg}")
            raise TemporaryProviderError("Reranking failed")
