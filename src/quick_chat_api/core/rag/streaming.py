"""SSE wire format; the single place to swap for `sse-starlette` later."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any


def encode_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def sse_stream(
    events: AsyncIterator[tuple[str, dict[str, Any]]],
) -> AsyncIterator[str]:
    try:
        async for event, data in events:
            yield encode_sse(event, data)
    except Exception as exc:
        from quick_chat_api.utils.common.logger import logger

        logger.error("stream failed", extra={"error": type(exc).__name__})
        yield encode_sse("error", {"detail": "Internal server error."})
