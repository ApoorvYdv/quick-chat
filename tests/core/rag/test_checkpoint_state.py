from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import EvidenceItem, history_window, initial_state
from quick_chat_api.core.schemas.chat import AskRequest

CONFIG = {"configurable": {"thread_id": "a:s1"}}


def _request(question: str) -> AskRequest:
    return AskRequest(question=question, session_id=uuid4())


async def _evidence(state):
    return {"evidence": [EvidenceItem("a", uuid4(), "t", "1", uuid4(), "secret")]}


async def test_history_accumulates_across_turns() -> None:
    graph = build_graph(InMemorySaver())
    await graph.ainvoke(initial_state(_request("first"), "a", None), CONFIG)
    state = await graph.ainvoke(initial_state(_request("second"), "a", None), CONFIG)

    assert [m.content for m in state["messages"]][::2] == ["first", "second"]
    assert len(history_window(state["messages"], 1)) == 2
    assert history_window(state["messages"], 0) == []


async def test_per_turn_fields_do_not_leak_between_turns() -> None:
    async def clarify(state):
        return {"needs_clarification": "Which case?"}

    saver = InMemorySaver()
    await build_graph(saver, nodes={"resolve_case": clarify}).ainvoke(
        initial_state(_request("one"), "a", None), CONFIG
    )
    state = await build_graph(saver).ainvoke(
        initial_state(_request("two"), "a", None), CONFIG
    )

    assert state["needs_clarification"] is None


async def test_evidence_is_not_checkpointed() -> None:
    saver = InMemorySaver()
    graph = build_graph(saver, nodes={"retrieve": _evidence})
    await graph.ainvoke(initial_state(_request("q"), "a", None), CONFIG)

    stored = saver.get_tuple(CONFIG).checkpoint["channel_values"]
    assert "evidence" not in stored and "contexts" not in stored
