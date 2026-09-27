"""Factory for the process-wide `VectorStore` instance.

Callers should always go through `get_vector_store()` rather than
constructing a provider directly -- the client holds a connection pool and
is cached for the lifetime of the process.
"""

from __future__ import annotations

from functools import lru_cache

# Import side effect: registers all built-in providers.
from quick_chat_api.core.vectorstore import providers as _providers  # noqa: F401
from quick_chat_api.core.vectorstore.base import VectorStore
from quick_chat_api.core.vectorstore.registry import build_store
from quick_chat_api.settings.config import settings


@lru_cache
def get_vector_store() -> VectorStore:
    """Return the cached vector store selected by `VECTOR_STORE_PROVIDER`."""
    return build_store(settings.VECTOR_STORE_PROVIDER.lower(), settings)
