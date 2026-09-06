"""Embedding provider interface.

Every concrete backend (local model, OpenAI, Voyage, Cohere, ...) implements
this contract. Callers (ingestion, retrieval) must depend only on this
interface, never on a specific provider class, so a provider swap is a
config change (`EMBEDDING_PROVIDER`), not a code change at call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Turns text into vectors for storage (documents) or search (queries)."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector width. Must match `Settings.EMBEDDING_DIM`."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents/chunks for storage. Batch, never one-by-one."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single user query for similarity search."""
