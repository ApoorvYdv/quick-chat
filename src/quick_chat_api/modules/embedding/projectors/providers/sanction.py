"""Projects an `ImposedSanction` into a standalone embeddable document.

Assumes the caller eager-loaded `case_charge` (with its `case_record`); this
projector never issues its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import ImposedSanction
from quick_chat_api.modules.embedding.projectors._formatting import (
    charge_context,
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class SanctionProjector(Projector[ImposedSanction]):
    def project(self, entity: ImposedSanction) -> ProjectedDocument:
        case_number, charge_description = charge_context(entity)

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Charge description", charge_description),
            field_line("Sanction type", entity.sanction_type),
            field_line("Due date", entity.due_date),
            field_line("Completed", entity.mark_as_completed),
            field_line("Conclusive", entity.is_conclusive),
        )

        return ProjectedDocument(
            content=content,
            title=entity.sanction_type,
            metadata={
                "case_number": case_number,
                "sanction_type": entity.sanction_type,
                "mark_as_completed": entity.mark_as_completed,
            },
        )


@register_projector(AIKnowledgeSourceType.SANCTION.value)
def _build_sanction_projector() -> SanctionProjector:
    return SanctionProjector()
