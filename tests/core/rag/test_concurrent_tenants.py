import asyncio
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from starlette_context import request_cycle_context

from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import initial_state
from quick_chat_api.core.schemas.chat import AskRequest
from quick_chat_api.utils.context import RequestContext


async def _echo_agency(state):
    # Yield several times so the two requests interleave across node hops.
    for _ in range(5):
        await asyncio.sleep(0)
    return {"answer": RequestContext.agency}


async def _ask(saver: InMemorySaver, agency: str) -> tuple[str, str]:
    request = AskRequest(question="q", session_id=uuid4())
    config = {"configurable": {"thread_id": f"{agency}:{request.session_id}"}}
    with request_cycle_context({}):
        RequestContext.agency = agency
        graph = build_graph(saver, nodes={"understand": _echo_agency})
        state = await graph.ainvoke(initial_state(request, agency, None), config)
    return state["agency"], state["answer"]


async def test_simultaneous_requests_never_cross_tenants() -> None:
    saver = InMemorySaver()
    agencies = [f"agency_{i}" for i in range(20)]

    results = await asyncio.gather(*(_ask(saver, a) for a in agencies))

    assert results == [(a, a) for a in agencies]
