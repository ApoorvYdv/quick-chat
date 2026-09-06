"""Exceptions raised by the chunking subsystem."""

from __future__ import annotations


class ChunkingError(RuntimeError):
    """Base class for all chunking errors."""


class UnknownChunkerError(ChunkingError):
    """`Settings.CHUNKING_STRATEGY` does not match any registered chunker."""
