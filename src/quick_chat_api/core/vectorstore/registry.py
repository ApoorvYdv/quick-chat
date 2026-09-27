"""Provider registry.

Decouples the factory from concrete provider implementations: each provider
module registers its own builder under a name via `@register_store(...)`.
Adding a new provider never requires editing this file or the factory --
only adding a new module under `providers/` and importing it in
`providers/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from quick_chat_api.core.vectorstore.exceptions import UnknownVectorStoreError

if TYPE_CHECKING:
    from quick_chat_api.core.vectorstore.base import VectorStore
    from quick_chat_api.settings.config import Settings

StoreBuilder = Callable[["Settings"], "VectorStore"]

_REGISTRY: dict[str, StoreBuilder] = {}


def register_store(name: str) -> Callable[[StoreBuilder], StoreBuilder]:
    """Class/function decorator that registers a builder under `name`."""

    def decorator(builder: StoreBuilder) -> StoreBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def build_store(name: str, config: Settings) -> VectorStore:
    """Look up and construct the provider registered under `name`."""
    try:
        builder = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownVectorStoreError(
            f"VECTOR_STORE_PROVIDER='{name}' is not registered. "
            f"Available providers: {available}."
        ) from None
    return builder(config)
