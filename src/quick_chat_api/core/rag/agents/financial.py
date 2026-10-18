"""Financial agent: structured payment queries only (no vector search)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from quick_chat_api.core.rag.agents.runner import (
    OUT_OF_SCOPE,
    build_tool,
    fact_evidence,
    run_agent,
    tenant_session,
)
from quick_chat_api.core.rag.agents.schemas import (
    CasePayments,
    FinancialAgentOutput,
    PaymentFact,
)
from quick_chat_api.core.rag.agents.scope import CaseScope
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.modules.rag.structured.financial import (
    CaseScopeError,
    get_payment_summaries,
)


class GetPayments(BaseModel):
    case_ids: list[UUID] = Field(min_length=1, max_length=20)


async def run_financial_agent(
    state: PipelineState, scope: CaseScope
) -> FinancialAgentOutput:
    out = FinancialAgentOutput()

    async def get_payments(args: GetPayments) -> str:
        case_ids = scope.require(args.case_ids)
        async with tenant_session() as session:
            try:
                summaries = await get_payment_summaries(session, case_ids)
            except CaseScopeError:
                out.rejected_case_ids.extend(case_ids)
                return OUT_OF_SCOPE
        lines: list[str] = []
        for case_id, summary in summaries.items():
            facts = [
                PaymentFact(
                    payment_id=p.id,
                    amount=p.amount,
                    payment_datetime=p.payment_datetime,
                    void=p.void,
                )
                for p in summary.payments
            ]
            out.payments.append(
                CasePayments(
                    case_id=case_id, total_paid=summary.total_paid, payments=facts
                )
            )
            lines.append(f"case_id={case_id} total_paid={summary.total_paid}")
            for f in facts:
                line = (
                    f"payment amount={f.amount} at={f.payment_datetime}"
                    f"{' VOID' if f.void else ''}"
                )
                out.evidence.append(
                    fact_evidence(case_id, "payment_record", f.payment_id, line)
                )
                lines.append(f"  {line}")
        return "\n".join(lines)

    tools = [
        build_tool(
            "get_payments",
            "Payments and total paid (void payments excluded) for resolved case ids.",
            GetPayments,
            get_payments,
            out,
        )
    ]
    sub_query = state.get("sub_queries", {}).get("financial") or state.get(
        "question", ""
    )
    await run_agent(
        "financial", tools, sub_query, state.get("entities", {}), scope, out
    )
    return out
