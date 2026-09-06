from datetime import date
from decimal import Decimal

import pytest

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import (
    CaseAppearance,
    CaseCharge,
    CaseRecord,
    ImposedDisposition,
    ImposedSanction,
    PartyDetail,
    PaymentRecord,
)
from quick_chat_api.modules.embedding.projectors import (
    UnknownProjectorError,
    get_projector,
)
from quick_chat_api.modules.embedding.projectors.registry import build_projector


def _case_record(**overrides: object) -> CaseRecord:
    defaults = dict(
        case_number="CR-2026-001",
        case_type="CRIMINAL",
        case_subtype="misdemeanor",
        case_status="OPEN",
    )
    case = CaseRecord(**{**defaults, **overrides})
    case.parties = case.parties if "parties" in overrides else []
    case.charges = case.charges if "charges" in overrides else []
    case.appearance_history = (
        case.appearance_history if "appearance_history" in overrides else []
    )
    case.payment_records = (
        case.payment_records if "payment_records" in overrides else []
    )
    return case


class TestRegistry:
    def test_unknown_source_type_raises_with_available_names(self) -> None:
        with pytest.raises(UnknownProjectorError, match="case_summary"):
            build_projector("not-a-real-source-type")

    def test_get_projector_returns_same_cached_instance(self) -> None:
        first = get_projector(AIKnowledgeSourceType.CASE.value)
        second = get_projector(AIKnowledgeSourceType.CASE.value)
        assert first is second


class TestCaseRecordProjector:
    def test_projects_case_level_fields(self) -> None:
        case = _case_record(
            case_title="State v. Doe",
            incident_date=date(2026, 1, 1),
            incident_location="Main St",
            additional_notes="defendant was cooperative",
        )

        doc = get_projector(AIKnowledgeSourceType.CASE.value).project(case)

        assert "CR-2026-001" in doc.content
        assert "State v. Doe" in doc.content
        assert "Main St" in doc.content
        assert "defendant was cooperative" in doc.content
        assert doc.metadata["case_number"] == "CR-2026-001"

    def test_omits_none_fields(self) -> None:
        case = _case_record()

        doc = get_projector(AIKnowledgeSourceType.CASE.value).project(case)

        assert "Notes:" not in doc.content
        assert "Issuer:" not in doc.content


class TestPartyProjector:
    def test_never_embeds_ssn_or_license_number(self) -> None:
        party = PartyDetail(
            party_type="DEFENDANT",
            full_name="John Doe",
            ssn_id="123-45-6789",
            license_number="LIC-SECRET-123",
            phone_number="555-1234",
        )

        doc = get_projector(AIKnowledgeSourceType.PARTY.value).project(party)

        assert "123-45-6789" not in doc.content
        assert "LIC-SECRET-123" not in doc.content
        assert "John Doe" in doc.content
        assert "555-1234" in doc.content

    def test_includes_case_context_when_relationship_loaded(self) -> None:
        case = _case_record()
        party = PartyDetail(party_type="DEFENDANT", full_name="Jane Doe")
        party.case_record = case

        doc = get_projector(AIKnowledgeSourceType.PARTY.value).project(party)

        assert doc.metadata["case_number"] == "CR-2026-001"

    def test_no_case_context_when_relationship_not_loaded(self) -> None:
        party = PartyDetail(party_type="DEFENDANT", full_name="Jane Doe")

        doc = get_projector(AIKnowledgeSourceType.PARTY.value).project(party)

        assert doc.metadata["case_number"] is None


class TestChargeProjector:
    def test_includes_disposition_and_sanction_context(self) -> None:
        charge = CaseCharge(
            charge_code="C1", charge_description="Speeding", charge_type="TRAFFIC"
        )
        charge.imposed_disposition = ImposedDisposition(
            disposition_type="GUILTY", finding="Guilty as charged"
        )
        charge.imposed_sanctions = [
            ImposedSanction(sanction_type="FINE", due_date=date(2026, 6, 1))
        ]

        doc = get_projector(AIKnowledgeSourceType.CHARGE.value).project(charge)

        assert "Guilty as charged" in doc.content
        assert "FINE" in doc.content

    def test_omits_disposition_section_when_absent(self) -> None:
        charge = CaseCharge(
            charge_code="C1", charge_description="Speeding", charge_type="TRAFFIC"
        )

        doc = get_projector(AIKnowledgeSourceType.CHARGE.value).project(charge)

        assert "Disposition:" not in doc.content
        assert "Sanctions:" not in doc.content


class TestAppearanceProjector:
    def test_includes_legal_representative_name_only(self) -> None:
        representative = PartyDetail(
            party_type="ATTORNEY", full_name="Alex Attorney", ssn_id="999-99-9999"
        )
        appearance = CaseAppearance(hearing_types=["ARRAIGNMENT"], status="REGISTERED")
        appearance.legal_representative = representative

        doc = get_projector(AIKnowledgeSourceType.APPEARANCE.value).project(appearance)

        assert "Alex Attorney" in doc.content
        assert "999-99-9999" not in doc.content


class TestCaseSummaryProjector:
    def test_composes_all_related_entities(self) -> None:
        charge = CaseCharge(
            charge_code="C1", charge_description="Speeding", charge_type="TRAFFIC"
        )
        appearance = CaseAppearance(hearing_types=["ARRAIGNMENT"], status="REGISTERED")
        party = PartyDetail(party_type="DEFENDANT", full_name="John Doe")
        payment = PaymentRecord(
            amount=Decimal("50.00"),
            currency="USD",
            void=False,
            card_last_4="1111",
            card_brand="VISA",
        )
        case = _case_record(
            parties=[party],
            charges=[charge],
            appearance_history=[appearance],
            payment_records=[payment],
        )

        doc = get_projector(AIKnowledgeSourceType.CASE_SUMMARY.value).project(case)

        assert "John Doe" in doc.content
        assert "Speeding" in doc.content
        assert "ARRAIGNMENT" in doc.content
        assert "Total paid: 50.00" in doc.content
        assert doc.metadata["party_count"] == 1
        assert doc.metadata["charge_count"] == 1

    def test_never_embeds_payment_card_details(self) -> None:
        payment = PaymentRecord(
            amount=Decimal("25.00"),
            currency="USD",
            void=False,
            card_last_4="4242",
            card_brand="MASTERCARD",
        )
        case = _case_record(payment_records=[payment])

        doc = get_projector(AIKnowledgeSourceType.CASE_SUMMARY.value).project(case)

        assert "4242" not in doc.content
        assert "MASTERCARD" not in doc.content

    def test_excludes_voided_payments_from_total(self) -> None:
        voided = PaymentRecord(amount=Decimal("100.00"), currency="USD", void=True)
        case = _case_record(payment_records=[voided])

        doc = get_projector(AIKnowledgeSourceType.CASE_SUMMARY.value).project(case)

        assert "Payments:" not in doc.content

    def test_no_payments_section_when_no_payments(self) -> None:
        case = _case_record()

        doc = get_projector(AIKnowledgeSourceType.CASE_SUMMARY.value).project(case)

        assert "Payments:" not in doc.content
