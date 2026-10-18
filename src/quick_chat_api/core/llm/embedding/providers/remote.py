"""Embedding provider that calls the shared inference service over HTTP.

The service hosts the model once; API workers stay light. Model identity is
checked against `EMBEDDING_MODEL`/`EMBEDDING_DIM` on first use (`ensure_ready`)
so the indexing key stays valid when switching `local` <-> `remote`.
"""

from __future__ import annotations

import asyncio

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
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)
        self._expected_model = expected_model
        self._expected_dimension = expected_dimension
        self._lock = asyncio.Lock()
        self._info: dict | None = None

    async def ensure_ready(self) -> None:
        if self._info is not None:
            return
        async with self._lock:
            if self._info is not None:
                return
            info = await self._request("GET", "/info")
            if info["model"] != self._expected_model:
                raise EmbeddingProviderError(
                    f"Inference service serves model '{info['model']}', "
                    f"but EMBEDDING_MODEL is '{self._expected_model}'."
                )
            if info["dimension"] != self._expected_dimension:
                raise EmbeddingDimensionMismatchError(
                    f"Inference service outputs {info['dimension']}-dim vectors, "
                    f"but EMBEDDING_DIM is configured as {self._expected_dimension}."
                )
            self._info = info

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        try:
            response = await self._client.request(method, path, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingProviderError(
                f"Inference service call {path} failed: {type(exc).__name__}"
            ) from exc
        return response.json()

    async def _call(self, path: str, json: dict) -> dict:
        await self.ensure_ready()
        return await self._request("POST", path, json)

    def _ready_info(self) -> dict:
        if self._info is None:
            raise EmbeddingProviderError(
                "Remote embedding provider used before `await ensure_ready()`."
            )
        return self._info

    @property
    def dimension(self) -> int:
        return self._ready_info()["dimension"]

    @property
    def max_tokens(self) -> int:
        return self._ready_info()["max_tokens"]

    async def count_tokens_batch(self, texts: list[str]) -> list[int]:
        if not texts:
            return []
        return (await self._call("/count_tokens", {"texts": texts}))["counts"]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return (await self._call("/embed", {"texts": texts, "kind": "document"}))[
            "embeddings"
        ]

    async def embed_query(self, text: str) -> list[float]:
        return (await self._call("/embed", {"texts": [text], "kind": "query"}))[
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
