"""Structured payment queries (balances/totals are not answerable by vector search)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.models.agency.agency import CaseRecord, PaymentRecord

__all__ = [
    "CaseScopeError",
    "PaymentSummary",
    "get_payment_summaries",
    "get_payment_summary",
]


class CaseScopeError(RuntimeError):
    """A case id is not visible in the current tenant."""


@dataclass(frozen=True)
class PaymentSummary:
    """Payments for a case plus the total of non-void ones. No balance: no assessed-amount source exists."""

    payments: list[PaymentRecord]
    total_paid: Decimal


async def get_payment_summary(session: AsyncSession, case_id: UUID) -> PaymentSummary:
    stmt = (
        select(PaymentRecord)
        .where(PaymentRecord.case_record_id == case_id)
        .order_by(PaymentRecord.payment_datetime.asc().nulls_last(), PaymentRecord.id)
    )
    payments = list((await session.execute(stmt)).scalars().all())
    total = sum((p.amount for p in payments if not p.void), Decimal("0.00"))
    return PaymentSummary(payments=payments, total_paid=total)


async def get_payment_summaries(
    session: AsyncSession, case_ids: list[UUID]
) -> dict[UUID, PaymentSummary]:
    """Payment summaries for resolved cases; any id outside the tenant raises CaseScopeError."""
    ids = set(case_ids)
    found = (
        await session.execute(select(func.count()).where(CaseRecord.id.in_(ids)))
    ).scalar_one()
    if found != len(ids):
        raise CaseScopeError("case id not found in the current tenant")
    # ponytail: one query per case (list cap is 20); batch into one IN query if it shows in latency
    return {cid: await get_payment_summary(session, cid) for cid in case_ids}
