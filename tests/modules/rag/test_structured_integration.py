"""Real Postgres: structured queries against seeded rows in a throwaway agency schema."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import quick_chat_api.core.database.session_context_manager  # noqa: F401  (is_active filter)
from quick_chat_api.core.models.agency.agency import (
    AgencyBase,
    CaseAppearance,
    CaseRecord,
    PaymentRecord,
)
from quick_chat_api.modules.rag.structured.case import get_cases_by_number
from quick_chat_api.modules.rag.structured.financial import get_payment_summary
from quick_chat_api.modules.rag.structured.hearings import (
    get_appearances,
    get_next_appearance,
)

pytestmark = pytest.mark.integration

TODAY = date(2026, 10, 7)


def _case(number: str) -> CaseRecord:
    return CaseRecord(case_number=number, case_type="CRIMINAL", case_subtype="x")


async def test_structured_queries_are_case_scoped(postgres) -> None:
    engine = create_async_engine(postgres.get_connection_url()).execution_options(
        schema_translate_map={None: "struct_a"}
    )
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA struct_a"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(AgencyBase.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        a, b, dup = _case("CR-1"), _case("CR-2"), _case("CR-1")
        session.add_all([a, b, dup])
        await session.flush()
        session.add_all(
            [
                CaseAppearance(case_record_id=a.id, due_date=date(2026, 9, 1)),
                CaseAppearance(case_record_id=a.id, due_date=date(2026, 12, 1)),
                CaseAppearance(case_record_id=a.id, due_date=date(2026, 11, 1)),
                CaseAppearance(case_record_id=b.id, due_date=date(2026, 10, 8)),
                PaymentRecord(case_record_id=a.id, amount=Decimal("10.00")),
                PaymentRecord(case_record_id=a.id, amount=Decimal("50.00"), void=True),
                PaymentRecord(case_record_id=b.id, amount=Decimal("7.00")),
            ]
        )
        await session.flush()

        # case number is not unique: every match comes back, none silently chosen
        assert len(await get_cases_by_number(session, "CR-1")) == 2
        assert await get_cases_by_number(session, "nope") == []

        due = [x.due_date for x in await get_appearances(session, a.id)]
        assert due == sorted(due) and len(due) == 3
        nxt = await get_next_appearance(session, a.id, today=TODAY)
        assert nxt is not None and nxt.due_date == date(2026, 11, 1)
        assert await get_next_appearance(session, a.id, today=date(2027, 1, 1)) is None

        summary = await get_payment_summary(session, a.id)
        assert summary.total_paid == Decimal("10.00") and len(summary.payments) == 2
    await engine.dispose()
