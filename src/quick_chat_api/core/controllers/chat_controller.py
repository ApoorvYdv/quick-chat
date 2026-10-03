"""Coordinates a chat request: reads tenant from `RequestContext`, runs the graph."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette_context import context, plugins

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.rag.pipeline import run_pipeline, stream_pipeline
from quick_chat_api.core.schemas.chat import AskRequest, AskResponse
from quick_chat_api.utils.context import RequestContext


class ChatController:
    def __init__(
        self, engine: Annotated[AsyncEngine, Depends(get_async_engine)]
    ) -> None:
        self.engine = engine
        self.agency = RequestContext.agency
        request_id = (
            context.get(plugins.RequestIdPlugin.key) if context.exists() else None
        )
        self.trace_id = str(request_id or uuid4())

    async def ask(
        self, request: AskRequest, case_id: UUID | None = None
    ) -> AskResponse:
        result = await run_pipeline(
            self.engine, request, self.agency, self.trace_id, case_id
        )
        return result.response

    def stream(
        self, request: AskRequest, case_id: UUID | None = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        return stream_pipeline(
            self.engine, request, self.agency, self.trace_id, case_id
        )
