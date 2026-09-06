import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import (
    CaseAppearance,
    CaseCharge,
    CaseRecord,
    PartyDetail,
)
from quick_chat_api.modules.embedding.db_adapters import (
    CaseKnowledgeSourceAdapter,
    CaseNotFoundError,
)


def _case_record(case_id, **overrides: object) -> CaseRecord:
    defaults = dict(id=case_id, case_number="CR-2026-001", case_type="CRIMINAL")
    case = CaseRecord(**{**defaults, **overrides})
    case.parties = overrides.get("parties", [])
    case.charges = overrides.get("charges", [])
    case.appearance_history = overrides.get("appearance_history", [])
    case.payment_records = overrides.get("payment_records", [])
    return case


def _session_returning(entity: CaseRecord | None) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = entity
    session = AsyncMock()
    session.execute.return_value = result
    return session


class TestDiscoverCase:
    def test_returns_case_document(self) -> None:
        case_id = uuid4()
        case = _case_record(case_id, case_title="State v. Doe")
        adapter = CaseKnowledgeSourceAdapter(_session_returning(case))

        discovered = asyncio.run(adapter.discover_case(case_id))

        assert discovered.source_type == AIKnowledgeSourceType.CASE.value
        assert discovered.source_table == "case_record"
        assert discovered.source_id == str(case_id)
        assert discovered.case_record_id == case_id
        assert "State v. Doe" in discovered.document.content

    def test_raises_when_case_missing(self) -> None:
        adapter = CaseKnowledgeSourceAdapter(_session_returning(None))

        with pytest.raises(CaseNotFoundError):
            asyncio.run(adapter.discover_case(uuid4()))


class TestDiscoverChildren:
    def test_discover_parties_projects_each_party(self) -> None:
        case_id = uuid4()
        party = PartyDetail(id=uuid4(), case_record_id=case_id, full_name="Jane Roe")
        case = _case_record(case_id, parties=[party])
        adapter = CaseKnowledgeSourceAdapter(_session_returning(case))

        discovered = asyncio.run(adapter.discover_parties(case_id))

        assert len(discovered) == 1
        assert discovered[0].source_type == AIKnowledgeSourceType.PARTY.value
        assert discovered[0].source_table == "party_detail"
        assert discovered[0].source_id == str(party.id)
        assert discovered[0].case_record_id == case_id

    def test_discover_charges_projects_each_charge(self) -> None:
        case_id = uuid4()
        charge = CaseCharge(
            id=uuid4(),
            case_record_id=case_id,
            charge_code="123",
            charge_description="Speeding",
        )
        case = _case_record(case_id, charges=[charge])
        adapter = CaseKnowledgeSourceAdapter(_session_returning(case))

        discovered = asyncio.run(adapter.discover_charges(case_id))

        assert len(discovered) == 1
        assert discovered[0].source_type == AIKnowledgeSourceType.CHARGE.value
        assert discovered[0].source_id == str(charge.id)

    def test_discover_appearances_projects_each_appearance(self) -> None:
        case_id = uuid4()
        appearance = CaseAppearance(id=uuid4(), case_record_id=case_id)
        case = _case_record(case_id, appearance_history=[appearance])
        adapter = CaseKnowledgeSourceAdapter(_session_returning(case))

        discovered = asyncio.run(adapter.discover_appearances(case_id))

        assert len(discovered) == 1
        assert discovered[0].source_type == AIKnowledgeSourceType.APPEARANCE.value
        assert discovered[0].source_id == str(appearance.id)


class TestDiscoverAll:
    def test_returns_case_summary_and_every_child_entity(self) -> None:
        case_id = uuid4()
        party = PartyDetail(id=uuid4(), case_record_id=case_id, full_name="Jane Roe")
        charge = CaseCharge(
            id=uuid4(),
            case_record_id=case_id,
            charge_code="123",
            charge_description="Speeding",
        )
        appearance = CaseAppearance(id=uuid4(), case_record_id=case_id)
        case = _case_record(
            case_id,
            parties=[party],
            charges=[charge],
            appearance_history=[appearance],
        )
        adapter = CaseKnowledgeSourceAdapter(_session_returning(case))

        discovered = asyncio.run(adapter.discover_all(case_id))

        source_types = [entity.source_type for entity in discovered]
        assert source_types == [
            AIKnowledgeSourceType.CASE.value,
            AIKnowledgeSourceType.CASE_SUMMARY.value,
            AIKnowledgeSourceType.PARTY.value,
            AIKnowledgeSourceType.CHARGE.value,
            AIKnowledgeSourceType.APPEARANCE.value,
        ]
        assert all(entity.case_record_id == case_id for entity in discovered)

    def test_raises_when_case_missing(self) -> None:
        adapter = CaseKnowledgeSourceAdapter(_session_returning(None))

        with pytest.raises(CaseNotFoundError):
            asyncio.run(adapter.discover_all(uuid4()))
