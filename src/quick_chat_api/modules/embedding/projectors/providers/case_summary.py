"""Composite whole-case rollup for high-level retrieval.

Per `PLAN.md` §4, this is the single highest-value first target: a
natural-language document spanning a `CaseRecord` and its relationships
(parties, charges with their dispositions/sanctions, appearances, and a
non-sensitive payment summary). It composes the other Phase 2 projectors
rather than duplicating their field lists.

Assumes the caller (a DB source adapter) eager-loaded `parties`, `charges`
(with `imposed_disposition`/`imposed_sanctions`), `appearance_history`
(with `legal_representative`), and `payment_records` -- this projector
never issues its own queries.

Payment records carry card details (`card_last_4`, `card_brand`, etc.);
only an aggregate total/count/currency is projected, never per-payment
card data, per `CLAUDE.md` §13/§20.
"""

from __future__ import annotations

from decimal import Decimal

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
from quick_chat_api.modules.embedding.projectors.providers.appearance import (
    AppearanceProjector,
)
from quick_chat_api.modules.embedding.projectors.providers.case import (
    CaseRecordProjector,
)
from quick_chat_api.modules.embedding.projectors.providers.charge import (
    ChargeProjector,
)
from quick_chat_api.modules.embedding.projectors.providers.party import PartyProjector
from quick_chat_api.modules.embedding.projectors.registry import register_projector


class CaseSummaryProjector(Projector[CaseRecord]):
    """Rolls up a case and its relationships into one embeddable document."""

    def __init__(self) -> None:
        self._case_projector = CaseRecordProjector()
        self._party_projector = PartyProjector()
        self._charge_projector = ChargeProjector()
        self._appearance_projector = AppearanceProjector()

    def project(self, entity: CaseRecord) -> ProjectedDocument:
        sections = [self._case_projector.project(entity).content]

        for party in entity.parties:
            sections.append(f"Party:\n{self._party_projector.project(party).content}")

        for charge in entity.charges:
            sections.append(
                f"Charge:\n{self._charge_projector.project(charge).content}"
            )

        for appearance in entity.appearance_history:
            sections.append(
                f"Appearance:\n{self._appearance_projector.project(appearance).content}"
            )

        payment_summary = self._project_payment_summary(entity)
        if payment_summary:
            sections.append(f"Payments:\n{payment_summary}")

        return ProjectedDocument(
            content="\n\n".join(sections),
            title=entity.case_title or entity.case_number,
            metadata={
                "case_number": entity.case_number,
                "case_type": entity.case_type,
                "case_status": entity.case_status,
                "party_count": len(entity.parties),
                "charge_count": len(entity.charges),
            },
        )

    @staticmethod
    def _project_payment_summary(entity: CaseRecord) -> str | None:
        payments = [p for p in entity.payment_records if not p.void]
        if not payments:
            return None

        total = sum((p.amount for p in payments), Decimal("0.00"))
        currencies = {p.currency for p in payments if p.currency}
        currency = currencies.pop() if len(currencies) == 1 else None

        return join_lines(
            field_line("Total paid", total),
            field_line("Currency", currency),
            field_line("Payment count", len(payments)),
        )


@register_projector(AIKnowledgeSourceType.CASE_SUMMARY.value)
def _build_case_summary_projector() -> CaseSummaryProjector:
    return CaseSummaryProjector()
