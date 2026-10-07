"""DB source adapters: discover a case's Phase 2 entities and project them.

Loads business entities from PostgreSQL (tenant-scoped via the caller's
`session_context()`), eager-loads exactly the relationships each projector
in `projectors/providers/` needs, and hands each entity to its projector via
`get_projector(...)`.

Read-only by design: this module never writes and never computes a
`content_hash`. Hashing, the unchanged-skip decision and the vector-store
writes belong to the ingestion service, so the DB read transaction is closed
before the embedding API call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
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
from quick_chat_api.modules.embedding.projectors.base import ProjectedDocument
from quick_chat_api.modules.embedding.projectors.factory import get_projector


class CaseNotFoundError(RuntimeError):
    """Raised when a `case_id` does not resolve to a `CaseRecord` in the current tenant."""


@dataclass(frozen=True)
class DiscoveredEntity:
    """One projected candidate, awaiting hashing/persistence by the ingestion service.

    `source_table` + `source_id` + `source_type` identify the entity, so the
    ingestion service can find its previously indexed points without
    re-deriving identity from the projected content.
    """

    source_type: str
    source_table: str
    source_id: str
    case_record_id: UUID
    document: ProjectedDocument
    # Case-level fields copied into every point's payload (display + store-side filters).
    case_context: dict[str, Any] = field(default_factory=dict)


class CaseKnowledgeSourceAdapter:
    """Discovers and projects the knowledge entities for one case.

    Stateless aside from the session it is handed -- it issues no writes
    and holds no state across calls, so a fresh instance per call (or one
    reused across a batch within the same session) both work.

    Dispositions, sanctions and addresses are reached through their charge or
    party (already eager-loaded), so they add no extra queries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def discover_case(self, case_id: UUID) -> DiscoveredEntity:
        """Case-level document only. `CaseRecordProjector` touches no relationships."""
        case_record = await self._load_case_record(case_id)
        return self._project_case(case_record)

    async def discover_case_summary(self, case_id: UUID) -> DiscoveredEntity:
        case_record = await self._load_case_record_with_relations(case_id)
        return self._project_case_summary(case_record)

    async def discover_parties(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._parties(await self._load_case_record_with_relations(case_id))

    async def discover_charges(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._charges(await self._load_case_record_with_relations(case_id))

    async def discover_appearances(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._appearances(await self._load_case_record_with_relations(case_id))

    async def discover_payments(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._payments(await self._load_case_record_with_relations(case_id))

    async def discover_dispositions(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._dispositions(await self._load_case_record_with_relations(case_id))

    async def discover_sanctions(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._sanctions(await self._load_case_record_with_relations(case_id))

    async def discover_criminal(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._criminal(await self._load_case_record_with_relations(case_id))

    async def discover_vehicles(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._vehicles(await self._load_case_record_with_relations(case_id))

    async def discover_addresses(self, case_id: UUID) -> list[DiscoveredEntity]:
        return self._addresses(await self._load_case_record_with_relations(case_id))

    async def discover_all(self, case_id: UUID) -> list[DiscoveredEntity]:
        """Every knowledge entity for one case from a single eager-loaded query.

        This is what `ingest_case()` (`PLAN.md` §11) should call -- one round
        trip instead of the `discover_*` methods above run separately,
        which exist individually for targeted re-indexing (e.g. re-embed
        only a case's charges) and for focused tests.
        """
        case_record = await self._load_case_record_with_relations(case_id)

        return [
            self._project_case(case_record),
            self._project_case_summary(case_record),
            *self._parties(case_record),
            *self._charges(case_record),
            *self._appearances(case_record),
            *self._payments(case_record),
            *self._dispositions(case_record),
            *self._sanctions(case_record),
            *self._criminal(case_record),
            *self._vehicles(case_record),
            *self._addresses(case_record),
        ]

    async def _load_case_record(self, case_id: UUID) -> CaseRecord:
        stmt = select(CaseRecord).where(CaseRecord.id == case_id)
        result = await self._session.execute(stmt)
        case_record = result.scalar_one_or_none()
        if case_record is None:
            raise CaseNotFoundError(f"case_id={case_id} not found")
        return case_record

    async def _load_case_record_with_relations(self, case_id: UUID) -> CaseRecord:
        """Eager-loads every relationship the projectors read.

        `<child>.case_record` / `charge.<child>` / `address.party` are
        populated in memory as a side effect of loading these collections off
        an already-identity-mapped `CaseRecord` -- SQLAlchemy sets both sides
        of a `back_populates` pair without an extra query -- so only
        `legal_representative` (a plain, non-back-populated relationship)
        needs its own `selectinload`.
        """
        stmt = (
            select(CaseRecord)
            .where(CaseRecord.id == case_id)
            .options(
                selectinload(CaseRecord.parties).selectinload(PartyDetail.addresses),
                selectinload(CaseRecord.charges).selectinload(
                    CaseCharge.imposed_disposition
                ),
                selectinload(CaseRecord.charges).selectinload(
                    CaseCharge.imposed_sanctions
                ),
                selectinload(CaseRecord.appearance_history).selectinload(
                    CaseAppearance.legal_representative
                ),
                selectinload(CaseRecord.payment_records),
                selectinload(CaseRecord.criminal),
                selectinload(CaseRecord.vehicles),
            )
        )
        result = await self._session.execute(stmt)
        case_record = result.scalar_one_or_none()
        if case_record is None:
            raise CaseNotFoundError(f"case_id={case_id} not found")
        return case_record

    @staticmethod
    def _case_context(case_record: CaseRecord) -> dict[str, Any]:
        return {
            "case_number": case_record.case_number,
            "case_title": case_record.case_title,
            "case_type": case_record.case_type,
            "case_status": case_record.case_status,
            "is_juvenile": case_record.is_juvenile,
        }

    @staticmethod
    def _entity(
        source_type: AIKnowledgeSourceType,
        source_table: str,
        entity: Any,
        case_record: CaseRecord,
    ) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=source_type.value,
            source_table=source_table,
            source_id=str(entity.id),
            case_record_id=case_record.id,
            document=get_projector(source_type.value).project(entity),
            case_context=CaseKnowledgeSourceAdapter._case_context(case_record),
        )

    def _project_case(self, case_record: CaseRecord) -> DiscoveredEntity:
        return self._entity(
            AIKnowledgeSourceType.CASE, "case_record", case_record, case_record
        )

    def _project_case_summary(self, case_record: CaseRecord) -> DiscoveredEntity:
        return self._entity(
            AIKnowledgeSourceType.CASE_SUMMARY, "case_record", case_record, case_record
        )

    def _parties(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        return [
            self._entity(AIKnowledgeSourceType.PARTY, "party_detail", p, case_record)
            for p in case_record.parties
        ]

    def _charges(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        return [
            self._entity(AIKnowledgeSourceType.CHARGE, "case_charge", c, case_record)
            for c in case_record.charges
        ]

    def _appearances(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        return [
            self._entity(
                AIKnowledgeSourceType.APPEARANCE, "case_appearance", a, case_record
            )
            for a in case_record.appearance_history
        ]

    def _payments(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        payments: list[PaymentRecord] = case_record.payment_records
        return [
            self._entity(
                AIKnowledgeSourceType.PAYMENT, "payment_record", p, case_record
            )
            for p in payments
        ]

    def _dispositions(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        dispositions: list[ImposedDisposition] = [
            c.imposed_disposition
            for c in case_record.charges
            if c.imposed_disposition is not None
        ]
        return [
            self._entity(
                AIKnowledgeSourceType.DISPOSITION,
                "imposed_disposition",
                d,
                case_record,
            )
            for d in dispositions
        ]

    def _sanctions(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        sanctions: list[ImposedSanction] = [
            s for c in case_record.charges for s in c.imposed_sanctions
        ]
        return [
            self._entity(
                AIKnowledgeSourceType.SANCTION, "imposed_sanction", s, case_record
            )
            for s in sanctions
        ]

    def _criminal(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        criminal: Criminal | None = case_record.criminal
        if criminal is None:
            return []
        return [
            self._entity(
                AIKnowledgeSourceType.CRIMINAL, "criminal", criminal, case_record
            )
        ]

    def _vehicles(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        vehicles: list[VehicleDetail] = case_record.vehicles
        return [
            self._entity(
                AIKnowledgeSourceType.VEHICLE, "vehicle_detail", v, case_record
            )
            for v in vehicles
        ]

    def _addresses(self, case_record: CaseRecord) -> list[DiscoveredEntity]:
        addresses: list[AddressDetail] = [
            a for p in case_record.parties for a in p.addresses
        ]
        return [
            self._entity(
                AIKnowledgeSourceType.ADDRESS, "address_detail", a, case_record
            )
            for a in addresses
        ]
