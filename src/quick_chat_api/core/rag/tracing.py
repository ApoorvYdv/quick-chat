"""`@traced_node`: per-node metadata fanned out to tracing sinks.

Sinks only ever receive ids, counts, status and latency; never case content,
unless LANGSMITH_LOG_CONTENT is explicitly enabled (synthetic data only).
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache, wraps
from typing import Any, Literal, TypeVar
from uuid import UUID

from langsmith import Client, trace, traceable, tracing_context
from langsmith.run_helpers import get_current_run_tree

from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.settings.config import settings
from quick_chat_api.utils.common.logger import logger

Node = Callable[[PipelineState], Awaitable[dict[str, Any]]]
F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


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
def langsmith_client() -> Client:
    """Client that blanks every run's inputs/outputs, whoever created the run.

    Also covers LangChain/LangGraph's own auto-created runs; counts and ids
    travel only as run metadata.
    """
    key = settings.LANGSMITH_API_KEY
    return Client(
        api_key=key.get_secret_value() if key else None,
        hide_inputs=_redactor(),
        hide_outputs=_redactor(),
    )


def _blank(_: Any) -> dict[str, Any]:
    return {}


def _redactor() -> Callable[[Any], dict[str, Any]] | None:
    """Blanker by default; None (record content) only when LANGSMITH_LOG_CONTENT is on."""
    return None if settings.LANGSMITH_LOG_CONTENT else _blank


def annotate(**metadata: Any) -> None:
    """Attach ids/counts/scores to the current LangSmith run (no-op when off)."""
    if run := get_current_run_tree():
        run.add_metadata(metadata)


def _run_sink(event: NodeEvent) -> None:
    annotate(
        agency=event.agency,
        session_id=event.session_id,
        status=event.status,
        latency_ms=event.latency_ms,
        evidence_count=event.evidence_count,
    )


@asynccontextmanager
async def request_run(
    agency: str, session_id: UUID, trace_id: str
) -> AsyncIterator[None]:
    """Parent run every step nests under; a no-op unless LANGSMITH_ENABLED."""
    client = langsmith_client()
    with tracing_context(
        enabled=settings.LANGSMITH_ENABLED,
        client=client,
        project_name=settings.LANGSMITH_PROJECT,
    ):
        async with trace(
            name="request",
            run_type="chain",
            inputs={},
            metadata={
                "agency": agency,
                "session_id": str(session_id),
                "trace_id": trace_id,
            },
            client=client,
            project_name=settings.LANGSMITH_PROJECT,
        ):
            yield


def span(
    name: str, run_type: Literal["tool", "chain", "retriever"] = "tool"
) -> Callable[[F], F]:
    """Child run + structlog event for a step inside a node (tool, retrieval, rerank)."""

    def decorator(fn: F) -> F:
        @traceable(
            name=name,
            run_type=run_type,
            process_inputs=_redactor(),
            process_outputs=_redactor(),
        )
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            status = "ok"
            try:
                return await fn(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                latency = round((time.perf_counter() - start) * 1000, 1)
                annotate(status=status, latency_ms=latency)
                logger.info(
                    "rag span",
                    extra={"span": name, "status": status, "latency_ms": latency},
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def _sinks() -> list[Sink]:
    return [_log_sink, _run_sink]


def traced_node(name: str) -> Callable[[Node], Node]:
    def decorator(fn: Node) -> Node:
        @traceable(
            name=name,
            run_type="chain",
            process_inputs=_redactor(),
            process_outputs=_redactor(),
        )
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
