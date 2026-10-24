"""Context construction: dedupe, prefer structured facts, detect conflicts, fit the token budget.

Structured facts are the evidence items written by tools (no rerank score); chunks
carry one. Items keep their source metadata and are grouped by case, so the LLM
never sees an untagged or cross-case blur of records.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from quick_chat_api.core.rag.state import EvidenceItem

_FIELD_RE = re.compile(r"(\w+)=(\S+)")
_CHARS_PER_TOKEN = 4  # ponytail: char estimate, swap in the model tokenizer if the budget must be exact

RecordKey = tuple[UUID, str, str]


@dataclass(frozen=True)
class ContextItem:
    alias: str
    evidence: EvidenceItem

    @property
    def text(self) -> str:
        e = self.evidence
        return (
            f"[{self.alias}] case={e.case_record_id} "
            f"source={e.source_table}/{e.source_record_id}\n{e.text}"
        )


@dataclass(frozen=True)
class BuiltContext:
    items: tuple[ContextItem, ...] = ()
    conflicts: tuple[str, ...] = ()
    dropped: int = 0

    @property
    def texts(self) -> list[str]:
        return [i.text for i in self.items]

    @property
    def by_alias(self) -> dict[str, EvidenceItem]:
        return {i.alias: i.evidence for i in self.items}


def _is_fact(e: EvidenceItem) -> bool:
    return e.rerank_score is None


def _record(e: EvidenceItem) -> RecordKey:
    return (e.case_record_id, e.source_table, e.source_record_id)


def _fields(text: str) -> dict[str, str]:
    return dict(_FIELD_RE.findall(text))


def _conflicts(key: RecordKey, facts: list[EvidenceItem]) -> list[str]:
    values: dict[str, dict[str, None]] = defaultdict(dict)
    for fact in facts:
        for name, value in _fields(fact.text).items():
            values[name][value] = None
    case, table, record = key
    return [
        f"case {case}: {table} {record} has different values for {name}: "
        + ", ".join(vals)
        for name, vals in values.items()
        if len(vals) > 1
    ]


def _dedupe(evidence: list[EvidenceItem]) -> tuple[list[EvidenceItem], list[str]]:
    groups: dict[RecordKey, list[EvidenceItem]] = defaultdict(list)
    for e in evidence:
        groups[_record(e)].append(e)

    kept: list[EvidenceItem] = []
    conflicts: list[str] = []
    for key, group in groups.items():
        facts = list({e.text: e for e in group if _is_fact(e)}.values())
        if len(facts) > 1:
            conflicts += _conflicts(key, facts)
        # A fact line is thin (ids, status); the chunk of the same record holds the
        # narrative (e.g. defendant), so chunks stay and facts just rank first.
        chunks = {e.chunk_id: e for e in group if not _is_fact(e)}
        kept += facts + list(chunks.values())
    return kept, conflicts


def _tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN + 1


def build_context(evidence: list[EvidenceItem], max_tokens: int) -> BuiltContext:
    """Deduped, budgeted, case-grouped context with stable aliases e1, e2, ..."""
    unique, conflicts = _dedupe(evidence)
    # Facts first, then best-reranked chunks, so the budget cuts the weakest evidence.
    ranked = sorted(unique, key=lambda e: (not _is_fact(e), -(e.rerank_score or 0.0)))

    kept: list[EvidenceItem] = []
    used = 0
    for e in ranked:
        cost = _tokens(e.text)
        if used + cost > max_tokens:
            continue
        kept.append(e)
        used += cost

    case_order = {
        c: n for n, c in enumerate(dict.fromkeys(e.case_record_id for e in kept))
    }
    kept.sort(
        key=lambda e: case_order[e.case_record_id]
    )  # stable: keeps rank inside a case
    items = tuple(ContextItem(f"e{n}", e) for n, e in enumerate(kept, 1))
    return BuiltContext(items, tuple(conflicts), len(unique) - len(kept))
