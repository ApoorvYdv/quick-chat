"""Passthrough: no reranking, keep the first `top_n` candidates in input order."""

from __future__ import annotations

from quick_chat_api.core.llm.reranking.base import (
    RerankCandidate,
    RerankProvider,
    RerankResult,
)
from quick_chat_api.core.llm.reranking.registry import register_reranker
from quick_chat_api.settings.config import Settings


class NoopReranker(RerankProvider):
    def __init__(self, top_n: int) -> None:
        self._top_n = top_n

    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        # No model, so no score: 0.0 is a placeholder, not a relevance signal.
        return [RerankResult(c.id, 0.0) for c in candidates[: self._top_n]]


@register_reranker("none")
def _build_none(config: Settings) -> NoopReranker:
    return NoopReranker(config.RERANK_TOP_N)
