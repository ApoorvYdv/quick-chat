"""Procedural agent: appearances (structured), appearance filters across cases, disposition/sanction search (vector)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from quick_chat_api.core.constants.constants import (
    SOURCE_TYPE_DOMAIN,
    AIKnowledgeSourceType,
    CaseAppearanceStatus,
    Domain,
)
from quick_chat_api.core.models.agency.agency import CaseAppearance
from quick_chat_api.core.rag.agents.runner import (
    build_tool,
    case_matches,
    fact_evidence,
    run_agent,
    search_reranked,
    tenant_session,
)
from quick_chat_api.core.rag.agents.schemas import AppearanceFact, ProceduralAgentOutput
from quick_chat_api.core.rag.agents.scope import CaseScope
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.modules.rag.structured.cross_case import filter_cases_by_appearance
from quick_chat_api.modules.rag.structured.hearings import (
    get_appearances,
    get_next_appearance,
)

# Appearances are answered structurally; only outcome text is searched.
SOURCE_TYPES = [
    t.value
    for t, d in SOURCE_TYPE_DOMAIN.items()
    if d is Domain.HEARINGS and t is not AIKnowledgeSourceType.APPEARANCE
]


class CaseIds(BaseModel):
    case_ids: list[UUID] = Field(min_length=1, max_length=20)


class FilterAppearances(BaseModel):
    status: CaseAppearanceStatus | None = None
    hearing_date: date | None = None


class SearchOutcomes(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def _fact(case_id: UUID, a: CaseAppearance) -> AppearanceFact:
    return AppearanceFact(
        case_id=case_id,
        appearance_id=a.id,
        due_date=a.due_date,
        status=a.status,
        hearing_types=[str(t) for t in a.hearing_types],
        hearing_result=a.hearing_result,
    )


def _line(f: AppearanceFact) -> str:
    return (
        f"case_id={f.case_id} due={f.due_date} status={f.status} "
        f"types={','.join(f.hearing_types)} result={f.hearing_result}"
    )


async def run_procedural_agent(
    state: PipelineState, scope: CaseScope
) -> ProceduralAgentOutput:
    out = ProceduralAgentOutput()

    def keep(facts: list[AppearanceFact]) -> str:
        out.evidence.extend(
            fact_evidence(f.case_id, "case_appearance", f.appearance_id, _line(f))
            for f in facts
        )
        return "\n".join(map(_line, facts)) or "No appearances found."

    async def appearances(args: CaseIds) -> str:
        case_ids = scope.require(args.case_ids)
        async with tenant_session() as session:
            for case_id in case_ids:
                out.appearances.extend(
                    _fact(case_id, a) for a in await get_appearances(session, case_id)
                )
        return keep(out.appearances)

    async def next_appearance(args: CaseIds) -> str:
        case_ids = scope.require(args.case_ids)
        async with tenant_session() as session:
            for case_id in case_ids:
                if (nxt := await get_next_appearance(session, case_id)) is not None:
                    out.next_appearances.append(_fact(case_id, nxt))
        return keep(out.next_appearances)

    async def filter_appearances(args: FilterAppearances) -> str:
        if scope.ids:
            # Inside a resolved scope the filter applies to those cases only.
            hits: list[AppearanceFact] = []
            async with tenant_session() as session:
                for case_id in sorted(scope.ids):
                    hits.extend(
                        _fact(case_id, a)
                        for a in await get_appearances(session, case_id)
                        if (args.status is None or a.status == args.status.value)
                        and (
                            args.hearing_date is None or a.due_date == args.hearing_date
                        )
                    )
            out.appearances.extend(hits)
            return keep(hits)
        async with tenant_session() as session:
            result = await filter_cases_by_appearance(
                session, status=args.status, hearing_date=args.hearing_date
            )
        out.matches, evidence, text = case_matches(result)
        out.evidence.extend(evidence)
        return text

    async def search_outcomes(args: SearchOutcomes) -> str:
        return await search_reranked(args.query, SOURCE_TYPES, scope, out)

    tools = [
        build_tool(
            "get_appearances",
            "All hearings/appearances for resolved case ids, soonest first.",
            CaseIds,
            appearances,
            out,
        ),
        build_tool(
            "get_next_appearance",
            "The next upcoming appearance for resolved case ids.",
            CaseIds,
            next_appearance,
            out,
        ),
        build_tool(
            "filter_appearances",
            "Cases with an appearance of a given status and/or hearing date.",
            FilterAppearances,
            filter_appearances,
            out,
        ),
        build_tool(
            "search_outcomes",
            "Semantic search over dispositions and sanctions.",
            SearchOutcomes,
            search_outcomes,
            out,
        ),
    ]
    sub_query = state.get("sub_queries", {}).get("procedural") or state.get(
        "question", ""
    )
    await run_agent(
        "procedural", tools, sub_query, state.get("entities", {}), scope, out
    )
    return out
