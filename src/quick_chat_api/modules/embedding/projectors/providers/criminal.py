"""Projects a `Criminal` (arrest/warrant) record into an embeddable document.

Assumes the caller eager-loaded `case_record`; this projector never issues
its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import Criminal
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class CriminalProjector(Projector[Criminal]):
    def project(self, entity: Criminal) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Arrested", entity.is_arrested),
            field_line("Arrested date", entity.arrested_date),
            field_line("Arrested time", entity.arrested_time),
            field_line("Arrest location", entity.arrest_location),
            field_line("Warrant issued", entity.is_warrant_issued),
            field_line("Warrant type", entity.warrant_type),
            field_line("Warrant issued date", entity.warrant_issued_date),
            field_line("Warrant issued time", entity.warrant_issued_time),
            field_line("Warrant number", entity.warrant_number),
            field_line("Observation", entity.observation_text),
        )

        return ProjectedDocument(
            content=content,
            title=f"Arrest/warrant for case {case_number}" if case_number else None,
            metadata={
                "case_number": case_number,
                "is_arrested": entity.is_arrested,
                "is_warrant_issued": entity.is_warrant_issued,
            },
        )


@register_projector(AIKnowledgeSourceType.CRIMINAL.value)
def _build_criminal_projector() -> CriminalProjector:
    return CriminalProjector()
