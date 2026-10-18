"""Agents node: Case-first when other agents need case ids, then concurrent fan-out."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

from quick_chat_api.core.rag.agents.case import run_case_agent
from quick_chat_api.core.rag.agents.financial import run_financial_agent
from quick_chat_api.core.rag.agents.procedural import run_procedural_agent
from quick_chat_api.core.rag.agents.schemas import (
    AgentOutput,
    CaseAgentOutput,
    ProceduralAgentOutput,
)
from quick_chat_api.core.rag.agents.scope import CaseScope
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.core.rag.tracing import Node, traced_node

AgentRunner = Callable[[PipelineState, CaseScope], Awaitable[Any]]

RUNNERS: dict[str, AgentRunner] = {
    "case": run_case_agent,
    "financial": run_financial_agent,
    "procedural": run_procedural_agent,
}


async def _run_one(name: str, state: PipelineState, scope: CaseScope) -> AgentOutput:
    async def node(state: PipelineState) -> dict[str, Any]:
        return {"out": await RUNNERS[name](state, scope)}

    return (await traced_node(f"agent.{name}")(node)(state))["out"]


def _clarification(out: CaseAgentOutput) -> str:
    people = "; ".join(
        f"{c.full_name} (born {c.dob or 'unknown'}, cases {', '.join(c.case_numbers)})"
        for c in out.candidates
    )
    return f"More than one person matches. Which one do you mean? {people}"


def make_agents() -> Node:
    async def agents(state: PipelineState) -> dict[str, Any]:
        names = [a for a in state.get("agents", []) if a in RUNNERS]
        entities = state.get("entities", {})
        anchored = bool(entities.get("case_numbers") or entities.get("parties"))
        known = [state.get("requested_case_id"), *state.get("resolved_case_ids", [])]
        scope = CaseScope.of(i for i in known if i)
        outputs: dict[str, AgentOutput] = {}

        rest = names
        if "case" in names and len(names) > 1:
            case_out = cast(CaseAgentOutput, await _run_one("case", state, scope))
            outputs["case"] = case_out
            if case_out.candidates:
                return _result(outputs, scope, _clarification(case_out))
            if case_out.case_ids:
                scope = CaseScope.of(case_out.case_ids)
            elif anchored:
                # The question names a case or person that does not exist here;
                # dependent agents must not fall back to an agency-wide search.
                return _result(outputs, scope)
            rest = [n for n in names if n != "case"]

        done = await asyncio.gather(*(_run_one(n, state, scope) for n in rest))
        outputs.update(zip(rest, done, strict=True))
        return _result(outputs, scope)

    return traced_node("agents")(agents)


def _result(
    outputs: dict[str, AgentOutput], scope: CaseScope, clarification: str | None = None
) -> dict[str, Any]:
    ids: dict[UUID, None] = dict.fromkeys(scope.ids or ())
    for out in outputs.values():
        if isinstance(out, CaseAgentOutput | ProceduralAgentOutput) and not (
            isinstance(out, CaseAgentOutput) and out.candidates
        ):
            ids.update(dict.fromkeys(out.case_ids))
    return {
        "agent_outputs": outputs,
        "evidence": [e for out in outputs.values() for e in out.evidence],
        "resolved_case_ids": list(ids),
        "needs_clarification": clarification,
    }
