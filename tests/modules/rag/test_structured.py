import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from quick_chat_api.core.constants.constants import (
    SOURCE_TYPE_DOMAIN,
    AIKnowledgeSourceType,
    Domain,
)
from quick_chat_api.core.models.agency.agency import PaymentRecord
from quick_chat_api.modules.rag.structured.financial import get_payment_summary
from quick_chat_api.modules.rag.structured.hearings import (
    get_appearances,
    get_next_appearance,
)


def _session(rows=(), one=None) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(rows)
    result.scalar_one_or_none.return_value = one
    session = AsyncMock()
    session.execute.return_value = result
    return session


def test_total_paid_excludes_void() -> None:
    rows = [
        PaymentRecord(amount=Decimal("10.50"), void=False),
        PaymentRecord(amount=Decimal("99.00"), void=True),
        PaymentRecord(amount=Decimal("4.50"), void=False),
    ]
    summary = asyncio.run(get_payment_summary(_session(rows), uuid4()))
    assert summary.total_paid == Decimal("15.00")
    assert len(summary.payments) == 3


def test_no_payments_total_is_zero() -> None:
    assert asyncio.run(get_payment_summary(_session(), uuid4())).total_paid == 0


def test_next_appearance_filters_from_today_in_sql() -> None:
    session = _session()
    today = date(2026, 10, 7)
    assert asyncio.run(get_next_appearance(session, [uuid4()], today=today)) == []
    stmt = str(
        session.execute.call_args.args[0].compile(
            compile_kwargs={"literal_binds": False}
        )
    )
    assert "due_date >=" in stmt


def test_appearances_require_a_case_reference() -> None:
    with pytest.raises(ValueError):
        asyncio.run(get_appearances(_session()))


def test_appearances_accept_case_number_alone() -> None:
    session = _session()
    asyncio.run(get_appearances(session, case_numbers=["2026-2184-CR-CR"]))
    assert "case_number IN" in str(session.execute.call_args.args[0])


def test_domain_map_matches_plan() -> None:
    T = AIKnowledgeSourceType
    assert SOURCE_TYPE_DOMAIN[T.APPEARANCE] is Domain.HEARINGS
    assert SOURCE_TYPE_DOMAIN[T.DISPOSITION] is Domain.HEARINGS
    assert SOURCE_TYPE_DOMAIN[T.CHARGE] is Domain.CASE


def test_case_level_types_map_to_case_domain() -> None:
    T = AIKnowledgeSourceType
    assert {SOURCE_TYPE_DOMAIN[t] for t in (T.CRIMINAL, T.VEHICLE, T.ADDRESS)} == {
        Domain.CASE
    }
