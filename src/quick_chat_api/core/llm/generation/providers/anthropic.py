"""Claude chat models via the Anthropic API."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from quick_chat_api.core.llm.generation.exceptions import ChatModelProviderError
from quick_chat_api.core.llm.generation.registry import ModelRole, register_provider
from quick_chat_api.settings.config import Settings


@register_provider("anthropic")
def _build_anthropic(config: Settings, role: ModelRole) -> BaseChatModel:
    if not config.ANTHROPIC_API_KEY or not config.ANTHROPIC_API_KEY.get_secret_value():
        raise ChatModelProviderError(
            "LLM_PROVIDER='anthropic' requires ANTHROPIC_API_KEY."
        )

    from langchain_anthropic import ChatAnthropic

    model = config.LLM_ROUTER_MODEL if role == "router" else config.LLM_ANSWER_MODEL
    return ChatAnthropic(
        model_name=model,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=config.LLM_TEMPERATURE,
        max_tokens_to_sample=config.LLM_MAX_TOKENS,
        timeout=config.LLM_TIMEOUT_S,
        max_retries=config.LLM_MAX_RETRIES,
        stop=None,  # pydantic-mypy marks it required; the model default is also None
    )
