"""Request/response schemas for the AI-knowledge (re)indexing endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionResult,
    IngestionOutcomeKind,
)


class EntityIngestionOutcomeResponse(BaseModel):
    source_type: str
    source_id: str
    kind: IngestionOutcomeKind
    chunk_count: int = 0
    error: str | None = Field(
        default=None, description="Error message when kind='failed', never entity content"
    )


class CaseIngestionResponse(BaseModel):
    case_id: UUID
    embedded: int
    skipped: int
    failed: int
    outcomes: list[EntityIngestionOutcomeResponse]

    @classmethod
    def from_result(cls, result: CaseIngestionResult) -> CaseIngestionResponse:
        return cls(
            case_id=result.case_id,
            embedded=result.embedded,
            skipped=result.skipped,
            failed=result.failed,
            outcomes=[
                EntityIngestionOutcomeResponse(
                    source_type=o.source_type,
                    source_id=o.source_id,
                    kind=o.kind,
                    chunk_count=o.chunk_count,
                    error=o.error,
                )
                for o in result.outcomes
            ],
        )


class CaseIndexDeleteResponse(BaseModel):
    case_id: UUID
    deleted_sources: int
