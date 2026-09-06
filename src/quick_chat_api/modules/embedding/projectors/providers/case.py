"""Projects a bare `CaseRecord` into its case-level embeddable document.

Case-level fields only -- no relationships, per `PLAN.md` §4. For a
whole-case rollup that also spans parties, charges, appearances,
and payments, see `case_summary.py`.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import CaseRecord
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class CaseRecordProjector(Projector[CaseRecord]):
    """Projects case-level fields only -- omits internal IDs/DB details."""

    def project(self, entity: CaseRecord) -> ProjectedDocument:
        incident = None
        if entity.incident_date is not None or entity.incident_location:
            when = f"{entity.incident_date}" if entity.incident_date else "unknown date"
            where = (
                f" at {entity.incident_location}" if entity.incident_location else ""
            )
            incident = f"Incident: {when}{where}"

        hearing = None
        if entity.hearing_date is not None:
            hearing = str(entity.hearing_date)
            if entity.hearing_time:
                hearing = f"{hearing} at {entity.hearing_time}"

        content = join_lines(
            field_line("Case number", entity.case_number),
            field_line("Case title", entity.case_title),
            field_line("Case type", entity.case_type),
            field_line("Case subtype", entity.case_subtype),
            field_line("Case status", entity.case_status),
            incident,
            field_line("Issuer", entity.issuer_name),
            field_line("Hearing", hearing),
            field_line("County", entity.county_name),
            field_line("Notes", entity.additional_notes),
        )

        return ProjectedDocument(
            content=content,
            title=entity.case_title or entity.case_number,
            metadata={
                "case_number": entity.case_number,
                "case_type": entity.case_type,
                "case_subtype": entity.case_subtype,
                "case_status": entity.case_status,
            },
        )


@register_projector(AIKnowledgeSourceType.CASE.value)
def _build_case_record_projector() -> CaseRecordProjector:
    return CaseRecordProjector()
