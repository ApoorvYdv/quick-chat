"""Local, offline embedding provider backed by `sentence-transformers`.

Runs entirely on-device (CPU or Apple Silicon MPS) -- no API calls, no
per-token cost. Intended as the dev/local-testing provider; swap to a
hosted provider later purely via `EMBEDDING_PROVIDER` config, no caller
code changes required.
"""

from __future__ import annotations

import logging

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.exceptions import (
    EmbeddingDimensionMismatchError,
)
from quick_chat_api.core.llm.embedding.registry import register_provider
from quick_chat_api.settings.config import Settings

logger = logging.getLogger(__name__)


class LocalSentenceTransformerProvider(EmbeddingProvider):
    """Embeds text locally using a `sentence-transformers` model."""

    def __init__(
        self,
        model_name: str,
        expected_dimension: int,
        device: str = "cpu",
        batch_size: int = 32,
        query_prefix: str = "",
        document_prefix: str = "",
    ) -> None:
        # Imported lazily so importing this module never pulls in torch
        # unless the local provider is actually selected/instantiated.
        from sentence_transformers import SentenceTransformer

        self._batch_size = batch_size
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix

        logger.info(
            "loading local embedding model",
            extra={"model": model_name, "device": device},
        )
        self._model = SentenceTransformer(model_name, device=device)

        actual_dimension = self._model.get_embedding_dimension()
        if actual_dimension != expected_dimension:
            raise EmbeddingDimensionMismatchError(
                f"Model '{model_name}' outputs {actual_dimension}-dim vectors, "
                f"but EMBEDDING_DIM is configured as {expected_dimension}. "
                "Update EMBEDDING_DIM (and the ai_knowledge_chunk vector column "
                "width) to match, or choose a different model."
            )
        self._dimension = actual_dimension

    @property
    def dimension(self) -> int:
        return self._dimension  # type:ignore

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        prefixed = [f"{self._document_prefix}{t}" for t in texts]
        embeddings = self._model.encode(
            prefixed,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        embedding = self._model.encode(
            f"{self._query_prefix}{text}",
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding.tolist()


@register_provider("local")
def _build_local_provider(config: Settings) -> LocalSentenceTransformerProvider:
    return LocalSentenceTransformerProvider(
        model_name=config.EMBEDDING_MODEL,
        expected_dimension=config.EMBEDDING_DIM,
        device=config.EMBEDDING_DEVICE,
        batch_size=config.EMBEDDING_BATCH_SIZE,
    )
