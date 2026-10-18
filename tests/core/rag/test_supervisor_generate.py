"""Supervisor retry loop, context builder and generate node with fake chains (no DB/LLM)."""

from uuid import uuid4

from langchain_core.runnables import RunnableLambda

from quick_chat_api.core.rag.agents.schemas import AgentOutput
from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.nodes import make_generate, make_supervisor
from quick_chat_api.core.rag.nodes.supervisor import Grade, Rewrite
from quick_chat_api.core.rag.state import EvidenceItem
from quick_chat_api.modules.rag.context_builder import build_context
from tests.core.rag.offline import OFFLINE_NODES

CASE = uuid4()


def _fact(rec: str, text: str) -> EvidenceItem:
    return EvidenceItem("a", CASE, "payment_record", rec, uuid4(), text)


def _chunk(score: float) -> EvidenceItem:
    return EvidenceItem("a", CASE, "note", "n1", uuid4(), "narrative", 0.5, score)


async def test_irrelevant_agent_retried_exactly_twice_then_insufficient() -> None:
    runs, rewrites = [], []

    async def retrieve(state):
        agent = "financial"
        runs.append(state["sub_queries"][agent])
        out = AgentOutput(agent=agent, evidence=[_chunk(-1.0)])
        outs = {**state.get("agent_outputs", {}), agent: out}
        return {"agent_outputs": outs, "evidence": out.evidence}

    def rewrite(inputs):
        rewrites.append(inputs["query"])
        return Rewrite(query=f"q{len(rewrites)}")

    never = RunnableLambda(lambda _: Grade(relevant_ids=[]))
    generate_calls = []

    async def generate(state):
        generate_calls.append(1)
        return {}

    graph = build_graph(
        nodes={
            **OFFLINE_NODES,
            "agents": retrieve,
            "supervisor": make_supervisor(never, RunnableLambda(rewrite)),
            "generate": generate,
        }
    )
    state = await graph.ainvoke(
        {
            "question": "q",
            "agency": "a",
            "agents": ["financial"],
            "sub_queries": {"financial": "q0"},
            "retries": {},
            "retry_agents": [],
            "insufficient_domains": [],
            "agent_outputs": {},
        }
    )
    assert runs == ["q0", "q1", "q2"] and len(rewrites) == 2
    assert state["insufficient_domains"] == ["financial"]
    assert state["insufficient_information"] is True and not generate_calls


async def test_empty_evidence_makes_no_llm_call() -> None:
    def boom(_):
        raise AssertionError("LLM called")

    out = await make_generate(RunnableLambda(boom))({"contexts": []})
    assert out["insufficient_information"] is True


async def test_foreign_citation_dropped() -> None:
    built = build_context([_fact("p1", "amount=5")], 1000)
    llm = RunnableLambda(
        lambda _: __import__(
            "quick_chat_api.core.rag.nodes.generate", fromlist=["Answer"]
        ).Answer(answer="paid 5", citations=["e1", "e99"])
    )
    out = await make_generate(llm)(
        {"contexts": built.texts, "context_map": built.by_alias}
    )
    assert [c.source_record_id for c in out["citations"]] == ["p1"]
    assert out["insufficient_information"] is False


def test_context_prefers_facts_flags_conflicts_and_fits_budget() -> None:
    chunk = EvidenceItem(
        "a", CASE, "payment_record", "p1", uuid4(), "free text", 0.1, 5.0
    )
    built = build_context(
        [chunk, _fact("p1", "status=PAID"), _fact("p1", "status=VOID")], 1000
    )
    assert all(i.evidence.rerank_score is None for i in built.items)
    assert len(built.conflicts) == 1 and "status" in built.conflicts[0]
    assert build_context([_fact("p1", "x" * 400)], 10).items == ()
