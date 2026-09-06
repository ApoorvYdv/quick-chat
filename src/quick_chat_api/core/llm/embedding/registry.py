"""Provider registry.

Decouples the factory from concrete provider implementations: each provider
module registers its own builder under a name via `@register_provider(...)`.
Adding a new provider (e.g. "openai") never requires editing this file or
the factory -- only adding a new module under `providers/` and importing it
in `providers/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from quick_chat_api.core.llm.embedding.exceptions import UnknownEmbeddingProviderError

if TYPE_CHECKING:
    from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
    from quick_chat_api.settings.config import Settings

ProviderBuilder = Callable[["Settings"], "EmbeddingProvider"]

_REGISTRY: dict[str, ProviderBuilder] = {}


def register_provider(
    name: str,
) -> Callable[[ProviderBuilder], ProviderBuilder]:
    """Class/function decorator that registers a builder under `name`."""

    def decorator(builder: ProviderBuilder) -> ProviderBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def build_provider(name: str, config: Settings) -> EmbeddingProvider:
    """Look up and construct the provider registered under `name`."""
    try:
        builder = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownEmbeddingProviderError(
            f"EMBEDDING_PROVIDER='{name}' is not registered. "
            f"Available providers: {available}."
        ) from None
    return builder(config)
