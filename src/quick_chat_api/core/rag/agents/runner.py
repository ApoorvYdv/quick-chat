"""Shared agent machinery: tenant session, bounded tool-calling loop, reranked search.

An agent's model only chooses tools and arguments. Every fact in the output is
written by a tool, so model text can never become evidence.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.llm.generation.factory import get_chat_model
from quick_chat_api.core.llm.prompts import AGENT_PROMPT_VERSION, AGENT_V1
from quick_chat_api.core.llm.reranking import get_reranker
from quick_chat_api.core.llm.reranking.base import RerankCandidate
from quick_chat_api.core.rag.agents.schemas import AgentOutput, CaseList
from quick_chat_api.core.rag.agents.scope import CaseScope, CaseScopeViolation
from quick_chat_api.core.rag.state import EvidenceItem
from quick_chat_api.core.rag.tracing import annotate, span
from quick_chat_api.modules.embedding.retrieval import retrieve
from quick_chat_api.modules.rag.structured.cross_case import CaseList as CrossCaseList
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger
from quick_chat_api.utils.context import RequestContext

OUT_OF_SCOPE = "Rejected: case id is outside the resolved scope."
INVALID_ARGS = "Rejected: invalid tool arguments."

ToolFn = Callable[[Any], Awaitable[str]]


@asynccontextmanager
async def tenant_session() -> AsyncIterator[AsyncSession]:
    async with session_context(get_async_engine(), RequestContext.agency) as session:
        yield session


def data_block(text: str) -> str:
    return f"<data>\n{text}\n</data>"


def fact_evidence(
    case_id: UUID, source_table: str, source_record_id: UUID | str, text: str
) -> EvidenceItem:
    """Evidence for a structured row; the chunk id is derived so repeats dedupe."""
    chunk_id = uuid5(NAMESPACE_URL, f"{source_table}:{source_record_id}")
    return EvidenceItem(
        RequestContext.agency,
        case_id,
        source_table,
        str(source_record_id),
        chunk_id,
        text,
    )


def build_tool(
    name: str,
    description: str,
    args: type[BaseModel],
    fn: ToolFn,
    out: AgentOutput,
) -> StructuredTool:
    """Wrap `fn(validated_args) -> text`; scope violations are recorded and never executed."""

    async def run(**kwargs: Any) -> str:
        try:
            return data_block(await fn(args(**kwargs)))
        except CaseScopeViolation as violation:
            out.rejected_case_ids.extend(violation.rejected)
            logger.warning(
                "agent tool rejected",
                extra={"agent": out.agent, "tool": name, "operation": "scope"},
            )
            return OUT_OF_SCOPE

    return StructuredTool.from_function(
        coroutine=run, name=name, description=description, args_schema=args
    )


async def _call_tool(tools: dict[str, StructuredTool], call: ToolCall) -> ToolMessage:
    tool = tools.get(call["name"])
    if tool is None:
        content = f"Unknown tool: {call['name']}"
    else:
        try:
            content = await span(f"tool.{tool.name}")(tool.ainvoke)(call["args"])
        except ValidationError:
            content = INVALID_ARGS
    return ToolMessage(content=content, tool_call_id=call["id"])


async def run_agent(
    role: str,
    tools: list[StructuredTool],
    question: str,
    entities: dict[str, Any],
    scope: CaseScope,
    out: AgentOutput,
) -> None:
    """Bounded tool-calling loop; stops when the model stops calling tools."""
    by_name = {t.name: t for t in tools}
    model = get_chat_model("router").bind_tools(tools)
    scope_ids = sorted(map(str, scope.ids)) if scope.ids else "none (agency-wide)"
    messages: list[Any] = [
        SystemMessage(AGENT_V1.format(role=role)),
        HumanMessage(
            f"Question: {question}\nKnown entities: {json.dumps(entities, default=str)}"
            f"\nKnown scope (case ids): {scope_ids}"
        ),
    ]
    for _ in range(settings.AGENT_MAX_ITERATIONS):
        reply = await model.ainvoke(messages)
        out.iterations += 1
        if not isinstance(reply, AIMessage) or not reply.tool_calls:
            break
        messages.append(reply)
        messages += await asyncio.gather(
            *(_call_tool(by_name, c) for c in reply.tool_calls)
        )
    logger.info(
        "agent done",
        extra={
            "agent": out.agent,
            "iterations": out.iterations,
            "evidence_count": len(out.evidence),
            "rejected_count": len(out.rejected_case_ids),
            "prompt_version": AGENT_PROMPT_VERSION,
        },
    )


@span("retrieval", "retriever")
async def _retrieve(*args: Any, **kwargs: Any) -> list[Any]:
    chunks = await retrieve(*args, **kwargs)
    annotate(retrieved=len(chunks))
    return chunks


@span("rerank", "chain")
async def _rerank(query: str, candidates: list[RerankCandidate]) -> list[Any]:
    ranked = await get_reranker().rerank(query, candidates)
    annotate(candidates=len(candidates), kept=len(ranked))
    return ranked


async def search_reranked(
    query: str, source_types: list[str], scope: CaseScope, out: AgentOutput
) -> str:
    """Hybrid search (store-side filtered by scope and source type) then rerank; kept chunks join the evidence."""
    chunks = await _retrieve(
        RequestContext.agency,
        query,
        case_record_ids=list(scope.ids) if scope.ids else None,
        source_types=source_types,
    )
    by_id = {str(c.id): c for c in chunks}
    ranked = await _rerank(
        query, [RerankCandidate(str(c.id), c.content) for c in chunks]
    )
    seen = {e.chunk_id for e in out.evidence}
    lines: list[str] = []
    for r in ranked:
        c = by_id[r.id]
        if c.id in seen:
            continue
        out.evidence.append(
            EvidenceItem(
                RequestContext.agency,
                c.case_record_id,
                c.source_table,
                c.source_id,
                c.id,
                c.content,
                c.score,
                r.score,
                c.source_type,
            )
        )
        lines.append(f"[{c.source_type} case={c.case_record_id}] {c.content}")
    return "\n".join(lines) or "No matching records."


def case_matches(result: CrossCaseList) -> tuple[CaseList, list[EvidenceItem], str]:
    """Typed matches, their evidence and the tool text, with the total and truncation stated."""
    matches = CaseList.from_result(result)
    lines = [
        f"case_id={c.case_id} number={c.case_number} type={c.case_type} "
        f"status={c.case_status} hearing_date={c.hearing_date}"
        for c in matches.cases
    ]
    evidence = [
        fact_evidence(c.case_id, "case_record", c.case_id, line)
        for c, line in zip(matches.cases, lines, strict=True)
    ]
    header = f"{matches.total} matching cases"
    if matches.truncated:
        header += f"; showing the first {len(matches.cases)}"
    return matches, evidence, "\n".join([header, *lines])
