"""Chunker registry.

Decouples the factory from concrete chunker implementations: each strategy
module registers its own builder under a name via `@register_chunker(...)`.
Adding a new strategy (e.g. a recursive/semantic chunker for Phase 4 file
ingestion) never requires editing this file or the factory -- only adding a
new module under `providers/` and importing it in `providers/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from quick_chat_api.modules.embedding.chunking.exceptions import UnknownChunkerError

if TYPE_CHECKING:
    from quick_chat_api.modules.embedding.chunking.base import Chunker

ChunkerBuilder = Callable[[], "Chunker"]

_REGISTRY: dict[str, ChunkerBuilder] = {}


def register_chunker(name: str) -> Callable[[ChunkerBuilder], ChunkerBuilder]:
    """Class/function decorator that registers a builder under `name`."""

    def decorator(builder: ChunkerBuilder) -> ChunkerBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def build_chunker(name: str) -> Chunker:
    """Look up and construct the chunker registered under `name`."""
    try:
        builder = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownChunkerError(
            f"CHUNKING_STRATEGY='{name}' is not registered. "
            f"Available strategies: {available}."
        ) from None
    return builder()
