"""Projects a `VehicleDetail` into an embeddable document.

Assumes the caller eager-loaded `case_record`; this projector never issues
its own queries.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import VehicleDetail
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class VehicleProjector(Projector[VehicleDetail]):
    def project(self, entity: VehicleDetail) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Make", entity.vehicle_make),
            field_line("Model", entity.vehicle_model),
            field_line("Year", entity.vehicle_year),
            field_line("Color", entity.vehicle_color),
            field_line("Type", entity.vehicle_type),
            field_line("Plate", entity.vehicle_plate),
            field_line("Plate state", entity.vehicle_state_code),
            field_line("Plate expiration year", entity.plate_expiration_year),
            field_line("VIN", entity.vehicle_vin),
            field_line("Legal speed", entity.legal_speed_rate),
            field_line("Recorded speed", entity.recorded_speed_rate),
            field_line("Commercial vehicle", entity.is_commercial_vehicle),
        )

        return ProjectedDocument(
            content=content,
            title=" ".join(
                part
                for part in (
                    entity.vehicle_year,
                    entity.vehicle_make,
                    entity.vehicle_model,
                )
                if part
            )
            or None,
            metadata={
                "case_number": case_number,
                "vehicle_plate": entity.vehicle_plate,
                "vehicle_state_code": entity.vehicle_state_code,
            },
        )


@register_projector(AIKnowledgeSourceType.VEHICLE.value)
def _build_vehicle_projector() -> VehicleProjector:
    return VehicleProjector()
