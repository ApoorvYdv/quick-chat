"""Projects an `AddressDetail` into an embeddable document.

Assumes the caller eager-loaded it through `party.addresses` so `party` (and
its `case_record`) are populated; this projector never issues its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import AddressDetail
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class AddressProjector(Projector[AddressDetail]):
    def project(self, entity: AddressDetail) -> ProjectedDocument:
        party = entity.__dict__.get("party")
        party_name = party.full_name if party is not None else None
        case_record = party.__dict__.get("case_record") if party is not None else None
        case_number = case_record.case_number if case_record is not None else None

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Party", party_name),
            field_line("Address type", entity.address_type),
            field_line("Default address", entity.is_default),
            field_line("Address line 1", entity.address_line_1),
            field_line("Address line 2", entity.address_line_2),
            field_line("City", entity.city),
            field_line("State", entity.state),
            field_line("Zip code", entity.zip_code),
        )

        return ProjectedDocument(
            content=content,
            title=f"Address for {party_name}" if party_name else None,
            metadata={
                "case_number": case_number,
                "party_name": party_name,
                "address_type": entity.address_type,
                "is_default": entity.is_default,
            },
        )


@register_projector(AIKnowledgeSourceType.ADDRESS.value)
def _build_address_projector() -> AddressProjector:
    return AddressProjector()
