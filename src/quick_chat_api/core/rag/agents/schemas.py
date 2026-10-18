"""Typed agent outputs. Facts come from tools only, never from model text."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from quick_chat_api.core.rag.state import EvidenceItem
from quick_chat_api.modules.rag.structured.cross_case import CaseList as CrossCaseList


class CaseSummary(BaseModel):
    case_id: UUID
    case_number: str
    case_type: str
    case_status: str
    hearing_date: date | None = None


class PartyCandidateOut(BaseModel):
    full_name: str
    dob: date | None = None
    case_numbers: list[str]


class AppearanceFact(BaseModel):
    case_id: UUID
    appearance_id: UUID
    due_date: date | None = None
    status: str
    hearing_types: list[str] = Field(default_factory=list)
    hearing_result: str | None = None


class PaymentFact(BaseModel):
    payment_id: UUID
    amount: Decimal
    payment_datetime: datetime | None = None
    void: bool


class CasePayments(BaseModel):
    case_id: UUID
    total_paid: Decimal
    payments: list[PaymentFact]


class AgentOutput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    agent: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    rejected_case_ids: list[UUID] = Field(default_factory=list)
    iterations: int = 0


class CaseList(BaseModel):
    cases: list[CaseSummary] = Field(default_factory=list)
    total: int = 0
    truncated: bool = False

    @classmethod
    def from_result(cls, result: CrossCaseList) -> CaseList:
        return cls(
            cases=[CaseSummary(**asdict(c)) for c in result.cases],
            total=result.total,
            truncated=result.truncated,
        )


class CaseAgentOutput(AgentOutput):
    agent: str = "case"
    matches: CaseList = Field(default_factory=CaseList)
    candidates: list[PartyCandidateOut] = Field(default_factory=list)

    @property
    def case_ids(self) -> list[UUID]:
        return [c.case_id for c in self.matches.cases]


class ProceduralAgentOutput(AgentOutput):
    agent: str = "procedural"
    appearances: list[AppearanceFact] = Field(default_factory=list)
    next_appearances: list[AppearanceFact] = Field(default_factory=list)
    matches: CaseList = Field(default_factory=CaseList)

    @property
    def case_ids(self) -> list[UUID]:
        return [c.case_id for c in self.matches.cases]


class FinancialAgentOutput(AgentOutput):
    agent: str = "financial"
    payments: list[CasePayments] = Field(default_factory=list)
