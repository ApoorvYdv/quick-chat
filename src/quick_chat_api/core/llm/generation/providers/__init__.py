"""Concrete chat-model providers; importing this package registers them."""

from quick_chat_api.core.llm.generation.providers import anthropic as _anthropic
from quick_chat_api.core.llm.generation.providers import ollama as _ollama

__all__: list[str] = []

_ = (_anthropic, _ollama)
