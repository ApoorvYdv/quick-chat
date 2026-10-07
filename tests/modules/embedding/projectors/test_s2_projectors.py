import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from quick_chat_api.core.constants.constants import (
    SOURCE_TYPE_GROUPS,
    AIKnowledgeSourceType,
)
from quick_chat_api.core.models.agency.agency import (
    AddressDetail,
    CaseAppearance,
    CaseCharge,
    CaseRecord,
    Criminal,
    ImposedDisposition,
    ImposedSanction,
    PartyDetail,
    PaymentRecord,
    VehicleDetail,
)
from quick_chat_api.modules.embedding.db_adapters import CaseKnowledgeSourceAdapter
from quick_chat_api.modules.embedding.projectors import get_projector


def _project(source_type: AIKnowledgeSourceType, entity: object) -> str:
    return get_projector(source_type.value).project(entity).content


def _case(**kw: object) -> CaseRecord:
    case = CaseRecord(
        id=uuid4(), case_number="CR-1", case_type="CRIMINAL", case_title="State v. Doe"
    )
    case.parties = []
    case.charges = []
    case.appearance_history = []
    case.payment_records = []
    case.vehicles = []
    case.criminal = kw.get("criminal")
    return case


def test_source_type_groups_cover_every_type_exactly_once() -> None:
    grouped = [t for types in SOURCE_TYPE_GROUPS.values() for t in types]
    assert sorted(grouped) == sorted(t.value for t in AIKnowledgeSourceType)


def test_payment_embeds_only_allowed_fields() -> None:
    payment = PaymentRecord(
        amount=Decimal("50.00"),
        currency="USD",
        payee_name="Jane Doe",
        payee_email="jane@example.com",
        payee_address="1 Main St",
        reference_number="REF-9",
        receipt_number="RC-7",
        consider_as_full=True,
        void=False,
        card_last_4="4242",
        card_brand="VISA",
        card_type="CREDIT",
        exp_year="2030",
        exp_month="12",
        payment_method="CARD",
        payment_mode="ONLINE",
        qp_payment_id="QP-SECRET",
        service_fee=Decimal("1.23"),
    )
    content = _project(AIKnowledgeSourceType.PAYMENT, payment)

    for kept in (
        "50.00",
        "USD",
        "Jane Doe",
        "jane@example.com",
        "1 Main St",
        "REF-9",
        "RC-7",
    ):
        assert kept in content
    for excluded in (
        "4242",
        "VISA",
        "CREDIT",
        "2030",
        "CARD",
        "ONLINE",
        "QP-SECRET",
        "1.23",
    ):
        assert excluded not in content


def test_disposition_and_sanction_carry_case_and_charge_context() -> None:
    case = _case()
    charge = CaseCharge(id=uuid4(), charge_description="Speeding")
    charge.case_record = case
    charge.imposed_disposition = ImposedDisposition(
        id=uuid4(),
        disposition_type="GUILTY",
        finding="Found",
        disposed_on=date(2026, 1, 2),
    )
    charge.imposed_sanctions = [ImposedSanction(id=uuid4(), sanction_type="FINE")]

    disposition = _project(
        AIKnowledgeSourceType.DISPOSITION, charge.imposed_disposition
    )
    sanction = _project(AIKnowledgeSourceType.SANCTION, charge.imposed_sanctions[0])

    assert (
        "CR-1" in disposition and "Speeding" in disposition and "GUILTY" in disposition
    )
    assert "CR-1" in sanction and "Speeding" in sanction and "FINE" in sanction


def test_criminal_vehicle_address_embed_all_fields() -> None:
    criminal = _project(
        AIKnowledgeSourceType.CRIMINAL,
        Criminal(
            is_arrested=True,
            arrest_location="Ignacio",
            warrant_number="W-1",
            observation_text="Officer saw it",
        ),
    )
    vehicle = _project(
        AIKnowledgeSourceType.VEHICLE,
        VehicleDetail(
            vehicle_make="Ford",
            vehicle_plate="ABC123",
            vehicle_vin="VIN999",
            vehicle_state_code="CO",
        ),
    )
    address = _project(
        AIKnowledgeSourceType.ADDRESS,
        AddressDetail(
            address_line_1="1 Main St", city="Ignacio", state="CO", zip_code="81137"
        ),
    )

    for text in ("Ignacio", "W-1", "Officer saw it"):
        assert text in criminal
    for text in ("Ford", "ABC123", "VIN999", "CO"):
        assert text in vehicle
    for text in ("1 Main St", "Ignacio", "81137"):
        assert text in address


def test_discover_all_includes_new_types_with_case_context() -> None:
    case = _case(criminal=Criminal(id=uuid4(), is_arrested=True))
    party = PartyDetail(id=uuid4(), full_name="Jane Doe", party_type="DEFENDANT")
    party.addresses = [AddressDetail(id=uuid4(), city="Ignacio")]
    case.parties = [party]
    charge = CaseCharge(id=uuid4(), charge_description="Speeding")
    charge.imposed_disposition = ImposedDisposition(
        id=uuid4(), disposition_type="GUILTY"
    )
    charge.imposed_sanctions = [ImposedSanction(id=uuid4(), sanction_type="FINE")]
    case.charges = [charge]
    case.payment_records = [PaymentRecord(id=uuid4(), amount=Decimal("5.00"))]
    case.vehicles = [VehicleDetail(id=uuid4(), vehicle_make="Ford")]
    case.appearance_history = [CaseAppearance(id=uuid4(), status="REGISTERED")]

    result = MagicMock()
    result.scalar_one_or_none.return_value = case
    session = AsyncMock()
    session.execute.return_value = result

    discovered = asyncio.run(CaseKnowledgeSourceAdapter(session).discover_all(case.id))

    assert {d.source_type for d in discovered} == {
        t.value for t in AIKnowledgeSourceType
    }
    assert all(d.case_context["case_number"] == "CR-1" for d in discovered)
    assert all(d.case_context["case_title"] == "State v. Doe" for d in discovered)
    assert session.execute.await_count == 1


@pytest.mark.parametrize("source_type", list(AIKnowledgeSourceType))
def test_every_source_type_has_a_projector(source_type: AIKnowledgeSourceType) -> None:
    assert get_projector(source_type.value) is not None
