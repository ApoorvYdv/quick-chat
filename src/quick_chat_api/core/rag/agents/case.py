"""Case agent: case-number/party/attribute lookups (structured) and case-text search (vector)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from quick_chat_api.core.constants.constants import (
    SOURCE_TYPE_DOMAIN,
    CaseStatus,
    Domain,
    PartyType,
)
from quick_chat_api.core.rag.agents.runner import (
    build_tool,
    case_matches,
    run_agent,
    search_reranked,
    tenant_session,
)
from quick_chat_api.core.rag.agents.schemas import CaseAgentOutput, PartyCandidateOut
from quick_chat_api.core.rag.agents.scope import CaseScope
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.modules.embedding.retrieval import get_cases_by_number
from quick_chat_api.modules.rag.structured.cross_case import (
    CaseDateField,
    CaseRef,
    filter_cases,
    find_cases_by_party,
)
from quick_chat_api.modules.rag.structured.cross_case import (
    CaseList as CrossCaseList,
)

SOURCE_TYPES = [t.value for t, d in SOURCE_TYPE_DOMAIN.items() if d is Domain.CASE]


class LookupCaseNumber(BaseModel):
    case_number: str = Field(min_length=1, max_length=64)


class FindCasesByParty(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: PartyType | None = None


class FilterCases(BaseModel):
    case_status: CaseStatus | None = None
    case_type: str | None = None
    date_field: CaseDateField = "hearing_date"
    date_from: date | None = None
    date_to: date | None = None


class SearchCaseRecords(BaseModel):
    query: str = Field(min_length=1, max_length=500)


async def run_case_agent(state: PipelineState, scope: CaseScope) -> CaseAgentOutput:
    out = CaseAgentOutput()

    async def lookup_case_number(args: LookupCaseNumber) -> str:
        async with tenant_session() as session:
            rows = await get_cases_by_number(session, args.case_number)
        result = CrossCaseList(
            cases=tuple(
                CaseRef(r.id, r.case_number, r.case_type, r.case_status, r.hearing_date)
                for r in rows
            ),
            total=len(rows),
        )
        return _record(out, result)

    async def find_by_party(args: FindCasesByParty) -> str:
        async with tenant_session() as session:
            result = await find_cases_by_party(session, args.name, args.role)
        if result.needs_clarification:
            out.candidates = [
                PartyCandidateOut(
                    full_name=c.full_name, dob=c.dob, case_numbers=list(c.case_numbers)
                )
                for c in result.candidates
            ]
            return "Several people match; ask the user which one. Candidates were recorded."
        return _record(out, result)

    async def filter_by_attributes(args: FilterCases) -> str:
        async with tenant_session() as session:
            result = await filter_cases(session, **args.model_dump())
        return _record(out, result)

    async def search_records(args: SearchCaseRecords) -> str:
        return await search_reranked(args.query, SOURCE_TYPES, scope, out)

    tools = [
        build_tool(
            "lookup_case_number",
            "Find every case with an exact case number.",
            LookupCaseNumber,
            lookup_case_number,
            out,
        ),
        build_tool(
            "find_cases_by_party",
            "Find all cases for a person by name. Several matches return candidates.",
            FindCasesByParty,
            find_by_party,
            out,
        ),
        build_tool(
            "filter_cases",
            "List cases by status, type or a date range; needs at least one filter.",
            FilterCases,
            filter_by_attributes,
            out,
        ),
        build_tool(
            "search_case_records",
            "Semantic search over case, party, charge, vehicle and address text.",
            SearchCaseRecords,
            search_records,
            out,
        ),
    ]
    sub_query = state.get("sub_queries", {}).get("case") or state.get("question", "")
    await run_agent("case", tools, sub_query, state.get("entities", {}), scope, out)
    return out


def _record(out: CaseAgentOutput, result: CrossCaseList) -> str:
    out.matches, evidence, text = case_matches(result)
    out.evidence.extend(evidence)
    return text
