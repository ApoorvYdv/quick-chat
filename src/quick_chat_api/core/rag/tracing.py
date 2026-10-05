"""`@traced_node`: per-node metadata fanned out to tracing sinks.

Sinks only ever receive ids, counts, status and latency; never case content.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache, wraps
from typing import Any

from langsmith import Client, RunTree

from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger

Node = Callable[[PipelineState], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class NodeEvent:
    node: str
    status: str
    latency_ms: float
    evidence_count: int
    agency: str
    session_id: str
    started_at: datetime


Sink = Callable[[NodeEvent], None]


def _log_sink(event: NodeEvent) -> None:
    logger.info(
        "rag node",
        extra={
            "node": event.node,
            "status": event.status,
            "latency_ms": event.latency_ms,
            "evidence_count": event.evidence_count,
        },
    )


@lru_cache
def _langsmith_client() -> Client:
    key = settings.LANGSMITH_API_KEY
    return Client(api_key=key.get_secret_value() if key else None)


def _langsmith_sink(event: NodeEvent) -> None:
    """Redacted: inputs/outputs are scrubbed to ids and counts."""
    run = RunTree(
        name=event.node,
        run_type="chain",
        project_name=settings.LANGSMITH_PROJECT,
        ls_client=_langsmith_client(),
        inputs={},
        start_time=event.started_at,
        extra={"metadata": {"agency": event.agency, "session_id": event.session_id}},
    )
    run.end(
        outputs={
            "status": event.status,
            "latency_ms": event.latency_ms,
            "evidence_count": event.evidence_count,
        },
        error=None if event.status == "ok" else "node failed",
    )
    run.post()


def _sinks() -> list[Sink]:
    return [_log_sink, *([_langsmith_sink] if settings.LANGSMITH_ENABLED else [])]


def traced_node(name: str) -> Callable[[Node], Node]:
    def decorator(fn: Node) -> Node:
        @wraps(fn)
        async def wrapper(state: PipelineState) -> dict[str, Any]:
            started_at = datetime.now(UTC)
            start = time.perf_counter()
            status = "ok"
            try:
                return await fn(state)
            except Exception:
                status = "error"
                raise
            finally:
                event = NodeEvent(
                    node=name,
                    status=status,
                    latency_ms=round((time.perf_counter() - start) * 1000, 1),
                    evidence_count=len(state.get("evidence", [])),
                    agency=state.get("agency", ""),
                    session_id=str(state.get("session_id", "")),
                    started_at=started_at,
                )
                for sink in _sinks():
                    sink(event)

        return wrapper

    return decorator
