"""Local chat models served by Ollama (on-device, no API cost)."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from quick_chat_api.core.llm.generation.registry import ModelRole, register_provider
from quick_chat_api.settings.config import Settings


@register_provider("ollama")
def _build_ollama(config: Settings, role: ModelRole) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    model = config.LLM_ROUTER_MODEL if role == "router" else config.LLM_ANSWER_MODEL
    return ChatOllama(
        model=model,
        base_url=config.LLM_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        num_predict=config.LLM_MAX_TOKENS,
        client_kwargs={"timeout": config.LLM_TIMEOUT_S},
    )
