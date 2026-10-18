"""Factory for the process-wide `RerankProvider` (cached: model load is expensive)."""

from __future__ import annotations

from functools import lru_cache

# Import side effect: registers all built-in providers.
from quick_chat_api.core.llm.reranking import providers as _providers  # noqa: F401
from quick_chat_api.core.llm.reranking.base import RerankProvider
from quick_chat_api.core.llm.reranking.registry import build_reranker
from quick_chat_api.settings.config import settings


@lru_cache
def get_reranker() -> RerankProvider:
    return build_reranker(settings.RERANK_PROVIDER.lower(), settings)
