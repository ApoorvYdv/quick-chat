"""Retrieval: query embedding, vector search, and Postgres hydration.

Closes `PLAN.md`'s long-open retrieval gap (A4). Two retrieval paths, per
`.claude/rules/rag.md`:

- `retrieve()` -- semantic search for narrative/discovery questions. Embeds
  the query, searches the tenant's Qdrant collection, then hydrates full
  content/metadata from Postgres by id (Postgres is the source of truth for
  chunk content; Qdrant only ever holds vectors + filter payload).
- `get_cases_by_number()` -- deterministic structured lookup for questions
  anchored on a case number, eager-loading the entities (parties, charges,
  appearances, payments) needed to answer case/party/charge/hearing/payment
  questions without further round trips.

Deciding *which* path a given question needs is Phase B's job (a
LangGraph-based agent router) -- this module only implements the two
retrieval primitives, per PLAN.md's "Architectural Evolution" section.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from quick_chat_api.core.constants.constants import AIKnowledgeStatus
from quick_chat_api.core.llm.embedding.factory import get_embedding_provider
from quick_chat_api.core.models.agency.agency import (
    AIKnowledgeChunk,
    CaseCharge,
    CaseRecord,
)
from quick_chat_api.core.vectorstore.base import VectorFilter
from quick_chat_api.core.vectorstore.factory import get_vector_store

__all__ = ["RetrievedChunk", "get_cases_by_number", "retrieve"]


@dataclass(frozen=True)
class RetrievedChunk:
    """One semantically retrieved chunk, hydrated from Postgres."""

    id: UUID
    content: str
    score: float
    source_type: str
    source_table: str
    source_id: str
    case_record_id: UUID | None
    document_id: UUID
    chunk_index: int
    metadata: dict


async def retrieve(
    session: AsyncSession,
    agency: str,
    query: str,
    *,
    case_record_id: UUID | None = None,
    source_types: list[str] | None = None,
    top_k: int = 20,
) -> list[RetrievedChunk]:
    """Semantic retrieval, ranked by similarity to `query`.

    Tenant isolation is enforced twice: `agency` selects the Qdrant
    collection, and `session` must already be schema-scoped to the same
    agency by the caller's `session_context()`. `case_record_id`/
    `source_types` narrow the search server-side (never a global search
    filtered afterward in Python), per `.claude/rules/rag.md`.
    """
    query_vector = get_embedding_provider().embed_query(query)
    filter_ = VectorFilter(
        case_record_id=case_record_id,
        source_types=source_types,
        status=AIKnowledgeStatus.COMPLETED.value,
        is_active=True,
    )
    hits = await asyncio.to_thread(
        get_vector_store().search, agency, query_vector, filter_, top_k
    )
    if not hits:
        return []

    scores_by_id = {hit.id: hit.score for hit in hits}
    stmt = (
        select(AIKnowledgeChunk)
        .where(AIKnowledgeChunk.id.in_(scores_by_id))
        .options(selectinload(AIKnowledgeChunk.document))
    )
    result = await session.execute(stmt)
    chunks_by_id = {chunk.id: chunk for chunk in result.scalars().all()}

    # Ordered by Qdrant's ranking; a hit missing from Postgres (a race with
    # a concurrent delete/re-embed between search and hydration) is dropped
    # rather than raising -- the source of truth simply no longer has it.
    return [
        RetrievedChunk(
            id=chunk.id,
            content=chunk.content,
            score=scores_by_id[chunk.id],
            source_type=chunk.document.source_type,
            source_table=chunk.document.source_table,
            source_id=chunk.document.source_id,
            case_record_id=chunk.case_record_id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            metadata=chunk.metadata_,
        )
        for hit in hits
        if (chunk := chunks_by_id.get(hit.id)) is not None
    ]


async def get_cases_by_number(
    session: AsyncSession, case_number: str
) -> list[CaseRecord]:
    """Deterministic lookup for questions anchored on a case number.

    Eager-loads parties/charges/appearances/payments so one call can answer
    case/party/charge/hearing/payment questions without further round
    trips. `case_number` has no uniqueness constraint at the DB level, so
    this returns every match rather than picking one (`CLAUDE.md` §13: do
    not silently select a record when more than one exists).
    """
    stmt = (
        select(CaseRecord)
        .where(CaseRecord.case_number == case_number)
        .options(
            selectinload(CaseRecord.parties),
            selectinload(CaseRecord.charges).selectinload(
                CaseCharge.imposed_disposition
            ),
            selectinload(CaseRecord.charges).selectinload(
                CaseCharge.imposed_sanctions
            ),
            selectinload(CaseRecord.appearance_history),
            selectinload(CaseRecord.payment_records),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
