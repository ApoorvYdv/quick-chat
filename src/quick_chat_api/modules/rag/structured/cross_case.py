"""Structured cross-case lists (by party, case attributes, appearance status/date).

Every query runs on the caller's tenant-bound session; nothing here takes an agency.
Lists are capped, and carry the true total plus a truncation flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.constants.constants import (
    CaseAppearanceStatus,
    CaseStatus,
    PartyType,
)
from quick_chat_api.core.models.agency.agency import (
    CaseAppearance,
    CaseRecord,
    PartyDetail,
)
from quick_chat_api.settings.config import settings

__all__ = [
    "CaseList",
    "CaseRef",
    "PartyCandidate",
    "filter_cases",
    "filter_cases_by_appearance",
    "find_cases_by_party",
]

CaseDateField = Literal["incident_date", "issue_date", "hearing_date"]


@dataclass(frozen=True)
class CaseRef:
    case_id: UUID
    case_number: str
    case_type: str
    case_status: str
    hearing_date: date | None


@dataclass(frozen=True)
class PartyCandidate:
    """One plausible person; `case_numbers` lets the user pick (ssn_id is never exposed)."""

    full_name: str
    dob: date | None
    case_numbers: tuple[str, ...]


@dataclass(frozen=True)
class CaseList:
    cases: tuple[CaseRef, ...] = ()
    total: int = 0
    truncated: bool = False
    candidates: tuple[PartyCandidate, ...] = ()

    @property
    def needs_clarification(self) -> bool:
        return bool(self.candidates)


async def _list_cases(session: AsyncSession, *where: ColumnElement[bool]) -> CaseList:
    cap = settings.CROSS_CASE_LIST_CAP
    total = (
        await session.execute(
            select(func.count()).select_from(CaseRecord).where(*where)
        )
    ).scalar_one()
    stmt = (
        select(CaseRecord)
        .where(*where)
        .order_by(CaseRecord.case_number, CaseRecord.id)
        .limit(cap)
    )
    rows = (await session.execute(stmt)).scalars().all()
    cases = tuple(
        CaseRef(r.id, r.case_number, r.case_type, r.case_status, r.hearing_date)
        for r in rows
    )
    return CaseList(cases=cases, total=total, truncated=total > len(cases))


def _party_filter(
    name_key: str, dob: date | None, role: PartyType | None
) -> ColumnElement[bool]:
    stmt = select(PartyDetail.case_record_id).where(
        func.lower(PartyDetail.full_name) == name_key,
        PartyDetail.dob.is_not_distinct_from(dob),
    )
    if role:
        stmt = stmt.where(PartyDetail.party_type == role.value)
    return CaseRecord.id.in_(stmt)


async def _candidates(
    session: AsyncSession, groups: Select, role: PartyType | None
) -> tuple[PartyCandidate, ...]:
    out = []
    for name, dob in (await session.execute(groups)).all():
        numbers = (
            await session.execute(
                select(CaseRecord.case_number)
                .where(_party_filter(name.lower(), dob, role))
                .order_by(CaseRecord.case_number)
                .limit(settings.CROSS_CASE_LIST_CAP)
            )
        ).scalars()
        out.append(PartyCandidate(name, dob, tuple(numbers)))
    return tuple(out)


async def find_cases_by_party(
    session: AsyncSession, name: str, role: PartyType | None = None
) -> CaseList:
    """Cases for a party name: case-insensitive exact match, then pg_trgm similarity.

    One exact person -> their cases. Several people, or any fuzzy-only match ->
    candidates and no cases: a person is never picked silently. People are
    identified by (full_name, dob).
    """
    name = name.strip()
    if not name:
        return CaseList()
    key = name.lower()
    role_clause = [PartyDetail.party_type == role.value] if role else []

    people = (
        select(func.min(PartyDetail.full_name), PartyDetail.dob)
        .where(func.lower(PartyDetail.full_name) == key, *role_clause)
        .group_by(func.lower(PartyDetail.full_name), PartyDetail.dob)
    )
    exact = (
        await session.execute(people.limit(settings.PARTY_CANDIDATE_LIMIT + 1))
    ).all()
    if len(exact) == 1:
        return await _list_cases(session, _party_filter(key, exact[0][1], role))
    if exact:
        return CaseList(
            candidates=await _candidates(
                session, people.limit(settings.PARTY_CANDIDATE_LIMIT), role
            )
        )

    # ponytail: similarity() scans party_detail; use the `%` operator to hit the GIN index if this gets slow
    score = func.similarity(PartyDetail.full_name, name)
    fuzzy = (
        select(func.min(PartyDetail.full_name), PartyDetail.dob)
        .where(score >= settings.PARTY_FUZZY_MIN_SIMILARITY, *role_clause)
        .group_by(func.lower(PartyDetail.full_name), PartyDetail.dob)
        .order_by(func.max(score).desc(), func.lower(PartyDetail.full_name))
        .limit(settings.PARTY_CANDIDATE_LIMIT)
    )
    return CaseList(candidates=await _candidates(session, fuzzy, role))


async def filter_cases(
    session: AsyncSession,
    *,
    case_status: CaseStatus | None = None,
    case_type: str | None = None,
    date_field: CaseDateField = "hearing_date",
    date_from: date | None = None,
    date_to: date | None = None,
) -> CaseList:
    """Cross-case filter on case attributes; at least one filter is required."""
    column = getattr(CaseRecord, date_field)
    where = [
        c
        for c in (
            CaseRecord.case_status == case_status.value if case_status else None,
            CaseRecord.case_type == case_type if case_type else None,
            column >= date_from if date_from else None,
            column <= date_to if date_to else None,
        )
        if c is not None
    ]
    if not where:
        raise ValueError("filter_cases needs at least one filter")
    return await _list_cases(session, *where)


async def filter_cases_by_appearance(
    session: AsyncSession,
    *,
    status: CaseAppearanceStatus | None = None,
    hearing_date: date | None = None,
) -> CaseList:
    """Cases with one appearance matching both status and hearing date (`due_date`)."""
    where = [
        c
        for c in (
            CaseAppearance.status == status.value if status else None,
            CaseAppearance.due_date == hearing_date if hearing_date else None,
        )
        if c is not None
    ]
    if not where:
        raise ValueError("filter_cases_by_appearance needs a status or a hearing date")
    matching = select(CaseAppearance.case_record_id).where(*where)
    return await _list_cases(session, CaseRecord.id.in_(matching))
