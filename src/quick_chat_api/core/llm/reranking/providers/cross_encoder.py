"""In-process reranker backed by a `sentence-transformers` CrossEncoder.

Scores are raw logits; candidates below `min_score` are dropped.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from quick_chat_api.core.llm.reranking.base import (
    RerankCandidate,
    RerankProvider,
    RerankResult,
)
from quick_chat_api.core.llm.reranking.registry import register_reranker
from quick_chat_api.settings.config import Settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker(RerankProvider):
    def __init__(
        self,
        model_name: str,
        device: str,
        top_n: int,
        min_score: float,
        model: Any = None,
    ) -> None:
        if model is None:
            # Lazy: importing this module must not pull in torch unless selected.
            from sentence_transformers import CrossEncoder

            logger.info(
                "loading cross-encoder", extra={"model": model_name, "device": device}
            )
            model = CrossEncoder(model_name, device=device)
        self._model = model
        self._top_n = top_n
        self._min_score = min_score

    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        if not candidates:
            return []
        pairs = [(query, c.text) for c in candidates]
        scores = await asyncio.to_thread(self._model.predict, pairs)
        scored = sorted(
            (
                RerankResult(c.id, float(s))
                for c, s in zip(candidates, scores, strict=True)
            ),
            key=lambda r: r.score,
            reverse=True,
        )
        return [r for r in scored if r.score >= self._min_score][: self._top_n]


@register_reranker("cross_encoder")
def _build_cross_encoder(config: Settings) -> CrossEncoderReranker:
    return CrossEncoderReranker(
        model_name=config.RERANK_MODEL,
        device=config.RERANK_DEVICE,
        top_n=config.RERANK_TOP_N,
        min_score=config.RERANK_MIN_SCORE,
    )
