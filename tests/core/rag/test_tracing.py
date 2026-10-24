import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langsmith import Client
from starlette_context import request_cycle_context

from quick_chat_api.core.llm.prompts import UNDERSTAND_V1
from quick_chat_api.core.rag import pipeline, tracing
from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import initial_state
from quick_chat_api.core.schemas.chat import AskRequest
from quick_chat_api.utils.context import RequestContext
from quick_chat_api.utils.dependencies import get_current_user
from tests.core.rag.offline import OFFLINE_NODES


async def test_sinks_get_metadata_only(monkeypatch) -> None:
    events: list[tracing.NodeEvent] = []
    monkeypatch.setattr(tracing, "_sinks", lambda: [events.append])

    request = AskRequest(question="secret question", session_id=uuid4())
    await build_graph(nodes=OFFLINE_NODES).ainvoke(initial_state(request, "a", None))

    assert events[0].node == "understand"
    assert all(e.agency == "a" and e.status == "ok" for e in events)
    assert "secret" not in repr(events)


async def test_one_parent_run_with_redacted_children(monkeypatch) -> None:
    sent: list[bytes] = []
    session = MagicMock()
    session.request.side_effect = lambda *a, **kw: (
        sent.append(kw.get("data") or b""),
        MagicMock(status_code=200),
    )[1]
    client = Client(
        api_key="k",
        api_url="http://langsmith.test",
        session=session,
        auto_batch_tracing=False,
        hide_inputs=tracing._blank,
        hide_outputs=tracing._blank,
    )
    monkeypatch.setattr(tracing, "langsmith_client", lambda: client)
    monkeypatch.setattr(tracing.settings, "LANGSMITH_ENABLED", True)

    @asynccontextmanager
    async def saver(engine, agency):
        yield InMemorySaver()

    monkeypatch.setattr(pipeline, "agency_checkpointer", saver)
    monkeypatch.setattr(
        pipeline, "build_graph", lambda cp: build_graph(cp, nodes=OFFLINE_NODES)
    )
    request = AskRequest(question="secret question", session_id=uuid4())

    await pipeline.run_pipeline(None, request, "agency_a", "trace-1")  # type: ignore[arg-type]
    client.flush()

    body = b"".join(sent).decode()
    posts = json.loads(
        "[" + ",".join(b.decode() for b in sent if b.startswith(b"{")) + "]"
    )
    runs = list({r["id"]: r for r in posts if r.get("name")}.values())
    assert "secret" not in body
    assert sum(1 for r in runs if r["name"] == "request") == 1
    assert {"understand", "agents", "finalize"} <= {r["name"] for r in runs}
    parents = {r["id"]: r.get("parent_run_id") for r in runs}
    nodes = [r for r in runs if r["name"] in {"understand", "agents", "finalize"}]
    assert all(
        r["trace_id"] == next(x["trace_id"] for x in runs if x["name"] == "request")
        for r in nodes
    )
    assert all(parents[r["id"]] for r in nodes)


async def test_current_user_stub_populates_context() -> None:
    with request_cycle_context({}):
        user = await get_current_user()
        assert RequestContext.user_details.username == user.username == "anonymous"


def test_understand_prompt_formats() -> None:
    messages = UNDERSTAND_V1.format_messages(question="q", history=[])
    assert [m.type for m in messages] == ["system", "human"]


def test_log_content_flag_disables_redaction(monkeypatch) -> None:
    assert tracing._redactor() is tracing._blank
    monkeypatch.setattr(tracing.settings, "LANGSMITH_LOG_CONTENT", True)
    assert tracing._redactor() is None
