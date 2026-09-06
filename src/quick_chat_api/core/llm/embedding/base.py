"""Embedding provider interface.

Every concrete backend (local model, OpenAI, Voyage, Cohere, ...) implements
this contract. Callers (ingestion, retrieval) must depend only on this
interface, never on a specific provider class, so a provider swap is a
config change (`EMBEDDING_PROVIDER`), not a code change at call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Turns text into vectors for storage (documents) or search (queries).

    Also exposes the model's real tokenizer so callers (chunking, in
    particular) can size text against the model's actual input limit
    instead of guessing from character/word counts.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector width. Must match `Settings.EMBEDDING_DIM`."""

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """Maximum input sequence length the model accepts, in tokens."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Exact token count for `text` under this model's own tokenizer."""

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents/chunks for storage. Batch, never one-by-one."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single user query for similarity search."""
