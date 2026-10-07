"""Structured payment queries (balances/totals are not answerable by vector search)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.models.agency.agency import PaymentRecord

__all__ = ["PaymentSummary", "get_payment_summary"]


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
