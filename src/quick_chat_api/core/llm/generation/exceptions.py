"""Exceptions raised by the chat-model subsystem."""

from __future__ import annotations


class ChatModelProviderError(RuntimeError):
    """Base class for all chat-model provider errors."""


class UnknownChatModelProviderError(ChatModelProviderError):
    """`LLM_PROVIDER` does not match any registered provider."""
