"""Chat-model provider registry (same shape as the embedding registry).

The "interface" is LangChain's `BaseChatModel`; providers only select and
configure one. Add a provider by creating `providers/<name>.py` and importing
it in `providers/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

from quick_chat_api.core.llm.generation.exceptions import (
    UnknownChatModelProviderError,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from quick_chat_api.settings.config import Settings

ModelRole = Literal["answer", "router"]
ProviderBuilder = Callable[["Settings", ModelRole], "BaseChatModel"]

_REGISTRY: dict[str, ProviderBuilder] = {}


def register_provider(name: str) -> Callable[[ProviderBuilder], ProviderBuilder]:
    def decorator(builder: ProviderBuilder) -> ProviderBuilder:
        _REGISTRY[name] = builder
        return builder

    return decorator


def build_provider(name: str, config: Settings, role: ModelRole) -> BaseChatModel:
    try:
        builder = _REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownChatModelProviderError(
            f"LLM_PROVIDER='{name}' is not registered. "
            f"Available providers: {available}."
        ) from None
    return builder(config, role)
