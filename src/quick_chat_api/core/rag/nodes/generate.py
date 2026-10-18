"""Generate node: grounded Claude answer from the built context, with validated citations."""

from __future__ import annotations

from typing import Any, cast

from langchain_core.messages import AnyMessage
from langchain_core.runnables import Runnable
from pydantic import BaseModel, Field

from quick_chat_api.core.llm.generation.factory import get_chat_model
from quick_chat_api.core.llm.prompts import ANSWER_PROMPT_VERSION, ANSWER_V2
from quick_chat_api.core.rag.state import PipelineState, history_window
from quick_chat_api.core.rag.tracing import Node
from quick_chat_api.core.schemas.chat import Citation
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger

INSUFFICIENT_ANSWER = (
    "The available case data does not provide enough information to answer."
)


class Answer(BaseModel):
    answer: str
    citations: list[str] = Field(default_factory=list)
    insufficient_information: bool = False
    conflicts: list[str] = Field(default_factory=list)


def _default_llm() -> Runnable[Any, Answer]:
    structured = get_chat_model("answer").with_structured_output(Answer)
    return cast("Runnable[Any, Answer]", ANSWER_V2 | structured)


def make_generate(llm: Runnable[Any, Answer] | None = None) -> Node:
    """Build the node; `llm` is the prompt|structured-model chain (fake in tests)."""

    async def generate(state: PipelineState) -> dict[str, Any]:
        contexts = state.get("contexts", [])
        if not contexts:
            return {"answer": INSUFFICIENT_ANSWER, "insufficient_information": True}

        known = state.get("context_map", {})
        history: list[AnyMessage] = history_window(
            state.get("messages", []), settings.CHAT_HISTORY_MAX_TURNS
        )
        result = await (llm or _default_llm()).ainvoke(
            {
                "question": state.get("question", ""),
                "history": history,
                "evidence": "\n\n".join([*contexts, *state.get("context_notes", [])]),
            }
        )
        # Citations are rebuilt from our own evidence; unknown ids are dropped.
        cited = list(dict.fromkeys(i for i in result.citations if i in known))
        citations = [
            Citation(
                chunk_id=known[i].chunk_id,
                case_record_id=known[i].case_record_id,
                source_table=known[i].source_table,
                source_record_id=known[i].source_record_id,
                source_type=known[i].source_type or known[i].source_table,
            )
            for i in cited
        ]
        logger.info(
            "rag generate",
            extra={
                "citations": len(citations),
                "dropped_citations": len(result.citations) - len(cited),
                "prompt_version": ANSWER_PROMPT_VERSION,
            },
        )
        conflicts = list(
            dict.fromkeys([*state.get("conflicts", []), *result.conflicts])
        )
        if result.insufficient_information or not citations:
            return {
                "answer": result.answer
                if result.insufficient_information
                else INSUFFICIENT_ANSWER,
                "citations": citations,
                "conflicts": conflicts,
                "insufficient_information": True,
            }
        return {
            "answer": result.answer,
            "citations": citations,
            "conflicts": conflicts,
            "insufficient_information": False,
        }

    return generate
