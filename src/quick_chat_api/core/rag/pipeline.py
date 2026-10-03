"""HTTP-free entry points to the graph (also the eval seam)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import UUID

from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.core.schemas.chat import AskRequest, AskResponse


@dataclass(frozen=True)
class PipelineResult:
    response: AskResponse
    contexts: list[str] = field(default_factory=list)


@lru_cache
def get_graph():  # type: ignore[no-untyped-def]
    # ponytail: no checkpointer yet (S1.7); multi-turn memory lands with it.
    return build_graph()


def _initial_state(
    request: AskRequest, agency: str, case_id: UUID | None
) -> PipelineState:
    return {
        "question": request.question,
        "agency": agency,
        "session_id": request.session_id,
        "requested_case_id": case_id or request.case_id,
        "case_number": request.case_number,
        "mode": request.mode,
    }


def _config(agency: str, request: AskRequest) -> dict[str, Any]:
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
    request: AskRequest,
    agency: str,
    trace_id: str,
    case_id: UUID | None = None,
) -> PipelineResult:
    state = await get_graph().ainvoke(
        _initial_state(request, agency, case_id), _config(agency, request)
    )
    return _to_result(state, trace_id, request.session_id)


async def stream_pipeline(
    request: AskRequest,
    agency: str,
    trace_id: str,
    case_id: UUID | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yields ("status", {node}) per finished node, then ("final", response)."""
    state: PipelineState = _initial_state(request, agency, case_id)
    async for update in get_graph().astream(
        state, _config(agency, request), stream_mode="updates"
    ):
        for node, delta in update.items():
            state.update(delta or {})  # type: ignore[typeddict-item]
            yield "status", {"node": node}
    result = _to_result(state, trace_id, request.session_id)
    yield "final", result.response.model_dump(mode="json")
