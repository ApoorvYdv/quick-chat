"""Structured hearing/appearance queries (dates are not answerable by vector search)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.models.agency.agency import CaseAppearance, CaseRecord
from quick_chat_api.utils.helper import get_client_timezone

__all__ = ["get_appearances", "get_next_appearance"]


def _ordered(case_ids: Sequence[UUID], case_numbers: Sequence[str]):
    if not case_ids and not case_numbers:
        raise ValueError("pass case_ids or case_numbers")
    match = or_(
        CaseAppearance.case_record_id.in_(case_ids),
        CaseRecord.case_number.in_(case_numbers),
    )
    return (
        select(CaseAppearance)
        .join(CaseRecord, CaseRecord.id == CaseAppearance.case_record_id)
        .where(match)
        .order_by(CaseAppearance.due_date.asc().nulls_last(), CaseAppearance.id)
    )


async def get_appearances(
    session: AsyncSession,
    case_ids: Sequence[UUID] = (),
    case_numbers: Sequence[str] = (),
) -> list[CaseAppearance]:
    """Appearances for the cases named by id and/or case number, soonest first; the session is already tenant-bound."""
    stmt = _ordered(case_ids, case_numbers)
    return list((await session.execute(stmt)).scalars().all())


async def get_next_appearance(
    session: AsyncSession,
    case_ids: Sequence[UUID] = (),
    case_numbers: Sequence[str] = (),
    today: date | None = None,
) -> list[CaseAppearance]:
    """Earliest appearance due today or later for each matched case, with `today` taken in the agency timezone."""
    today = today or datetime.now(get_client_timezone()).date()
    stmt = _ordered(case_ids, case_numbers).where(CaseAppearance.due_date >= today)
    upcoming = (await session.execute(stmt)).scalars().all()
    first: dict[UUID, CaseAppearance] = {}
    for a in upcoming:  # soonest first, so the first seen per case is its next
        first.setdefault(a.case_record_id, a)
    return list(first.values())
