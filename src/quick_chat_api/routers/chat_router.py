"""HTTP endpoints for asking questions (JSON and SSE)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from quick_chat_api.core.controllers.chat_controller import ChatController
from quick_chat_api.core.rag.streaming import sse_stream
from quick_chat_api.core.schemas.chat import AskRequest, AskResponse
from quick_chat_api.utils.dependencies import get_agency_header

router = APIRouter(tags=["chat"], dependencies=[Depends(get_agency_header)])

ChatDep = Annotated[ChatController, Depends()]


def _sse(controller: ChatController, request: AskRequest, case_id: UUID | None):
    return StreamingResponse(
        sse_stream(controller.stream(request, case_id)),
        media_type="text/event-stream",
    )


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest, controller: ChatDep) -> AskResponse:
    return await controller.ask(request)


@router.post("/ask/stream")
async def ask_stream(request: AskRequest, controller: ChatDep):
    return _sse(controller, request, None)


@router.post("/cases/{case_id}/ask", response_model=AskResponse)
async def ask_case(
    case_id: UUID, request: AskRequest, controller: ChatDep
) -> AskResponse:
    return await controller.ask(request, case_id)


@router.post("/cases/{case_id}/ask/stream")
async def ask_case_stream(case_id: UUID, request: AskRequest, controller: ChatDep):
    return _sse(controller, request, case_id)
