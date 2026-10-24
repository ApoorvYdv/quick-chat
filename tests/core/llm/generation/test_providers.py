from __future__ import annotations

import pytest
from pydantic import SecretStr

from quick_chat_api.core.llm.generation import (
    ChatModelProviderError,
    UnknownChatModelProviderError,
)
from quick_chat_api.core.llm.generation.registry import build_provider
from quick_chat_api.settings.config import settings


def _anthropic_settings(**overrides):
    return settings.model_copy(
        update={
            "ANTHROPIC_API_KEY": SecretStr("test-key"),
            "LLM_ANSWER_MODEL": "claude-sonnet-5-5",
            "LLM_ROUTER_MODEL": "claude-haiku-5-5",
            "LLM_TIMEOUT_S": 30.0,
            "LLM_MAX_RETRIES": 3,
            "LLM_MAX_TOKENS": 512,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("role", "model"),
    [("answer", "claude-sonnet-5-5"), ("router", "claude-haiku-5-5")],
)
def test_anthropic_builds_configured_model_per_role(role, model) -> None:
    chat = build_provider("anthropic", _anthropic_settings(), role)

    assert type(chat).__name__ == "ChatAnthropic"
    assert chat.model == model
    assert chat.default_request_timeout == 30.0
    assert chat.max_retries == 3
    assert chat.max_tokens == 512
    assert chat.anthropic_api_key.get_secret_value() == "test-key"


@pytest.mark.parametrize("key", [None, SecretStr("")])
def test_anthropic_without_api_key_fails_fast(key) -> None:
    with pytest.raises(ChatModelProviderError, match="ANTHROPIC_API_KEY"):
        build_provider(
            "anthropic", _anthropic_settings(ANTHROPIC_API_KEY=key), "answer"
        )


def test_ollama_still_registered() -> None:
    chat = build_provider("ollama", settings, "answer")
    assert type(chat).__name__ == "ChatOllama"


def test_unknown_provider_lists_registered_names() -> None:
    with pytest.raises(
        UnknownChatModelProviderError, match="anthropic, ollama, openrouter"
    ):
        build_provider("nope", settings, "answer")


def test_openrouter_builds_per_role_and_requires_key() -> None:
    cfg = settings.model_copy(
        update={
            "OPENROUTER_API_KEY": SecretStr("k"),
            "LLM_ANSWER_MODEL": "a:free",
            "LLM_ROUTER_MODEL": "r:free",
        }
    )
    assert build_provider("openrouter", cfg, "answer").model_name == "a:free"
    assert build_provider("openrouter", cfg, "router").model_name == "r:free"
    with pytest.raises(ChatModelProviderError, match="OPENROUTER_API_KEY"):
        build_provider(
            "openrouter", cfg.model_copy(update={"OPENROUTER_API_KEY": None}), "answer"
        )
