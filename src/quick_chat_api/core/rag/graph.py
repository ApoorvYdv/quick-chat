"""Answer-pipeline graph.

Nodes are placeholders until S3 replaces them one by one; swapping a node
means passing a different callable in `nodes`, no signature changes.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from quick_chat_api.core.rag.nodes import (
    INSUFFICIENT_ANSWER,
    after_supervisor,
    make_build_context,
    make_generate,
    make_supervisor,
)
from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.core.rag.tracing import Node, traced_node


async def understand(state: PipelineState) -> dict[str, Any]:
    return {}


async def resolve_case(state: PipelineState) -> dict[str, Any]:
    case_id = state.get("requested_case_id")
    return {"resolved_case_ids": [case_id] if case_id else []}


async def retrieve(state: PipelineState) -> dict[str, Any]:
    return {"evidence": []}


async def finalize(state: PipelineState) -> dict[str, Any]:
    clarification = state.get("needs_clarification")
    answer = state.get("answer") or clarification or INSUFFICIENT_ANSWER
    return {
        "answer": answer,
        "insufficient_information": bool(
            state.get("insufficient_information")
            or not (state.get("answer") or clarification)
        ),
        "messages": [
            HumanMessage(state.get("question", "")),
            AIMessage(answer),
        ],
        "last_case_ids": state.get("resolved_case_ids", []),
    }


DEFAULT_NODES: dict[str, Node] = {
    "understand": understand,
    "resolve_case": resolve_case,
    "retrieve": retrieve,
    "supervisor": make_supervisor(),
    "build_context": make_build_context(),
    "generate": make_generate(),
    "finalize": finalize,
}

NODE_ORDER = tuple(DEFAULT_NODES)


def _after_resolve(state: PipelineState) -> str:
    return "finalize" if state.get("needs_clarification") else "retrieve"


def _after_retrieve(state: PipelineState) -> str:
    return "finalize" if state.get("needs_clarification") else "supervisor"


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
    graph.add_conditional_edges("retrieve", _after_retrieve)
    graph.add_conditional_edges("supervisor", after_supervisor)
    graph.add_conditional_edges("build_context", _after_context)
    graph.add_edge("generate", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
