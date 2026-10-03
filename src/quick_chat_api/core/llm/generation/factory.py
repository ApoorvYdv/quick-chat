"""`get_chat_model(role)`: the only way application code obtains a chat model."""

from __future__ import annotations

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

# Import side effect: registers all built-in providers.
from quick_chat_api.core.llm.generation import providers as _providers  # noqa: F401
from quick_chat_api.core.llm.generation.registry import ModelRole, build_provider
from quick_chat_api.settings.config import settings


@lru_cache
def get_chat_model(role: ModelRole = "answer") -> BaseChatModel:
    return build_provider(settings.LLM_PROVIDER.lower(), settings, role)
