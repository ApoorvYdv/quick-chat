import pytest

from quick_chat_api.modules.rag.structured.cross_case import (
    CaseList,
    filter_cases,
    filter_cases_by_appearance,
    find_cases_by_party,
)
from quick_chat_api.modules.rag.structured.financial import (
    CaseScopeError,
    get_payment_summaries,
)
from tests.modules.rag.test_structured import _session


async def test_unfiltered_lists_are_rejected() -> None:
    with pytest.raises(ValueError):
        await filter_cases(_session())
    with pytest.raises(ValueError):
        await filter_cases_by_appearance(_session())


async def test_blank_party_name_queries_nothing() -> None:
    session = _session()
    assert await find_cases_by_party(session, "  ") == CaseList()
    session.execute.assert_not_called()


async def test_payment_summaries_reject_ids_outside_tenant() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    result = MagicMock()
    result.scalar_one.return_value = 0
    session = AsyncMock()
    session.execute.return_value = result
    with pytest.raises(CaseScopeError):
        await get_payment_summaries(session, [uuid4()])
