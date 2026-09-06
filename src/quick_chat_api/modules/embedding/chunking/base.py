"""Chunking interface.

A `Chunker` turns one `ProjectedDocument` into one or more `Chunk`s sized to
fit the active embedding model's token budget. Callers (the ingestion
service) depend only on this interface via `get_chunker()`, never on a
concrete chunker class, so swapping the strategy is a config change
(`Settings.CHUNKING_STRATEGY`), not a call-site change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider


class SplitReason(StrEnum):
    """Why a chunk boundary was drawn where it was -- stamped into chunk metadata."""

    SINGLE_CHUNK = "single_chunk"
    """The whole document fit under the token budget; no splitting needed."""

    FIELD_PACKED = "field_packed"
    """Split along field-line boundaries; no field's text was cut mid-way."""

    TOKEN_WINDOW_FALLBACK = "token_window_fallback"
    """A single field's own text exceeded the budget; split by token window."""


@dataclass(frozen=True)
class Chunk:
    """One retrievable, embeddable unit produced from a `ProjectedDocument`.

    `index` is the chunk's position within its parent document (maps
    directly to `ai_knowledge_chunk.chunk_index`). `metadata` carries the
    source document's own metadata plus chunking provenance (strategy,
    version, split reason, sibling count) -- sibling chunks share the same
    `document_id` at persistence time, which is what lets retrieval expand
    a single matched chunk into its full document's context without a
    dedicated parent-chunk column.
    """

    content: str
    index: int
    token_count: int
    metadata: dict = field(default_factory=dict)


class Chunker(ABC):
    """Splits one projected document into token-budget-respecting chunks."""

    @abstractmethod
    def chunk(
        self,
        content: str,
        document_metadata: dict,
        provider: EmbeddingProvider,
    ) -> list[Chunk]:
        """Split `content` into `Chunk`s sized against `provider`'s token budget.

        `document_metadata` (the source `ProjectedDocument.metadata`) is
        merged into every produced chunk's metadata so per-chunk retrieval
        filtering never loses the parent document's business context.
        """
