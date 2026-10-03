"""HTTP-free entry points to the graph (also the eval seam)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncEngine

from quick_chat_api.core.rag.checkpointer import agency_checkpointer
from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import PipelineState, initial_state
from quick_chat_api.core.schemas.chat import AskRequest, AskResponse


@dataclass(frozen=True)
class PipelineResult:
    response: AskResponse
    contexts: list[str] = field(default_factory=list)


def _config(agency: str, request: AskRequest) -> RunnableConfig:
    return {"configurable": {"thread_id": f"{agency}:{request.session_id}"}}


def _to_result(state: PipelineState, trace_id: str, session_id: UUID) -> PipelineResult:
    return PipelineResult(
        response=AskResponse(
            answer=state.get("answer", ""),
            citations=state.get("citations", []),
            insufficient_information=state.get("insufficient_information", False),
            conflicts=state.get("conflicts", []),
            resolved_case_ids=state.get("resolved_case_ids", []),
            needs_clarification=state.get("needs_clarification"),
            trace_id=trace_id,
            session_id=session_id,
        ),
        contexts=state.get("contexts", []),
    )


async def run_pipeline(
    engine: AsyncEngine,
    request: AskRequest,
    agency: str,
    trace_id: str,
    case_id: UUID | None = None,
) -> PipelineResult:
    # ponytail: graph compiled per request because the checkpointer is bound to
    # a per-request connection; cache a compiled graph if profiling shows cost.
    async with agency_checkpointer(engine, agency) as checkpointer:
        state = await build_graph(checkpointer).ainvoke(
            initial_state(request, agency, case_id), _config(agency, request)
        )
    return _to_result(cast(PipelineState, state), trace_id, request.session_id)


async def stream_pipeline(
    engine: AsyncEngine,
    request: AskRequest,
    agency: str,
    trace_id: str,
    case_id: UUID | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yields ("status", {node}) per finished node, then ("final", response)."""
    state = initial_state(request, agency, case_id)
    async with agency_checkpointer(engine, agency) as checkpointer:
        async for update in build_graph(checkpointer).astream(
            state, _config(agency, request), stream_mode="updates"
        ):
            for node, delta in update.items():
                state.update(delta or {})  # type: ignore[typeddict-item]
                yield "status", {"node": node}
    result = _to_result(state, trace_id, request.session_id)
    yield "final", result.response.model_dump(mode="json")
