"""Projects a `PartyDetail` into an embeddable document.

`ssn_id` and `license_number` are direct identifiers and are never
projected into embeddable text, per the project's PII-exclusion decision
for the semantic projection layer (`PLAN.md` §3, design principle 8).
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import PartyDetail
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class PartyProjector(Projector[PartyDetail]):
    """Projects party fields, excluding `ssn_id` and `license_number`."""

    def project(self, entity: PartyDetail) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        content = join_lines(
            field_line("Party type", entity.party_type),
            field_line("Name", entity.full_name),
            field_line("Case number", case_number),
            field_line("Primary party", entity.is_primary_party),
            field_line("Date of birth", entity.dob),
            field_line("Race", entity.race),
            field_line("Sex", entity.sex),
            field_line("Ethnicity", entity.ethnicity),
            field_line("Eye color", entity.eye_color),
            field_line("Hair color", entity.hair_color),
            field_line("Height", entity.height),
            field_line("Weight", entity.weight),
            field_line("License type", entity.license_type),
            field_line("License state", entity.license_state_code),
            field_line("License suspended", entity.is_license_suspended),
            field_line("License surrendered", entity.is_license_surrendered),
            field_line("Commercial license", entity.is_commercial_license),
            field_line("Phone", entity.phone_number),
            field_line("Email", entity.email),
            field_line("Organization", entity.party_organization),
            field_line("Juvenile", entity.is_juvenile),
        )

        return ProjectedDocument(
            content=content,
            title=entity.full_name,
            metadata={
                "case_number": case_number,
                "party_type": entity.party_type,
                "full_name": entity.full_name,
                "is_primary_party": entity.is_primary_party,
            },
        )


@register_projector(AIKnowledgeSourceType.PARTY.value)
def _build_party_projector() -> PartyProjector:
    return PartyProjector()
