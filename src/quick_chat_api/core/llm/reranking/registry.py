"""Provider registry: each provider module registers its own builder by name."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from quick_chat_api.core.llm.reranking.exceptions import UnknownRerankProviderError

if TYPE_CHECKING:
    from quick_chat_api.core.llm.reranking.base import RerankProvider
    from quick_chat_api.settings.config import Settings

ProviderBuilder = Callable[["Settings"], "RerankProvider"]

_REGISTRY: dict[str, ProviderBuilder] = {}


def register_reranker(
    name: str,
) -> Callable[[ProviderBuilder], ProviderBuilder]:
    def decorator(builder: ProviderBuilder) -> ProviderBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def build_reranker(name: str, config: Settings) -> RerankProvider:
    try:
        builder = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownRerankProviderError(
            f"RERANK_PROVIDER='{name}' is not registered. "
            f"Available providers: {available}."
        ) from None
    return builder(config)
