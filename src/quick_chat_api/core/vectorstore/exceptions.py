"""Exceptions raised by the vector store subsystem."""

from __future__ import annotations


class VectorStoreError(RuntimeError):
    """Base class for all vector-store errors."""


class UnknownVectorStoreError(VectorStoreError):
    """`VECTOR_STORE_PROVIDER` does not match any registered provider."""


class VectorStoreOperationError(VectorStoreError):
    """A vector store call (upsert/delete/search) failed."""
