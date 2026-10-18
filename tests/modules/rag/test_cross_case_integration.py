"""Real Postgres + pg_trgm: cross-case lists, caps, candidates and tenant scope."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

import quick_chat_api.core.database.session_context_manager  # noqa: F401  (is_active filter)
from quick_chat_api.core.constants.constants import CaseAppearanceStatus, PartyType
from quick_chat_api.core.models.agency.agency import (
    AgencyBase,
    CaseAppearance,
    CaseRecord,
    PartyDetail,
)
from quick_chat_api.modules.rag.structured.cross_case import (
    filter_cases,
    filter_cases_by_appearance,
    find_cases_by_party,
)
from quick_chat_api.modules.rag.structured.financial import (
    CaseScopeError,
    get_payment_summaries,
)

pytestmark = pytest.mark.integration

DAY = date(2026, 10, 10)


def _case(number: str, **kw) -> CaseRecord:
    return CaseRecord(case_number=number, case_type="CRIMINAL", case_subtype="x", **kw)


def _party(case: CaseRecord, name: str, dob: date | None, role=PartyType.DEFENDANT):
    return PartyDetail(
        case_record_id=case.id, party_type=role.value, full_name=name, dob=dob
    )


async def _engine(postgres, schema: str):
    engine = create_async_engine(postgres.get_connection_url()).execution_options(
        schema_translate_map={None: schema}
    )
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(AgencyBase.metadata.create_all)
    return engine


async def test_cross_case_lists(postgres) -> None:
    engine = await _engine(postgres, "cross_a")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        maxwell = [_case(f"CR-{i:02d}") for i in range(25)]
        other, same_name, lone = _case("CR-90"), _case("CR-91"), _case("CR-92")
        session.add_all([*maxwell, other, same_name, lone])
        await session.flush()
        session.add_all(
            [
                *(_party(c, "John Maxwell", date(1980, 1, 1)) for c in maxwell),
                _party(other, "Jane Roe", None),
                _party(same_name, "JOHN MAXWELL", date(1990, 5, 5)),
                _party(lone, "Sam Smith", None, PartyType.VICTIM),
                CaseAppearance(
                    case_record_id=other.id,
                    due_date=DAY,
                    status=CaseAppearanceStatus.REGISTERED.value,
                ),
                CaseAppearance(
                    case_record_id=lone.id,
                    due_date=DAY,
                    status=CaseAppearanceStatus.UNREGISTERED.value,
                ),
                CaseAppearance(
                    case_record_id=same_name.id,
                    due_date=date(2026, 10, 11),
                    status=CaseAppearanceStatus.REGISTERED.value,
                ),
            ]
        )
        await session.flush()

        # two people share the name -> candidates, no silent pick (AC-8)
        ambiguous = await find_cases_by_party(session, "john maxwell")
        assert ambiguous.needs_clarification and not ambiguous.cases
        assert {len(c.case_numbers) for c in ambiguous.candidates} == {1, 20}

        # unique person -> cases, capped at 20 with the true total (AC-1, AC-8)
        jane = await find_cases_by_party(session, "JANE ROE", PartyType.DEFENDANT)
        assert [c.case_number for c in jane.cases] == ["CR-90"] and not jane.truncated
        assert await find_cases_by_party(session, "Sam Smith", PartyType.DEFENDANT) == (
            await find_cases_by_party(session, "nobody here")
        )

        # fuzzy-only match is always a candidate, never auto-picked
        typo = await find_cases_by_party(session, "Jane Row")
        assert typo.needs_clarification and typo.candidates[0].full_name == "Jane Roe"

        # status + date must hold on the same appearance (AC-2)
        hit = await filter_cases_by_appearance(
            session, status=CaseAppearanceStatus.REGISTERED, hearing_date=DAY
        )
        assert [c.case_number for c in hit.cases] == ["CR-90"] and hit.total == 1

        listed = await filter_cases(session, case_type="CRIMINAL")
        assert len(listed.cases) == 20 and listed.total == 28 and listed.truncated

        with pytest.raises(CaseScopeError):
            await get_payment_summaries(session, [other.id, uuid4()])
    await engine.dispose()


async def test_lists_do_not_cross_tenants(postgres) -> None:
    a, b = await _engine(postgres, "iso_a"), await _engine(postgres, "iso_b")
    async with AsyncSession(a, expire_on_commit=False) as sa:
        case = _case("CR-A")
        sa.add(case)
        await sa.flush()
        sa.add(_party(case, "Only InA", None))
        await sa.flush()
        case_a = case.id
        assert (await find_cases_by_party(sa, "Only InA")).total == 1
    async with AsyncSession(b, expire_on_commit=False) as sb:
        assert await find_cases_by_party(sb, "Only InA") == await find_cases_by_party(
            sb, "x"
        )
        with pytest.raises(CaseScopeError):
            await get_payment_summaries(sb, [case_a])
    await a.dispose()
    await b.dispose()
