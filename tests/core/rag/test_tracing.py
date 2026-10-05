from uuid import uuid4

from starlette_context import request_cycle_context

from quick_chat_api.core.llm.prompts import UNDERSTAND_V1
from quick_chat_api.core.rag import tracing
from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import initial_state
from quick_chat_api.core.schemas.chat import AskRequest
from quick_chat_api.utils.context import RequestContext
from quick_chat_api.utils.dependencies import get_current_user


async def test_sinks_get_metadata_only(monkeypatch) -> None:
    events: list[tracing.NodeEvent] = []
    monkeypatch.setattr(tracing, "_sinks", lambda: [events.append])

    request = AskRequest(question="secret question", session_id=uuid4())
    await build_graph().ainvoke(initial_state(request, "a", None))

    assert events[0].node == "understand"
    assert all(e.agency == "a" and e.status == "ok" for e in events)
    assert "secret" not in repr(events)


def test_langsmith_sink_off_by_default() -> None:
    assert tracing._sinks() == [tracing._log_sink]


async def test_current_user_stub_populates_context() -> None:
    with request_cycle_context({}):
        user = await get_current_user()
        assert RequestContext.user_details.username == user.username == "anonymous"


def test_understand_prompt_formats() -> None:
    messages = UNDERSTAND_V1.format_messages(question="q", history=[])
    assert [m.type for m in messages] == ["system", "human"]
