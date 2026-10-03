import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from quick_chat_api.core.rag.graph import NODE_ORDER, build_graph
from quick_chat_api.core.rag.state import EvidenceItem
from quick_chat_api.main import app
from quick_chat_api.utils import dependencies as deps


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(deps, "validate_active_agency", AsyncMock(return_value=None))
    return TestClient(app)


def _body(**extra: object) -> dict:
    return {"question": "What are the charges?", "session_id": str(uuid4()), **extra}


def test_ask_without_evidence_is_insufficient(client: TestClient) -> None:
    resp = client.post("/ask", json=_body(), headers={"agency": "a"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["insufficient_information"] is True
    assert data["citations"] == []


def test_case_route_resolves_path_case_id(client: TestClient) -> None:
    case_id = str(uuid4())
    resp = client.post(f"/cases/{case_id}/ask", json=_body(), headers={"agency": "a"})

    assert resp.json()["resolved_case_ids"] == [case_id]


def test_stream_emits_status_per_node_then_final(client: TestClient) -> None:
    resp = client.post("/ask/stream", json=_body(), headers={"agency": "a"})

    events = [
        line.removeprefix("event: ")
        for line in resp.text.splitlines()
        if line.startswith("event: ")
    ]
    assert events[-1] == "final"
    assert events[:-1] == ["status"] * (len(events) - 1)
    final = resp.text.split("event: final\ndata: ")[1].split("\n")[0]
    assert json.loads(final)["insufficient_information"] is True


def test_invalid_session_id_is_422(client: TestClient) -> None:
    resp = client.post(
        "/ask", json={"question": "x", "session_id": "nope"}, headers={"agency": "a"}
    )
    assert resp.status_code == 422


async def test_clarification_short_circuits_without_llm() -> None:
    called = AsyncMock()

    async def ask_clarification(state):
        return {"needs_clarification": "Which case?"}

    graph = build_graph(nodes={"resolve_case": ask_clarification, "generate": called})
    state = await graph.ainvoke({"question": "q", "agency": "a"})

    assert state["needs_clarification"] == "Which case?"
    called.assert_not_called()


async def test_real_node_replaces_fake_without_signature_change() -> None:
    item = EvidenceItem("a", uuid4(), "t", "1", uuid4(), "text")

    async def retrieve(state):
        return {"evidence": [item]}

    async def generate(state):
        return {"answer": "from evidence", "insufficient_information": False}

    graph = build_graph(nodes={"retrieve": retrieve, "generate": generate})
    state = await graph.ainvoke({"question": "q", "agency": "a"})

    assert state["answer"] == "from evidence"
    assert state["contexts"] == ["text"]
    assert set(NODE_ORDER) >= {"retrieve", "generate"}
