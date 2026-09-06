"""Factory for the process-wide `Chunker` instance.

Callers should always go through `get_chunker()` rather than constructing a
chunker directly, mirroring `core/llm/embedding/factory.py`.
"""

from __future__ import annotations

from functools import lru_cache

# Import side effect: registers all built-in chunking strategies.
from quick_chat_api.modules.embedding.chunking import (
    providers as _providers,  # noqa: F401
)
from quick_chat_api.modules.embedding.chunking.base import Chunker
from quick_chat_api.modules.embedding.chunking.registry import build_chunker
from quick_chat_api.settings.config import settings


@lru_cache
def get_chunker() -> Chunker:
    """Return the cached chunker selected by `Settings.CHUNKING_STRATEGY`."""
    return build_chunker(settings.CHUNKING_STRATEGY.lower())
