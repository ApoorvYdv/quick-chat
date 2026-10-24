"""Chat models via OpenRouter's OpenAI-compatible API (free-tier friendly)."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from quick_chat_api.core.llm.generation.exceptions import ChatModelProviderError
from quick_chat_api.core.llm.generation.registry import ModelRole, register_provider
from quick_chat_api.settings.config import Settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@register_provider("openrouter")
def _build_openrouter(config: Settings, role: ModelRole) -> BaseChatModel:
    if (
        not config.OPENROUTER_API_KEY
        or not config.OPENROUTER_API_KEY.get_secret_value()
    ):
        raise ChatModelProviderError(
            "LLM_PROVIDER='openrouter' requires OPENROUTER_API_KEY."
        )

    from langchain_openai import ChatOpenAI

    model = config.LLM_ROUTER_MODEL if role == "router" else config.LLM_ANSWER_MODEL
    return ChatOpenAI(
        model=model,
        api_key=config.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        temperature=config.LLM_TEMPERATURE,
        max_completion_tokens=config.LLM_MAX_TOKENS,
        timeout=config.LLM_TIMEOUT_S,
        max_retries=config.LLM_MAX_RETRIES,
        # Free models are mostly reasoning models; unbounded thinking eats LLM_MAX_TOKENS.
        extra_body={"reasoning": {"effort": "low"}},
    )
