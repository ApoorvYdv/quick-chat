from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: UUID
    case_id: UUID | None = None
    case_number: str | None = Field(default=None, max_length=100)
    mode: Literal["auto", "case", "agency_search"] = "auto"


class Citation(BaseModel):
    chunk_id: UUID
    case_record_id: UUID
    source_table: str
    source_record_id: str
    source_type: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    insufficient_information: bool = False
    conflicts: list[str] = Field(default_factory=list)
    resolved_case_ids: list[UUID] = Field(default_factory=list)
    needs_clarification: str | None = None
    trace_id: str
    session_id: UUID
