"""Exceptions raised by the embedding subsystem."""

from __future__ import annotations


class EmbeddingProviderError(RuntimeError):
    """Base class for all embedding-provider errors."""


class EmbeddingDimensionMismatchError(EmbeddingProviderError):
    """A provider's actual output dimension does not match `EMBEDDING_DIM`."""


class UnknownEmbeddingProviderError(EmbeddingProviderError):
    """`EMBEDDING_PROVIDER` does not match any registered provider."""
