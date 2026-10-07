"""Structured hearing/appearance queries (dates are not answerable by vector search)."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.models.agency.agency import CaseAppearance
from quick_chat_api.utils.helper import get_client_timezone

__all__ = ["get_appearances", "get_next_appearance"]


def _ordered(case_id: UUID):
    return (
        select(CaseAppearance)
        .where(CaseAppearance.case_record_id == case_id)
        .order_by(CaseAppearance.due_date.asc().nulls_last(), CaseAppearance.id)
    )


async def get_appearances(session: AsyncSession, case_id: UUID) -> list[CaseAppearance]:
    """All appearances for the case, soonest first; the session is already tenant-bound."""
    return list((await session.execute(_ordered(case_id))).scalars().all())


async def get_next_appearance(
    session: AsyncSession, case_id: UUID, today: date | None = None
) -> CaseAppearance | None:
    """Earliest appearance due today or later, with `today` taken in the agency timezone."""
    today = today or datetime.now(get_client_timezone()).date()
    stmt = _ordered(case_id).where(CaseAppearance.due_date >= today).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()
