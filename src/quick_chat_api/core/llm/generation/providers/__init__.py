"""Concrete chat-model providers; importing this package registers them."""

from quick_chat_api.core.llm.generation.providers import ollama as _ollama

__all__: list[str] = []

_ = _ollama
