"""Supervisor: grades each agent's evidence and sends irrelevant agents back with a rewritten query.

Structured facts are tool-written and count as relevant. Chunks above
`SUPERVISOR_ACCEPT_SCORE` are accepted on their rerank score; the rest go to the
LLM grader. An agent with nothing relevant is retried through the graph's
`retrieve` edge, at most `SUPERVISOR_MAX_RETRIES` times, then marked insufficient.
"""

from __future__ import annotations

import json
from typing import Any, cast

from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from quick_chat_api.core.llm.generation.factory import get_chat_model
from quick_chat_api.core.llm.prompts import (
    GRADE_V1,
    REWRITE_V1,
    SUPERVISOR_PROMPT_VERSION,
)
from quick_chat_api.core.rag.agents.schemas import AgentOutput
from quick_chat_api.core.rag.state import EvidenceItem, PipelineState
from quick_chat_api.core.rag.tracing import Node
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger


class Grade(BaseModel):
    relevant_ids: list[str] = Field(default_factory=list)


class Rewrite(BaseModel):
    query: str = Field(min_length=1, max_length=500)


def _default_grader() -> Runnable[Any, Grade]:
    structured = get_chat_model("router").with_structured_output(Grade)
    return cast("Runnable[Any, Grade]", GRADE_V1 | structured)


def _default_rewriter() -> Runnable[Any, Rewrite]:
    structured = get_chat_model("router").with_structured_output(Rewrite)
    return cast("Runnable[Any, Rewrite]", REWRITE_V1 | structured)


async def _relevant(
    out: AgentOutput, query: str, grader: Runnable[Any, Grade] | None
) -> list[EvidenceItem]:
    chunks = [e for e in out.evidence if e.rerank_score is not None]
    borderline = {
        f"c{n}": e
        for n, e in enumerate(
            (
                e
                for e in chunks
                if cast(float, e.rerank_score) < settings.SUPERVISOR_ACCEPT_SCORE
            ),
            1,
        )
    }
    accepted = {e.chunk_id for e in chunks if e not in borderline.values()}
    if borderline:
        grade = await (grader or _default_grader()).ainvoke(
            {
                "query": query,
                "evidence": "\n\n".join(
                    f"[{i}] {e.text}" for i, e in borderline.items()
                ),
            }
        )
        accepted |= {
            borderline[i].chunk_id for i in grade.relevant_ids if i in borderline
        }
    return [e for e in out.evidence if e.rerank_score is None or e.chunk_id in accepted]


def make_supervisor(
    grader: Runnable[Any, Grade] | None = None,
    rewriter: Runnable[Any, Rewrite] | None = None,
) -> Node:
    """Build the node; `grader`/`rewriter` are prompt|structured-model chains (fakes in tests)."""

    async def supervisor(state: PipelineState) -> dict[str, Any]:
        outputs: dict[str, AgentOutput] = dict(state.get("agent_outputs", {}))
        if not outputs:
            return {"retry_agents": []}
        targets = state.get("retry_agents") or list(outputs)
        retries = dict(state.get("retries", {}))
        queries = dict(state.get("sub_queries", {}))
        insufficient = list(state.get("insufficient_domains", []))
        question = state.get("question", "")
        retry: list[str] = []

        for name in targets:
            out = outputs[name]
            query = queries.get(name) or question
            kept = await _relevant(out, query, grader)
            if kept:
                outputs[name] = out.model_copy(update={"evidence": kept})
            elif retries.get(name, 0) < settings.SUPERVISOR_MAX_RETRIES:
                retries[name] = retries.get(name, 0) + 1
                rewritten = await (rewriter or _default_rewriter()).ainvoke(
                    {
                        "agent": name,
                        "query": query,
                        "entities": json.dumps(state.get("entities", {}), default=str),
                    }
                )
                queries[name] = rewritten.query
                retry.append(name)
            else:
                outputs[name] = out.model_copy(update={"evidence": []})
                insufficient.append(name)

        logger.info(
            "rag supervisor",
            extra={
                "graded": len(targets),
                "retry_agents": retry,
                "insufficient_domains": insufficient,
                "retries": retries,
                "prompt_version": SUPERVISOR_PROMPT_VERSION,
            },
        )
        return {
            "agent_outputs": outputs,
            "evidence": [e for o in outputs.values() for e in o.evidence],
            "retries": retries,
            "sub_queries": queries,
            "retry_agents": retry,
            "insufficient_domains": insufficient,
        }

    return supervisor


def after_supervisor(state: PipelineState) -> str:
    return "retrieve" if state.get("retry_agents") else "build_context"
