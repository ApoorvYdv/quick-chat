"""Agents with a scripted chat model and fake data tools (no DB, Qdrant or LLM)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from starlette_context import request_cycle_context

from quick_chat_api.core.rag.agents import (
    CaseAgentOutput,
    CaseScope,
    FinancialAgentOutput,
    ProceduralAgentOutput,
    make_agents,
)
from quick_chat_api.core.rag.agents import case as case_mod
from quick_chat_api.core.rag.agents import financial as financial_mod
from quick_chat_api.core.rag.agents import procedural as procedural_mod
from quick_chat_api.core.rag.agents import runner as runner_mod
from quick_chat_api.modules.rag.structured.cross_case import (
    CaseList,
    CaseRef,
    PartyCandidate,
)
from quick_chat_api.modules.rag.structured.financial import PaymentSummary
from quick_chat_api.utils.context import RequestContext

CASE_A, CASE_B = uuid4(), uuid4()


class ScriptedModel:
    """Chat model stand-in: replays one scripted tool-call turn, then stops."""

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self.calls = calls
        self.turns = 0

    def bind_tools(self, _tools: list) -> ScriptedModel:
        return self

    async def ainvoke(self, _messages: list) -> AIMessage:
        self.turns += 1
        if self.turns > 1 or not self.calls:
            return AIMessage("done")
        return AIMessage(
            "",
            tool_calls=[
                {"name": n, "args": a, "id": f"c{i}"}
                for i, (n, a) in enumerate(self.calls)
            ],
        )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    @asynccontextmanager
    async def fake_session():
        yield None

    for mod in (runner_mod, case_mod, financial_mod, procedural_mod):
        monkeypatch.setattr(mod, "tenant_session", fake_session, raising=False)
    with request_cycle_context({}):
        RequestContext.agency = "agency_a"
        yield


def _script(
    monkeypatch: pytest.MonkeyPatch, **by_agent: list[tuple[str, dict]]
) -> None:
    """Pick the scripted calls by the agent role in the system prompt."""

    def get_chat_model(_role: str) -> object:
        class Router:
            def bind_tools(self, tools: list) -> ScriptedModel:
                names = {t.name for t in tools}
                key = (
                    "case"
                    if "lookup_case_number" in names
                    else "financial"
                    if "get_payments" in names
                    else "procedural"
                )
                return ScriptedModel(by_agent.get(key, []))

        return Router()

    monkeypatch.setattr(runner_mod, "get_chat_model", get_chat_model)


def _ref(case_id: UUID, number: str) -> CaseRef:
    return CaseRef(case_id, number, "CRIMINAL", "OPEN", date(2026, 3, 4))


async def test_financial_and_procedural_run_concurrently(monkeypatch) -> None:
    both_started = asyncio.Event()
    started = 0

    async def payments(_session, ids):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 1)  # fails if run serially
        return {i: PaymentSummary(payments=[], total_paid=Decimal("0")) for i in ids}

    async def appearances(_session, case_ids, case_numbers=()):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 1)
        return []

    monkeypatch.setattr(financial_mod, "get_payment_summaries", payments)
    monkeypatch.setattr(procedural_mod, "get_appearances", appearances)
    _script(
        monkeypatch,
        financial=[("get_payments", {"case_ids": [str(CASE_A)]})],
        procedural=[("get_appearances", {"case_ids": [str(CASE_A)]})],
    )
    node = make_agents()
    out = await node(
        {
            "question": "payments and hearings",
            "agents": ["financial", "procedural"],
            "requested_case_id": CASE_A,
        }
    )
    assert set(out["agent_outputs"]) == {"financial", "procedural"}
    assert started == 2


async def test_out_of_scope_case_id_is_rejected_and_not_queried(monkeypatch) -> None:
    called = False

    async def payments(_session, ids):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(financial_mod, "get_payment_summaries", payments)
    _script(monkeypatch, financial=[("get_payments", {"case_ids": [str(CASE_B)]})])
    out = await financial_mod.run_financial_agent(
        {"question": "q"}, CaseScope.of([CASE_A])
    )
    assert isinstance(out, FinancialAgentOutput)
    assert out.rejected_case_ids == [CASE_B] and not called and not out.payments


async def test_payment_evidence_has_no_payee_pii(monkeypatch) -> None:
    pay = SimpleNamespace(
        id=uuid4(),
        amount=Decimal("25.00"),
        payment_datetime=None,
        void=False,
        payee_email="x@y.z",
    )

    async def payments(_session, ids):
        return {ids[0]: PaymentSummary(payments=[pay], total_paid=Decimal("25.00"))}

    monkeypatch.setattr(financial_mod, "get_payment_summaries", payments)
    _script(monkeypatch, financial=[("get_payments", {"case_ids": [str(CASE_A)]})])
    out = await financial_mod.run_financial_agent(
        {"question": "q"}, CaseScope.of([CASE_A])
    )
    assert out.payments[0].total_paid == Decimal("25.00")
    assert "x@y.z" not in out.evidence[0].text


async def test_case_first_scopes_dependents(monkeypatch) -> None:
    async def lookup(_session, number):
        return [
            SimpleNamespace(
                id=CASE_A,
                case_number=number,
                case_type="CRIMINAL",
                case_status="OPEN",
                hearing_date=None,
            )
        ]

    seen: list[list[UUID]] = []

    async def payments(_session, ids):
        seen.append(ids)
        return {i: PaymentSummary(payments=[], total_paid=Decimal("0")) for i in ids}

    monkeypatch.setattr(case_mod, "get_cases_by_number", lookup)
    monkeypatch.setattr(financial_mod, "get_payment_summaries", payments)
    _script(
        monkeypatch,
        case=[("lookup_case_number", {"case_number": "CR-1"})],
        # The model also asks for another case; scope must block it.
        financial=[
            ("get_payments", {"case_ids": [str(CASE_A)]}),
            ("get_payments", {"case_ids": [str(CASE_B)]}),
        ],
    )
    out = await make_agents()(
        {
            "question": "fines on CR-1",
            "agents": ["case", "financial"],
            "entities": {"case_numbers": ["CR-1"]},
        }
    )
    assert out["resolved_case_ids"] == [CASE_A]
    assert seen == [[CASE_A]]
    assert out["agent_outputs"]["financial"].rejected_case_ids == [CASE_B]


async def test_ambiguous_party_short_circuits_with_clarification(monkeypatch) -> None:
    async def by_party(_session, name, role):
        return CaseList(
            candidates=(
                PartyCandidate("Jo Smith", date(1990, 1, 1), ("CR-1",)),
                PartyCandidate("Jo Smith", date(1985, 5, 5), ("CR-2",)),
            )
        )

    monkeypatch.setattr(case_mod, "find_cases_by_party", by_party)
    _script(monkeypatch, case=[("find_cases_by_party", {"name": "Jo Smith"})])
    out = await make_agents()(
        {
            "question": "Jo Smith fines",
            "agents": ["case", "financial"],
            "entities": {"parties": [{"name": "Jo Smith"}]},
        }
    )
    assert "financial" not in out["agent_outputs"]
    assert "CR-1" in out["needs_clarification"] and "CR-2" in out["needs_clarification"]


async def test_unknown_anchor_skips_dependents(monkeypatch) -> None:
    async def lookup(_session, number):
        return []

    monkeypatch.setattr(case_mod, "get_cases_by_number", lookup)
    _script(monkeypatch, case=[("lookup_case_number", {"case_number": "CR-404"})])
    out = await make_agents()(
        {
            "question": "fines on CR-404",
            "agents": ["case", "financial"],
            "entities": {"case_numbers": ["CR-404"]},
        }
    )
    assert set(out["agent_outputs"]) == {"case"} and out["evidence"] == []


async def test_procedural_filter_is_agency_wide_without_scope(monkeypatch) -> None:
    async def by_appearance(_session, *, status, hearing_date):
        return CaseList(cases=(_ref(CASE_A, "CR-1"),), total=57, truncated=True)

    monkeypatch.setattr(procedural_mod, "filter_cases_by_appearance", by_appearance)
    _script(
        monkeypatch,
        procedural=[
            (
                "filter_appearances",
                {"status": "REGISTERED", "hearing_date": "2026-03-04"},
            )
        ],
    )
    out = await procedural_mod.run_procedural_agent({"question": "q"}, CaseScope())
    assert isinstance(out, ProceduralAgentOutput)
    assert (
        out.matches.total == 57 and out.matches.truncated and out.case_ids == [CASE_A]
    )


async def test_invalid_tool_args_are_rejected_not_raised(monkeypatch) -> None:
    _script(monkeypatch, case=[("lookup_case_number", {"case_number": ""})])
    out = await case_mod.run_case_agent({"question": "q"}, CaseScope())
    assert isinstance(out, CaseAgentOutput) and out.evidence == []


async def test_loop_is_capped(monkeypatch) -> None:
    class Forever:
        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _m):
            return AIMessage(
                "",
                tool_calls=[
                    {
                        "name": "lookup_case_number",
                        "args": {"case_number": "X"},
                        "id": "1",
                    }
                ],
            )

    async def lookup(_s, _n):
        return []

    monkeypatch.setattr(case_mod, "get_cases_by_number", lookup)
    monkeypatch.setattr(runner_mod, "get_chat_model", lambda _r: Forever())
    monkeypatch.setattr(runner_mod.settings, "AGENT_MAX_ITERATIONS", 3)
    out = await case_mod.run_case_agent({"question": "q"}, CaseScope())
    assert out.iterations == 3


async def test_concurrent_agencies_do_not_cross(monkeypatch) -> None:
    async def payments(_session, ids):
        await asyncio.sleep(0)
        pay = SimpleNamespace(
            id=uuid4(), amount=Decimal("1"), payment_datetime=None, void=False
        )
        return {ids[0]: PaymentSummary(payments=[pay], total_paid=Decimal("1"))}

    monkeypatch.setattr(financial_mod, "get_payment_summaries", payments)
    _script(monkeypatch, financial=[("get_payments", {"case_ids": [str(CASE_A)]})])

    async def request(agency: str) -> set[str]:
        with request_cycle_context({}):
            RequestContext.agency = agency
            out = await financial_mod.run_financial_agent(
                {"question": "q"}, CaseScope()
            )
            return {e.agency for e in out.evidence}

    results = await asyncio.gather(*(request(f"agency_{i}") for i in range(6)))
    assert results == [{f"agency_{i}"} for i in range(6)]
