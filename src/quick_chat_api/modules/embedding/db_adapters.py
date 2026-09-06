"""DB source adapters: discover a case's Phase 2 entities and project them.

Loads business entities from PostgreSQL (tenant-scoped via the caller's
`session_context()`), eager-loads exactly the relationships each projector
in `projectors/providers/` needs, and hands each entity to its projector via
`get_projector(...)`.

Read-only by design: this module never touches `ai_knowledge_source` /
`ai_knowledge_chunk` and never computes a `content_hash`. Hashing, the
unchanged-skip decision, and all knowledge-table writes belong to the
ingestion service (`PLAN.md` §11) so that the DB read transaction, the
embedding API call, and the knowledge-table write transaction stay on
separate sides of the boundary in `PLAN.md` §9.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import (
    CaseAppearance,
    CaseCharge,
    CaseRecord,
    PartyDetail,
)
from quick_chat_api.modules.embedding.projectors.base import ProjectedDocument
from quick_chat_api.modules.embedding.projectors.factory import get_projector


class CaseNotFoundError(RuntimeError):
    """Raised when a `case_id` does not resolve to a `CaseRecord` in the current tenant."""


@dataclass(frozen=True)
class DiscoveredEntity:
    """One projected candidate, awaiting hashing/persistence by the ingestion service.

    `source_table` + `source_id` + `source_type` mirror the columns backing
    `ai_knowledge_source`'s dedupe unique constraint, so the ingestion
    service can look up any prior row for this entity without re-deriving
    identity from the projected content.
    """

    source_type: str
    source_table: str
    source_id: str
    case_record_id: UUID
    document: ProjectedDocument


class CaseKnowledgeSourceAdapter:
    """Discovers and projects the Phase 2 knowledge entities for one case.

    Stateless aside from the session it is handed -- it issues no writes
    and holds no state across calls, so a fresh instance per call (or one
    reused across a batch within the same session) both work.
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
        case_record = await self._load_case_record_with_relations(case_id)
        return [self._project_party(party) for party in case_record.parties]

    async def discover_charges(self, case_id: UUID) -> list[DiscoveredEntity]:
        case_record = await self._load_case_record_with_relations(case_id)
        return [self._project_charge(charge) for charge in case_record.charges]

    async def discover_appearances(self, case_id: UUID) -> list[DiscoveredEntity]:
        case_record = await self._load_case_record_with_relations(case_id)
        return [
            self._project_appearance(appearance)
            for appearance in case_record.appearance_history
        ]

    async def discover_all(self, case_id: UUID) -> list[DiscoveredEntity]:
        """Every Phase 2 entity for one case from a single eager-loaded query.

        This is what `ingest_case()` (`PLAN.md` §11) should call -- one round
        trip instead of the five `discover_*` methods above run separately,
        which exist individually for targeted re-indexing (e.g. re-embed
        only a case's charges) and for focused tests.
        """
        case_record = await self._load_case_record_with_relations(case_id)

        discovered = [
            self._project_case(case_record),
            self._project_case_summary(case_record),
        ]
        discovered.extend(self._project_party(party) for party in case_record.parties)
        discovered.extend(
            self._project_charge(charge) for charge in case_record.charges
        )
        discovered.extend(
            self._project_appearance(appearance)
            for appearance in case_record.appearance_history
        )
        return discovered

    async def _load_case_record(self, case_id: UUID) -> CaseRecord:
        stmt = select(CaseRecord).where(CaseRecord.id == case_id)
        result = await self._session.execute(stmt)
        case_record = result.scalar_one_or_none()
        if case_record is None:
            raise CaseNotFoundError(f"case_id={case_id} not found")
        return case_record

    async def _load_case_record_with_relations(self, case_id: UUID) -> CaseRecord:
        """Eager-loads every relationship the Phase 2 projectors read.

        `charges.case_record`, `parties.case_record`, and
        `appearance_history.case_record` are populated in memory as a side
        effect of loading these collections off an already-identity-mapped
        `CaseRecord` -- SQLAlchemy sets both sides of a `back_populates`
        pair without an extra query -- so only `legal_representative`
        (a plain, non-back-populated relationship) needs its own
        `selectinload`.
        """
        stmt = (
            select(CaseRecord)
            .where(CaseRecord.id == case_id)
            .options(
                selectinload(CaseRecord.parties),
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
            )
        )
        result = await self._session.execute(stmt)
        case_record = result.scalar_one_or_none()
        if case_record is None:
            raise CaseNotFoundError(f"case_id={case_id} not found")
        return case_record

    def _project_case(self, case_record: CaseRecord) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=AIKnowledgeSourceType.CASE.value,
            source_table="case_record",
            source_id=str(case_record.id),
            case_record_id=case_record.id,
            document=get_projector(AIKnowledgeSourceType.CASE.value).project(
                case_record
            ),
        )

    def _project_case_summary(self, case_record: CaseRecord) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=AIKnowledgeSourceType.CASE_SUMMARY.value,
            source_table="case_record",
            source_id=str(case_record.id),
            case_record_id=case_record.id,
            document=get_projector(AIKnowledgeSourceType.CASE_SUMMARY.value).project(
                case_record
            ),
        )

    def _project_party(self, party: PartyDetail) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=AIKnowledgeSourceType.PARTY.value,
            source_table="party_detail",
            source_id=str(party.id),
            case_record_id=party.case_record_id,
            document=get_projector(AIKnowledgeSourceType.PARTY.value).project(party),
        )

    def _project_charge(self, charge: CaseCharge) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=AIKnowledgeSourceType.CHARGE.value,
            source_table="case_charge",
            source_id=str(charge.id),
            case_record_id=charge.case_record_id,
            document=get_projector(AIKnowledgeSourceType.CHARGE.value).project(
                charge
            ),
        )

    def _project_appearance(self, appearance: CaseAppearance) -> DiscoveredEntity:
        return DiscoveredEntity(
            source_type=AIKnowledgeSourceType.APPEARANCE.value,
            source_table="case_appearance",
            source_id=str(appearance.id),
            case_record_id=appearance.case_record_id,
            document=get_projector(AIKnowledgeSourceType.APPEARANCE.value).project(
                appearance
            ),
        )
