"""Answer-pipeline graph.

Nodes are placeholders until S3 replaces them one by one; swapping a node
means passing a different callable in `nodes`, no signature changes.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.core.rag.tracing import Node, traced_node

INSUFFICIENT_ANSWER = (
    "The available case data does not provide enough information to answer."
)


async def understand(state: PipelineState) -> dict[str, Any]:
    return {}


async def resolve_case(state: PipelineState) -> dict[str, Any]:
    case_id = state.get("requested_case_id")
    return {"resolved_case_ids": [case_id] if case_id else []}


async def retrieve(state: PipelineState) -> dict[str, Any]:
    return {"evidence": []}


async def build_context(state: PipelineState) -> dict[str, Any]:
    return {"contexts": [e.text for e in state.get("evidence", [])]}


async def generate(state: PipelineState) -> dict[str, Any]:
    return {"answer": INSUFFICIENT_ANSWER, "insufficient_information": True}


async def finalize(state: PipelineState) -> dict[str, Any]:
    if state.get("answer"):
        return {}
    return {"answer": INSUFFICIENT_ANSWER, "insufficient_information": True}


DEFAULT_NODES: dict[str, Node] = {
    "understand": understand,
    "resolve_case": resolve_case,
    "retrieve": retrieve,
    "build_context": build_context,
    "generate": generate,
    "finalize": finalize,
}

NODE_ORDER = tuple(DEFAULT_NODES)


def _after_resolve(state: PipelineState) -> str:
    return "finalize" if state.get("needs_clarification") else "retrieve"


def _after_context(state: PipelineState) -> str:
    # No evidence -> no LLM call.
    return "generate" if state.get("contexts") else "finalize"


def build_graph(
    checkpointer: BaseCheckpointSaver | None = None,
    nodes: dict[str, Node] | None = None,
) -> CompiledStateGraph:
    impl = {**DEFAULT_NODES, **(nodes or {})}
    graph = StateGraph(PipelineState)
    for name, fn in impl.items():
        graph.add_node(name, traced_node(name)(fn))  # type: ignore[call-overload]
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "resolve_case")
    graph.add_conditional_edges("resolve_case", _after_resolve)
    graph.add_edge("retrieve", "build_context")
    graph.add_conditional_edges("build_context", _after_context)
    graph.add_edge("generate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
