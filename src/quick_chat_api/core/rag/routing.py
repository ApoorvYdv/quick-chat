"""Deterministic-first routing: keyword and entity rules pick the agents.

Rules see only the current question, never history or retrieved text, so
injected content cannot steer the route. An empty or diffuse route is handed
to the LLM fallback by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Agent = Literal["case", "financial", "procedural"]
RouteSource = Literal["rule", "llm"]

AGENTS: tuple[Agent, ...] = ("case", "financial", "procedural")

CASE_NUMBER_RE = re.compile(
    r"\b(?:[A-Z]{1,5}-\d{1,4}(?:-\d+)?|\d{4}-\d+(?:-[A-Z]{1,5})+)\b"
)

_KEYWORDS: dict[Agent, re.Pattern[str]] = {
    "case": re.compile(
        r"\b(charges?|defendants?|part(?:y|ies)|dispositions?|status|judge|"
        r"attorney|offenses?|plea|sanctions?|vehicles?|address(?:es)?)\b",
        re.IGNORECASE,
    ),
    "financial": re.compile(
        r"\b(financ\w*|fines?|fees?|payments?|paid|balance|owes?|owed|restitution|costs?|"
        r"bond|amount)\b",
        re.IGNORECASE,
    ),
    "procedural": re.compile(
        r"\b(hearings?|appearances?|continuances?|docket|scheduled|calendar|"
        r"registered|unregistered|fta|failure to appear)\b",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class Route:
    agents: tuple[Agent, ...]
    source: RouteSource


def route_by_rules(question: str, has_party: bool = False) -> tuple[Agent, ...]:
    """Matching agents in canonical order; `()` means no route or a conflict."""
    matched = {a for a, pattern in _KEYWORDS.items() if pattern.search(question)}
    anchored = has_party or bool(CASE_NUMBER_RE.search(question))
    if anchored:
        matched.add("case")
    # ponytail: all three domains with no anchoring entity is treated as unclear
    # intent; refine with per-domain scoring if the router eval shows misses.
    if len(matched) == len(AGENTS) and not anchored:
        return ()
    return tuple(a for a in AGENTS if a in matched)
