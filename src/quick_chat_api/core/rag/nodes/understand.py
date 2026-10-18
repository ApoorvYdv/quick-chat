"""Rewrite + route node.

Entities and routing are deterministic. The LLM (one structured-output call at
most) runs only for a follow-up question that needs history resolved, a
possible party name the rules cannot extract, or a rule route that is empty or
conflicting. LLM agents are used only when the rules did not decide.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from quick_chat_api.core.constants.constants import (
    CaseAppearanceStatus,
    CaseStatus,
    PartyType,
)
from quick_chat_api.core.llm.generation.factory import get_chat_model
from quick_chat_api.core.llm.prompts import UNDERSTAND_PROMPT_VERSION, UNDERSTAND_V2
from quick_chat_api.core.rag.routing import (
    AGENTS,
    CASE_NUMBER_RE,
    Agent,
    RouteSource,
    route_by_rules,
)
from quick_chat_api.core.rag.state import PipelineState, history_window
from quick_chat_api.core.rag.tracing import Node
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger
from quick_chat_api.utils.helper import get_client_timezone

_FOLLOW_UP_RE = re.compile(
    r"\b(it|its|they|them|their|that|those|this|these|he|him|his|she|her|same)\b"
    r"|^\s*(and|also|what about)\b",
    re.IGNORECASE,
)
_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RELATIVE_DAYS = {"yesterday": -1, "today": 0, "tomorrow": 1}


class PartyRef(BaseModel):
    name: str
    role: PartyType | None = None


class Entities(BaseModel):
    case_numbers: list[str] = Field(default_factory=list)
    parties: list[PartyRef] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    appearance_statuses: list[CaseAppearanceStatus] = Field(default_factory=list)
    case_statuses: list[CaseStatus] = Field(default_factory=list)


class SubQuery(BaseModel):
    agent: Agent
    query: str


class Understanding(BaseModel):
    """Structured output of the rewrite/fallback LLM call."""

    entities: Entities = Field(default_factory=Entities)
    agents: list[Agent] = Field(default_factory=list)
    sub_queries: list[SubQuery] = Field(default_factory=list)


def _today() -> date:
    return datetime.now(get_client_timezone()).date()


def _dates(question: str) -> list[date]:
    found: list[date] = []
    for y, m, d in _ISO_DATE_RE.findall(question):
        found.append(date(int(y), int(m), int(d)))
    for m, d, y in _US_DATE_RE.findall(question):
        found.append(date(int(y), int(m), int(d)))
    today = _today()
    for word, offset in _RELATIVE_DAYS.items():
        if re.search(rf"\b{word}\b", question, re.IGNORECASE):
            found.append(today + timedelta(days=offset))
    return found


def _enum_hits[E: (CaseAppearanceStatus, CaseStatus)](
    question: str, enum: type[E]
) -> list[E]:
    return [
        m
        for m in enum
        if re.search(rf"\b{re.escape(m.value)}\b", question, re.IGNORECASE)
    ]


def extract_entities(question: str) -> Entities:
    """Deterministic extraction; party names need the LLM."""
    return Entities(
        case_numbers=list(dict.fromkeys(CASE_NUMBER_RE.findall(question))),
        dates=_dates(question),
        appearance_statuses=_enum_hits(question, CaseAppearanceStatus),
        case_statuses=_enum_hits(question, CaseStatus),
    )


def _merge(base: Entities, extra: Entities) -> Entities:
    data = {
        f: list(dict.fromkeys([*getattr(base, f), *getattr(extra, f)]))
        for f in Entities.model_fields
        if f != "parties"
    }
    parties = {p.name.lower(): p for p in [*base.parties, *extra.parties]}
    return Entities(**data, parties=list(parties.values()))


def _needs_llm(question: str, has_history: bool) -> bool:
    follow_up = has_history and bool(_FOLLOW_UP_RE.search(question))
    return follow_up or bool(_NAME_RE.search(question))


def _default_llm() -> Runnable[Any, Understanding]:
    structured = get_chat_model("router").with_structured_output(Understanding)
    return cast("Runnable[Any, Understanding]", UNDERSTAND_V2 | structured)


def make_understand(llm: Runnable[Any, Understanding] | None = None) -> Node:
    """Build the node; `llm` is the prompt|structured-model chain (fake in tests)."""

    async def understand(state: PipelineState) -> dict[str, Any]:
        question = state.get("question", "")
        history: list[AnyMessage] = history_window(
            state.get("messages", []), settings.CHAT_HISTORY_MAX_TURNS
        )
        entities = extract_entities(question)
        agents = route_by_rules(question)
        source: RouteSource = "rule"
        parsed: Understanding | None = None

        if not agents or _needs_llm(question, bool(history)):
            chain = llm or _default_llm()
            parsed = await chain.ainvoke(
                {
                    "question": question,
                    "history": history,
                    "today": _today().isoformat(),
                }
            )
            entities = _merge(entities, parsed.entities)
            agents = route_by_rules(question, bool(entities.parties))
        if not agents and parsed:
            agents, source = tuple(dict.fromkeys(parsed.agents)), "llm"

        queries = {s.agent: s.query for s in (parsed.sub_queries if parsed else [])}
        sub_queries = {a: queries.get(a) or question for a in agents if a in AGENTS}
        logger.info(
            "rag route",
            extra={
                "route_source": source,
                "agents": list(agents),
                "prompt_version": UNDERSTAND_PROMPT_VERSION,
            },
        )
        return {
            "entities": entities.model_dump(mode="json"),
            "agents": list(agents),
            "sub_queries": sub_queries,
            "route_source": source,
        }

    return understand
