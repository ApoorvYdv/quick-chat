"""Graph state. Tenant (`agency`) is copied from `RequestContext` only.

Only `messages` and `last_case_ids` are meant to survive between turns.
`evidence`/`contexts` are untracked channels (never checkpointed, so retrieved
case content is not stored at rest) and every other per-turn field is reset by
`initial_state`, since checkpointed channels would otherwise carry over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, TypedDict
from uuid import UUID

from langchain_core.messages import AnyMessage
from langgraph.channels.untracked_value import UntrackedValue
from langgraph.graph.message import add_messages

from quick_chat_api.core.schemas.chat import AskRequest, Citation


@dataclass(frozen=True)
class EvidenceItem:
    agency: str
    case_record_id: UUID
    source_table: str
    source_record_id: str
    chunk_id: UUID
    text: str
    score: float = 0.0
    rerank_score: float | None = None


class PipelineState(TypedDict, total=False):
    question: str
    agency: str
    session_id: UUID
    requested_case_id: UUID | None
    case_number: str | None
    mode: str
    resolved_case_ids: list[UUID]
    needs_clarification: str | None
    evidence: Annotated[list[EvidenceItem], UntrackedValue]
    contexts: Annotated[list[str], UntrackedValue]
    answer: str
    citations: list[Citation]
    conflicts: list[str]
    insufficient_information: bool
    messages: Annotated[list[AnyMessage], add_messages]
    last_case_ids: list[UUID]


def initial_state(
    request: AskRequest, agency: str, case_id: UUID | None
) -> PipelineState:
    return {
        "question": request.question,
        "agency": agency,
        "session_id": request.session_id,
        "requested_case_id": case_id or request.case_id,
        "case_number": request.case_number,
        "mode": request.mode,
        "resolved_case_ids": [],
        "needs_clarification": None,
        "evidence": [],
        "contexts": [],
        "answer": "",
        "citations": [],
        "conflicts": [],
        "insufficient_information": False,
    }


def history_window(messages: list[AnyMessage], max_turns: int) -> list[AnyMessage]:
    """Last `max_turns` question/answer pairs."""
    return messages[-2 * max_turns :] if max_turns else []
