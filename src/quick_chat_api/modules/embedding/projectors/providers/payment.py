"""Projects a `PaymentRecord` into an embeddable document.

Card fields (`card_*`, `exp_*`), `qp_payment_id`, method/mode and `service_fee`
are deliberately not embedded; they stay queryable from Postgres only.
"""

from __future__ import annotations

from quick_chat_api.core.constants.constants import AIKnowledgeSourceType
from quick_chat_api.core.models.agency.agency import PaymentRecord
from quick_chat_api.modules.embedding.projectors._formatting import (
    field_line,
    join_lines,
)
from quick_chat_api.modules.embedding.projectors.base import (
    ProjectedDocument,
    Projector,
)
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class PaymentProjector(Projector[PaymentRecord]):
    def project(self, entity: PaymentRecord) -> ProjectedDocument:
        case_number = None
        if "case_record" in entity.__dict__ and entity.case_record is not None:
            case_number = entity.case_record.case_number

        content = join_lines(
            field_line("Case number", case_number),
            field_line("Amount", entity.amount),
            field_line("Currency", entity.currency),
            field_line("Payment date", entity.payment_datetime),
            field_line("Payee name", entity.payee_name),
            field_line("Payee email", entity.payee_email),
            field_line("Payee address", entity.payee_address),
            field_line("Reference number", entity.reference_number),
            field_line("Receipt number", entity.receipt_number),
            field_line("Considered as full", entity.consider_as_full),
            field_line("Void", entity.void),
        )

        return ProjectedDocument(
            content=content,
            title=f"Payment for case {case_number}" if case_number else None,
            metadata={
                "case_number": case_number,
                "amount": str(entity.amount),
                "void": entity.void,
            },
        )


@register_projector(AIKnowledgeSourceType.PAYMENT.value)
def _build_payment_projector() -> PaymentProjector:
    return PaymentProjector()
