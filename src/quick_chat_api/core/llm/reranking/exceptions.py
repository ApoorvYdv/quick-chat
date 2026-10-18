"""Exceptions raised by the reranking subsystem."""

from __future__ import annotations


class RerankProviderError(RuntimeError):
    """Base class for all rerank-provider errors."""


class UnknownRerankProviderError(RerankProviderError):
    """`RERANK_PROVIDER` does not match any registered provider."""
