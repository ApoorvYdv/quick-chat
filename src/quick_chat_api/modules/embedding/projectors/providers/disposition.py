"""Projects an `ImposedDisposition` into a standalone embeddable document.

Assumes the caller eager-loaded `case_charge` (with its `case_record`); this
projector never issues its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import ImposedDisposition
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


class DispositionProjector(Projector[ImposedDisposition]):
    def project(self, entity: ImposedDisposition) -> ProjectedDocument:
        case_number, charge_description = charge_context(entity)

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Charge description", charge_description),
            field_line("Disposition type", entity.disposition_type),
            field_line("Finding", entity.finding),
            field_line("Disposed on", entity.disposed_on),
            field_line("Conclusive", entity.is_conclusive),
        )

        return ProjectedDocument(
            content=content,
            title=entity.disposition_type,
            metadata={
                "case_number": case_number,
                "disposition_type": entity.disposition_type,
                "finding": entity.finding,
            },
        )


@register_projector(AIKnowledgeSourceType.DISPOSITION.value)
def _build_disposition_projector() -> DispositionProjector:
    return DispositionProjector()
