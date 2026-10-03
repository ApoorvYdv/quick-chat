"""Embedding provider that calls the shared inference service over HTTP.

The service hosts the model once; API workers stay light. Model identity is
checked against `EMBEDDING_MODEL`/`EMBEDDING_DIM` at startup so the indexing
key stays valid when switching `local` <-> `remote`.
"""

from __future__ import annotations

import httpx

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
)
from quick_chat_api.core.llm.embedding.registry import register_provider
from quick_chat_api.settings.config import Settings


class RemoteEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        base_url: str,
        expected_model: str,
        expected_dimension: int,
        timeout_s: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_s)
        info = self._post_or_get("GET", "/info")
        if info["model"] != expected_model:
            raise EmbeddingProviderError(
                f"Inference service serves model '{info['model']}', "
                f"but EMBEDDING_MODEL is '{expected_model}'."
            )
        if info["dimension"] != expected_dimension:
            raise EmbeddingDimensionMismatchError(
                f"Inference service outputs {info['dimension']}-dim vectors, "
                f"but EMBEDDING_DIM is configured as {expected_dimension}."
            )
        self._dimension: int = info["dimension"]
        self._max_tokens: int = info["max_tokens"]

    def _post_or_get(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            response = self._client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError(
                f"Inference service call {path} failed: {type(exc).__name__}"
            ) from exc
        return response.json()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def count_tokens(self, text: str) -> int:
        # ponytail: one HTTP call per count; add a batch API to the interface if chunking gets slow
        return self._post_or_get("POST", "/count_tokens", {"texts": [text]})["counts"][
            0
        ]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._post_or_get(
            "POST", "/embed", {"texts": texts, "kind": "document"}
        )["embeddings"]

    def embed_query(self, text: str) -> list[float]:
        return self._post_or_get("POST", "/embed", {"texts": [text], "kind": "query"})[
            "embeddings"
        ][0]


@register_provider("remote")
def _build_remote_provider(config: Settings) -> RemoteEmbeddingProvider:
    return RemoteEmbeddingProvider(
        base_url=config.EMBEDDING_REMOTE_URL,
        expected_model=config.EMBEDDING_MODEL,
        expected_dimension=config.EMBEDDING_DIM,
        timeout_s=config.EMBEDDING_REMOTE_TIMEOUT_S,
    )
