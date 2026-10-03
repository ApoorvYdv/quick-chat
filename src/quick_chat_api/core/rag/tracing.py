"""`@traced_node`: per-node metadata logging. Never logs case content."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from quick_chat_api.core.rag.state import PipelineState
from quick_chat_api.utils.common.logger import logger

Node = Callable[[PipelineState], Awaitable[dict[str, Any]]]


def traced_node(name: str) -> Callable[[Node], Node]:
    def decorator(fn: Node) -> Node:
        @wraps(fn)
        async def wrapper(state: PipelineState) -> dict[str, Any]:
            start = time.perf_counter()
            status = "ok"
            try:
                return await fn(state)
            except Exception:
                status = "error"
                raise
            finally:
                logger.info(
                    "rag node",
                    extra={
                        "node": name,
                        "status": status,
                        "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                        "evidence_count": len(state.get("evidence", [])),
                    },
                )

        return wrapper

    return decorator
