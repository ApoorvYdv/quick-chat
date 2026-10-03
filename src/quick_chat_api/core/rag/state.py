"""Graph state. Tenant (`agency`) is copied from `RequestContext` only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from quick_chat_api.core.schemas.chat import Citation


@dataclass(frozen=True)
class EvidenceItem:
    agency: str
    case_record_id: UUID
    source_table: str
    source_record_id: str
    chunk_id: UUID
    text: str
    score: float = 0.0
    rerank_score: float | None = None


class PipelineState(TypedDict, total=False):
    question: str
    agency: str
    session_id: UUID
    requested_case_id: UUID | None
    case_number: str | None
    mode: str
    resolved_case_ids: list[UUID]
    needs_clarification: str | None
    evidence: list[EvidenceItem]
    contexts: list[str]
    answer: str
    citations: list[Citation]
    conflicts: list[str]
    insufficient_information: bool
