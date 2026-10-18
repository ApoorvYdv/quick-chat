"""Reranker that calls the shared inference service's /rerank over HTTP.

# ponytail: top_n / min_score are applied by the service from its own
# settings; keep RERANK_TOP_N and RERANK_MIN_SCORE equal on both sides.
"""

from __future__ import annotations

import httpx

from quick_chat_api.core.llm.reranking.base import (
    RerankCandidate,
    RerankProvider,
    RerankResult,
)
from quick_chat_api.core.llm.reranking.exceptions import RerankProviderError
from quick_chat_api.core.llm.reranking.registry import register_reranker
from quick_chat_api.settings.config import Settings


class RemoteReranker(RerankProvider):
    def __init__(
        self, base_url: str, timeout_s: float, client: httpx.AsyncClient | None = None
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        if not candidates:
            return []
        body = {
            "query": query,
            "candidates": [{"id": c.id, "text": c.text} for c in candidates],
        }
        try:
            response = await self._client.post("/rerank", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RerankProviderError(
                f"Inference service call /rerank failed: {type(exc).__name__}"
            ) from exc
        known = {c.id for c in candidates}
        return [
            RerankResult(r["id"], r["score"])
            for r in response.json()["results"]
            if r["id"] in known
        ]


@register_reranker("remote")
def _build_remote(config: Settings) -> RemoteReranker:
    return RemoteReranker(config.RERANK_REMOTE_URL, config.RERANK_REMOTE_TIMEOUT_S)
