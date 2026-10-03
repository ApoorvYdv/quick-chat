"""Ingestion service: discover -> hash/skip -> chunk -> embed -> upsert to Qdrant.

Orchestrates `CaseKnowledgeSourceAdapter` (discovery/projection),
`get_chunker()` (chunking), `get_embedding_provider()` (embedding) and
`get_vector_store()` (the only place chunks are stored; Postgres keeps just
the source case rows).

Properties this module owns:

- **No transaction across the embedding call**: case discovery runs in one
  read session that is closed before any embedding-provider call is made.
- **Per-entity failure isolation** (`CLAUDE.md` §19): one entity failing to
  chunk, embed or upsert does not abort the rest of the case. It is reported
  as a `FAILED` outcome (error message only, never entity content) and left
  unindexed/unchanged, so the next run retries it.
- **Idempotent re-indexing**: point ids are derived from the entity identity
  and chunk index, so re-embedding overwrites in place. Skip detection reads
  `content_hash`/`indexing_key`/`chunk_count` back from the stored payload.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncEngine

from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.exceptions import EmbeddingProviderError
from quick_chat_api.core.llm.embedding.factory import get_embedding_provider
from quick_chat_api.core.vectorstore.base import VectorFilter, VectorPoint
from quick_chat_api.core.vectorstore.exceptions import VectorStoreError
from quick_chat_api.core.vectorstore.factory import get_vector_store
from quick_chat_api.modules.embedding.chunking.base import Chunk
from quick_chat_api.modules.embedding.chunking.exceptions import ChunkingError
from quick_chat_api.modules.embedding.chunking.factory import get_chunker
from quick_chat_api.modules.embedding.db_adapters import (
    CaseKnowledgeSourceAdapter,
    CaseNotFoundError,
    DiscoveredEntity,
)
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger

__all__ = [
    "CaseIngestionResult",
    "CaseIngestionService",
    "CaseNotFoundError",
    "EntityIngestionOutcome",
    "IngestionOutcomeKind",
]

_SourceKey = tuple[str, str, str]

NAMESPACE_CHUNK = UUID("6f0c3a1e-8d57-4c0e-9a55-3f6f4b7d2c11")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_key(entity: DiscoveredEntity) -> _SourceKey:
    return (entity.source_table, entity.source_id, entity.source_type)


def _point_id(key: _SourceKey, chunk_index: int) -> UUID:
    """Deterministic id: re-embedding the same chunk overwrites its point."""
    return uuid5(NAMESPACE_CHUNK, ":".join((*key, str(chunk_index))))


def _indexing_key(provider: EmbeddingProvider) -> str:
    """Fingerprint of "how" a document was indexed, not "what" it contains.

    Stored in each point's payload and compared alongside `content_hash` on
    the next run -- content can be byte-identical but still need re-embedding
    if the model or chunking strategy changed.
    """
    # Provider is excluded on purpose: local and remote serve the same model.
    return f"{settings.EMBEDDING_MODEL}|{settings.EMBEDDING_VERSION}|{settings.CHUNKING_STRATEGY}|{settings.CHUNKING_VERSION}"


class IngestionOutcomeKind(StrEnum):
    """What happened to one discovered entity during a single `ingest_case` run."""

    EMBEDDED = "embedded"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    FAILED = "failed"


@dataclass(frozen=True)
class EntityIngestionOutcome:
    source_type: str
    source_id: str
    kind: IngestionOutcomeKind
    chunk_count: int = 0
    error: str | None = None


@dataclass(frozen=True)
class CaseIngestionResult:
    case_id: UUID
    outcomes: list[EntityIngestionOutcome]

    @property
    def embedded(self) -> int:
        return sum(1 for o in self.outcomes if o.kind is IngestionOutcomeKind.EMBEDDED)

    @property
    def skipped(self) -> int:
        return sum(
            1 for o in self.outcomes if o.kind is IngestionOutcomeKind.SKIPPED_UNCHANGED
        )

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.kind is IngestionOutcomeKind.FAILED)


@dataclass(frozen=True)
class _IndexedSnapshot:
    """What the vector store currently holds for one entity."""

    content_hash: str | None
    indexing_key: str | None
    chunk_count: int
    expected_chunk_count: int | None
    point_ids: list[UUID]


class CaseIngestionService:
    """Runs the discover -> chunk -> embed -> upsert pipeline for one case.

    Stateless aside from `engine`/`agency` -- a fresh instance per call (or
    reused across a batch within the same agency) both work.
    """

    def __init__(self, engine: AsyncEngine, agency: str) -> None:
        self._engine = engine
        self._agency = agency

    async def ingest_case(self, case_id: UUID) -> CaseIngestionResult:
        """Embed only entities whose content or indexing key changed since last run."""
        return await self._run(case_id, force=False)

    async def reindex_case(self, case_id: UUID) -> CaseIngestionResult:
        """Re-embed every entity for the case regardless of content_hash/indexing_key."""
        return await self._run(case_id, force=True)

    async def delete_case_index(self, case_id: UUID) -> int:
        """Delete every indexed point for `case_id`.

        Returns the number of distinct entities (sources) that were indexed.
        """
        store = get_vector_store()
        filter_ = VectorFilter(case_record_id=case_id)
        try:
            existing = await asyncio.to_thread(store.list_points, self._agency, filter_)
            await asyncio.to_thread(store.delete_by_filter, self._agency, filter_)
        except VectorStoreError as exc:
            logger.error(
                "vector store delete failed",
                extra={
                    "agency": self._agency,
                    "case_id": str(case_id),
                    "error": str(exc),
                },
            )
            raise
        return len({_payload_key(p.payload) for p in existing})

    async def _run(self, case_id: UUID, *, force: bool) -> CaseIngestionResult:
        provider = get_embedding_provider()
        chunker = get_chunker()
        indexing_key = _indexing_key(provider)

        async with session_context(self._engine, self._agency) as session:
            discovered = await CaseKnowledgeSourceAdapter(session).discover_all(case_id)
        try:
            indexed = await self._load_indexed(case_id)
        except VectorStoreError as exc:
            logger.error(
                "vector store read failed",
                extra={
                    "agency": self._agency,
                    "case_id": str(case_id),
                    "error": str(exc),
                },
            )
            return CaseIngestionResult(
                case_id=case_id,
                outcomes=[_failed(e, str(exc)) for e in discovered],
            )

        outcomes: list[EntityIngestionOutcome] = []
        for entity in discovered:
            content_hash = _content_hash(entity.document.content)
            existing = indexed.get(_source_key(entity))
            if (
                not force
                and existing is not None
                and existing.content_hash == content_hash
                and existing.indexing_key == indexing_key
                and existing.chunk_count == existing.expected_chunk_count
            ):
                outcomes.append(
                    EntityIngestionOutcome(
                        source_type=entity.source_type,
                        source_id=entity.source_id,
                        kind=IngestionOutcomeKind.SKIPPED_UNCHANGED,
                    )
                )
                continue

            try:
                chunks = chunker.chunk(
                    entity.document.content, entity.document.metadata, provider
                )
                vectors = provider.embed_documents([c.content for c in chunks])
                await self._write(
                    entity, content_hash, indexing_key, chunks, vectors, existing
                )
            except (ChunkingError, EmbeddingProviderError, VectorStoreError) as exc:
                logger.error(
                    "entity indexing failed",
                    extra={
                        "case_id": str(case_id),
                        "source_type": entity.source_type,
                        "source_id": entity.source_id,
                        "error": str(exc),
                    },
                )
                outcomes.append(_failed(entity, str(exc)))
                continue

            outcomes.append(
                EntityIngestionOutcome(
                    source_type=entity.source_type,
                    source_id=entity.source_id,
                    kind=IngestionOutcomeKind.EMBEDDED,
                    chunk_count=len(chunks),
                )
            )
        return CaseIngestionResult(case_id=case_id, outcomes=outcomes)

    async def _load_indexed(self, case_id: UUID) -> dict[_SourceKey, _IndexedSnapshot]:
        points = await asyncio.to_thread(
            get_vector_store().list_points,
            self._agency,
            VectorFilter(case_record_id=case_id),
        )
        grouped: dict[_SourceKey, list] = {}
        for point in points:
            grouped.setdefault(_payload_key(point.payload), []).append(point)
        return {
            key: _IndexedSnapshot(
                content_hash=group[0].payload.get("content_hash"),
                indexing_key=group[0].payload.get("indexing_key"),
                chunk_count=len(group),
                expected_chunk_count=group[0].payload.get("chunk_count"),
                point_ids=[p.id for p in group],
            )
            for key, group in grouped.items()
        }

    async def _write(
        self,
        entity: DiscoveredEntity,
        content_hash: str,
        indexing_key: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        existing: _IndexedSnapshot | None,
    ) -> None:
        key = _source_key(entity)
        points = [
            VectorPoint(
                id=_point_id(key, chunk.index),
                vector=vector,
                payload={
                    "case_record_id": str(entity.case_record_id),
                    "source_type": entity.source_type,
                    "source_table": entity.source_table,
                    "source_id": entity.source_id,
                    "title": entity.document.title,
                    "chunk_index": chunk.index,
                    "chunk_count": len(chunks),
                    "content": chunk.content,
                    "chunk_metadata": chunk.metadata,
                    "content_hash": content_hash,
                    "indexing_key": indexing_key,
                    "embedding_model": settings.EMBEDDING_MODEL,
                    "embedding_version": settings.EMBEDDING_VERSION,
                    "chunking_strategy": settings.CHUNKING_STRATEGY,
                    "chunking_version": settings.CHUNKING_VERSION,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        store = get_vector_store()
        await asyncio.to_thread(store.upsert_points, self._agency, points)
        # Upsert first: a failure here leaves the old, still-retrievable
        # points intact. Only trailing chunks from a previously larger split
        # become stale.
        new_ids = {p.id for p in points}
        stale_ids = [
            i for i in (existing.point_ids if existing else []) if i not in new_ids
        ]
        if stale_ids:
            await asyncio.to_thread(store.delete_points, self._agency, stale_ids)


def _payload_key(payload: dict) -> _SourceKey:
    return (
        payload.get("source_table", ""),
        payload.get("source_id", ""),
        payload.get("source_type", ""),
    )


def _failed(entity: DiscoveredEntity, error: str) -> EntityIngestionOutcome:
    return EntityIngestionOutcome(
        source_type=entity.source_type,
        source_id=entity.source_id,
        kind=IngestionOutcomeKind.FAILED,
        error=error,
    )
