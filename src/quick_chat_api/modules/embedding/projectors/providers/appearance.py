"""Projects a `CaseAppearance` into an embeddable document.

Relationship-aware per `PLAN.md` §4: carries case and legal-representative
context. Assumes the caller (a DB source adapter) eager-loaded
`case_record` and `legal_representative` -- this projector never issues
its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import CaseAppearance
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class AppearanceProjector(Projector[CaseAppearance]):
    """Projects a case appearance together with case and legal-rep context."""

    def project(self, entity: CaseAppearance) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        legal_representative = None
        if (
            "legal_representative" in entity.__dict__
            and entity.legal_representative is not None
        ):
            legal_representative = entity.legal_representative.full_name

        hearing_types = (
            ", ".join(entity.hearing_types) if entity.hearing_types else None
        )

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Hearing types", hearing_types),
            field_line("Status", entity.status),
            field_line("Due date", entity.due_date),
            field_line("Hearing result", entity.hearing_result),
            field_line("Hearing notes", entity.hearing_notes),
            field_line("Check-in time", entity.check_in_time),
            field_line("Legal representative", legal_representative),
            field_line("Translator language", entity.translator_language),
        )

        return ProjectedDocument(
            content=content,
            title=f"Appearance for case {case_number}" if case_number else None,
            metadata={
                "case_number": case_number,
                "status": entity.status,
                "hearing_types": entity.hearing_types,
            },
        )


@register_projector(AIKnowledgeSourceType.APPEARANCE.value)
def _build_appearance_projector() -> AppearanceProjector:
    return AppearanceProjector()
