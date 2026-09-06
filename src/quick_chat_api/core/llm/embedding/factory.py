"""Factory for the process-wide `EmbeddingProvider` instance.

Callers should always go through `get_embedding_provider()` rather than
constructing a provider directly -- model load is expensive (seconds,
hundreds of MB of weights for local models), so the instance is cached for
the lifetime of the process.
"""

from __future__ import annotations

from functools import lru_cache

# Import side effect: registers all built-in providers.
from quick_chat_api.core.llm.embedding import providers as _providers  # noqa: F401
from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.registry import build_provider
from quick_chat_api.settings.config import settings


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Return the cached embedding provider selected by `EMBEDDING_PROVIDER`."""
    return build_provider(settings.EMBEDDING_PROVIDER.lower(), settings)
