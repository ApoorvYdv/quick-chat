"""Context node: merges agent evidence into the aliased, budgeted context the generator sees."""

from __future__ import annotations

from typing import Any

from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.core.rag.tracing import Node
from quick_chat_api.modules.rag.context_builder import build_context
from quick_chat_api.settings.config import settings


def _notes(state: PipelineState) -> list[str]:
    notes = []
    for name, out in state.get("agent_outputs", {}).items():
        matches = getattr(out, "matches", None)
        if matches and matches.total:
            truncated = "; the list is truncated" if matches.truncated else ""
            notes.append(
                f"{name} agent: {matches.total} matching cases in total, "
                f"{len(matches.cases)} shown{truncated}."
            )
    if missing := state.get("insufficient_domains"):
        notes.append(f"No relevant data was found for: {', '.join(missing)}.")
    return notes


def make_build_context() -> Node:
    async def build(state: PipelineState) -> dict[str, Any]:
        built = build_context(state.get("evidence", []), settings.CONTEXT_MAX_TOKENS)
        return {
            "contexts": built.texts,
            "context_map": built.by_alias,
            "context_notes": _notes(state),
            "conflicts": list(built.conflicts),
        }

    return build
