import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    _instance = None
    _model = None
    _dimensions = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_model(self):
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer

            model_name = settings.EMBEDDING_MODEL
            logger.info(f"Loading embedding model: {model_name}")
            self._model = SentenceTransformer(model_name)
            self._dimensions = self._model.get_embedding_dimension()
            logger.info(f"Embedding model loaded (dimensions={self._dimensions})")

            if self._dimensions != settings.EMBEDDING_DIMENSIONS:
                raise RuntimeError(
                    f"Embedding model '{model_name}' produces {self._dimensions} dimensions, "
                    f"but settings.EMBEDDING_DIMENSIONS is {settings.EMBEDDING_DIMENSIONS}. "
                    f"Update settings or run a migration."
                )

    @property
    def dimensions(self) -> int:
        self._load_model()
        return self._dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._load_model()
        embeddings = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]
