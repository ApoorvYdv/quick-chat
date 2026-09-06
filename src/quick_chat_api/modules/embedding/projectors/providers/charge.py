"""Projects a `CaseCharge` into an embeddable document.

Relationship-aware per `PLAN.md` §4: carries case context and, where
present, the charge's disposition/sanction outcome. Assumes the caller
(a DB source adapter) eager-loaded `case_record`, `imposed_disposition`,
and `imposed_sanctions` -- this projector never issues its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import CaseCharge
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class ChargeProjector(Projector[CaseCharge]):
    """Projects a charge together with its case and disposition/sanction context."""

    def project(self, entity: CaseCharge) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        disposition = None
        if "imposed_disposition" in entity.__dict__ and entity.imposed_disposition:
            d = entity.imposed_disposition
            disposition = join_lines(
                field_line("Disposition type", d.disposition_type),
                field_line("Finding", d.finding),
                field_line("Disposed on", d.disposed_on),
                field_line("Conclusive", d.is_conclusive),
            )

        sanctions = None
        if "imposed_sanctions" in entity.__dict__ and entity.imposed_sanctions:
            sanctions = "\n".join(
                join_lines(
                    field_line("Sanction type", sanction.sanction_type),
                    field_line("Due date", sanction.due_date),
                    field_line("Completed", sanction.mark_as_completed),
                )
                for sanction in entity.imposed_sanctions
            )

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Charge code", entity.charge_code),
            field_line("Charge type", entity.charge_type),
            field_line("Charge description", entity.charge_description),
            field_line("Points", entity.points),
            field_line("Court only fine", entity.court_only_fine),
            field_line("Closed", entity.is_charge_closed),
            field_line("Void", entity.void),
            f"Disposition:\n{disposition}" if disposition else None,
            f"Sanctions:\n{sanctions}" if sanctions else None,
        )

        return ProjectedDocument(
            content=content,
            title=entity.charge_description,
            metadata={
                "case_number": case_number,
                "charge_code": entity.charge_code,
                "charge_type": entity.charge_type,
                "is_charge_closed": entity.is_charge_closed,
            },
        )


@register_projector(AIKnowledgeSourceType.CHARGE.value)
def _build_charge_projector() -> ChargeProjector:
    return ChargeProjector()
