"""Ingestion service: discover -> hash/skip -> chunk -> embed -> persist.

Orchestrates `CaseKnowledgeSourceAdapter` (discovery/projection),
`get_chunker()` (chunking), and `get_embedding_provider()` (embedding) into
`ai_knowledge_source`/`ai_knowledge_chunk` writes, per `PLAN.md` §11.

Two safety properties this module owns:

- **Transaction/embedding-call separation** (`PLAN.md` §9): case discovery
  runs in one read session that is closed before any embedding-provider
  call is made, and every write happens afterward in a single, separate
  write session. No transaction is ever held open across the embedding
  call.
- **Per-entity failure isolation** (`CLAUDE.md` §19, `PLAN.md` §12): one
  entity failing to chunk, embed, or persist does not abort the rest of
  the case. It is recorded as a `FAILED` `ai_knowledge_source` row with
  the error message (never entity content) in `source_metadata`, and its
  last-known-good chunks (if any) are left untouched rather than deleted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from quick_chat_api.core.constants.constants import AIKnowledgeStatus
from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.exceptions import EmbeddingProviderError
from quick_chat_api.core.llm.embedding.factory import get_embedding_provider
from quick_chat_api.core.models.agency.agency import AIKnowledgeChunk, AIKnowledgeSource
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


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _indexing_key(provider: EmbeddingProvider) -> str:
    """Fingerprint of "how" a document was indexed, not "what" it contains.

    Stored in `source_metadata["indexing_key"]` and compared alongside
    `content_hash` on the next run -- content can be byte-identical but
    still need re-embedding if the model or chunking strategy changed.
    """
    return f"{settings.EMBEDDING_PROVIDER}|{settings.EMBEDDING_MODEL}|{settings.EMBEDDING_VERSION}|{settings.CHUNKING_STRATEGY}|{settings.CHUNKING_VERSION}"


class IngestionOutcomeKind(StrEnum):
    """What happened to one discovered entity during a single `ingest_case` run.

    Distinct from `AIKnowledgeStatus`: this is the in-memory run report
    handed back to the caller, not the persisted lifecycle status.
    """

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
class _ExistingSourceSnapshot:
    content_hash: str | None
    indexing_key: str | None
    status: str


@dataclass(frozen=True)
class _PreparedWrite:
    entity: DiscoveredEntity
    content_hash: str
    chunks: list[Chunk]
    vectors: list[list[float]]


@dataclass(frozen=True)
class _FailedWrite:
    entity: DiscoveredEntity
    content_hash: str | None
    error: str


class CaseIngestionService:
    """Runs the discover -> chunk -> embed -> persist pipeline for one case.

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
        """Soft-deletes every `ai_knowledge_source` row for `case_id`.

        Sets `status=DELETED` and `is_active=False`. The latter reuses the
        project's existing global active-record filter (`CLAUDE.md` §9), so
        future retrieval queries stop seeing these rows automatically,
        without retrieval needing its own `status` check. Chunks are purged
        outright -- they have no lifecycle independent of their document.

        Returns the number of `ai_knowledge_source` rows soft-deleted.
        """
        async with session_context(self._engine, self._agency) as session:
            stmt = (
                select(AIKnowledgeSource)
                .where(AIKnowledgeSource.case_record_id == case_id)
                .options(selectinload(AIKnowledgeSource.chunks))
            )
            result = await session.execute(stmt)
            sources = result.scalars().all()
            for source in sources:
                source.status = AIKnowledgeStatus.DELETED.value
                source.is_active = False
                source.chunks.clear()
            await session.commit()
            return len(sources)

    async def _run(self, case_id: UUID, *, force: bool) -> CaseIngestionResult:
        provider = get_embedding_provider()
        chunker = get_chunker()
        indexing_key = _indexing_key(provider)

        discovered, existing_by_key = await self._discover_and_load_existing(case_id)

        prepared: list[_PreparedWrite] = []
        failed: list[_FailedWrite] = []
        outcomes: list[EntityIngestionOutcome] = []

        for entity in discovered:
            content_hash = _content_hash(entity.document.content)
            key: _SourceKey = (
                entity.source_table,
                entity.source_id,
                entity.source_type,
            )
            existing = existing_by_key.get(key)

            if (
                not force
                and existing is not None
                and existing.status == AIKnowledgeStatus.COMPLETED.value
                and existing.content_hash == content_hash
                and existing.indexing_key == indexing_key
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
            except (ChunkingError, EmbeddingProviderError) as exc:
                logger.error(
                    "entity embedding failed",
                    extra={
                        "case_id": str(case_id),
                        "source_type": entity.source_type,
                        "source_id": entity.source_id,
                        "error": str(exc),
                    },
                )
                failed.append(
                    _FailedWrite(
                        entity=entity, content_hash=content_hash, error=str(exc)
                    )
                )
                continue

            prepared.append(
                _PreparedWrite(
                    entity=entity,
                    content_hash=content_hash,
                    chunks=chunks,
                    vectors=vectors,
                )
            )

        outcomes.extend(await self._persist(case_id, prepared, failed, indexing_key))
        return CaseIngestionResult(case_id=case_id, outcomes=outcomes)

    async def _discover_and_load_existing(
        self, case_id: UUID
    ) -> tuple[list[DiscoveredEntity], dict[_SourceKey, _ExistingSourceSnapshot]]:
        async with session_context(self._engine, self._agency) as session:
            adapter = CaseKnowledgeSourceAdapter(session)
            discovered = await adapter.discover_all(case_id)

            stmt = select(AIKnowledgeSource).where(
                AIKnowledgeSource.case_record_id == case_id
            )
            result = await session.execute(stmt)
            existing_by_key = {
                (
                    row.source_table,
                    row.source_id,
                    row.source_type,
                ): _ExistingSourceSnapshot(
                    content_hash=row.content_hash,
                    indexing_key=(row.source_metadata or {}).get("indexing_key"),
                    status=row.status,
                )
                for row in result.scalars().all()
            }
        return discovered, existing_by_key

    async def _persist(
        self,
        case_id: UUID,
        prepared: list[_PreparedWrite],
        failed: list[_FailedWrite],
        indexing_key: str,
    ) -> list[EntityIngestionOutcome]:
        outcomes: list[EntityIngestionOutcome] = []
        async with session_context(self._engine, self._agency) as session:
            for item in prepared:
                try:
                    async with session.begin_nested():
                        await self._write_embedded(session, item, indexing_key)
                except SQLAlchemyError as exc:
                    logger.error(
                        "entity persistence failed",
                        extra={
                            "case_id": str(case_id),
                            "source_type": item.entity.source_type,
                            "source_id": item.entity.source_id,
                            "error": str(exc),
                        },
                    )
                    failed.append(
                        _FailedWrite(
                            entity=item.entity,
                            content_hash=item.content_hash,
                            error=str(exc),
                        )
                    )
                    continue

                outcomes.append(
                    EntityIngestionOutcome(
                        source_type=item.entity.source_type,
                        source_id=item.entity.source_id,
                        kind=IngestionOutcomeKind.EMBEDDED,
                        chunk_count=len(item.chunks),
                    )
                )

            for item in failed:
                try:
                    async with session.begin_nested():
                        await self._write_failed(session, item)
                except SQLAlchemyError as exc:
                    # The FAILED-status write itself failed (e.g. the DB is
                    # unreachable) -- still report the original embedding/
                    # chunking error, since that's the actionable one; this
                    # is logged separately so the write failure isn't lost.
                    logger.error(
                        "failed-status write itself failed",
                        extra={
                            "case_id": str(case_id),
                            "source_type": item.entity.source_type,
                            "source_id": item.entity.source_id,
                            "error": str(exc),
                        },
                    )
                outcomes.append(
                    EntityIngestionOutcome(
                        source_type=item.entity.source_type,
                        source_id=item.entity.source_id,
                        kind=IngestionOutcomeKind.FAILED,
                        error=item.error,
                    )
                )

            await session.commit()
        return outcomes

    async def _write_embedded(
        self,
        session: AsyncSession,
        item: _PreparedWrite,
        indexing_key: str,
    ) -> None:
        source_id = await self._upsert_source(
            session,
            entity=item.entity,
            content_hash=item.content_hash,
            status=AIKnowledgeStatus.COMPLETED,
            extra_metadata={"indexing_key": indexing_key},
        )

        # Full replace rather than per-chunk upsert: re-chunking can change
        # the chunk count, which would otherwise leave stale trailing chunks
        # from a previous, larger split behind.
        await session.execute(
            delete(AIKnowledgeChunk).where(AIKnowledgeChunk.document_id == source_id)
        )
        session.add_all(
            AIKnowledgeChunk(
                document_id=source_id,
                case_record_id=item.entity.case_record_id,
                chunk_index=chunk.index,
                content=chunk.content,
                content_hash=_content_hash(chunk.content),
                token_count=chunk.token_count,
                embedding=vector,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_version=settings.EMBEDDING_VERSION,
                metadata_=chunk.metadata,
            )
            for chunk, vector in zip(item.chunks, item.vectors, strict=True)
        )

    async def _write_failed(self, session: AsyncSession, item: _FailedWrite) -> None:
        # Chunks are deliberately left untouched: a failed re-embed attempt
        # should not destroy the last-known-good, still-retrievable index
        # for this entity.
        await self._upsert_source(
            session,
            entity=item.entity,
            content_hash=item.content_hash,
            status=AIKnowledgeStatus.FAILED,
            extra_metadata={"error": item.error},
        )

    async def _upsert_source(
        self,
        session: AsyncSession,
        *,
        entity: DiscoveredEntity,
        content_hash: str | None,
        status: AIKnowledgeStatus,
        extra_metadata: dict,
    ) -> UUID:
        document = entity.document
        source_metadata = {**document.metadata, **extra_metadata}
        stmt = (
            pg_insert(AIKnowledgeSource)
            .values(
                case_record_id=entity.case_record_id,
                source_type=entity.source_type,
                source_table=entity.source_table,
                source_id=entity.source_id,
                title=document.title,
                content_hash=content_hash,
                source_metadata=source_metadata,
                status=status.value,
            )
            .on_conflict_do_update(
                index_elements=["source_table", "source_id", "source_type"],
                set_={
                    "case_record_id": entity.case_record_id,
                    "title": document.title,
                    "content_hash": content_hash,
                    "source_metadata": source_metadata,
                    "status": status.value,
                    # Un-delete: a source that comes back after being
                    # soft-deleted (`delete_case_index`) becomes visible
                    # again once it's successfully re-ingested.
                    "is_active": True,
                },
            )
            .returning(AIKnowledgeSource.id)
        )
        result = await session.execute(stmt)
        return result.scalar_one()
