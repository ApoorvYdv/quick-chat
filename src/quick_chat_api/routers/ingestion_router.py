"""HTTP endpoints for triggering AI-knowledge ingestion/reindexing.

Router owns HTTP concerns only -- request/response schemas, status codes,
dependency wiring. No DB queries, embedding, or chunking logic here, per
`.claude/rules/architecture.md`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from quick_chat_api.core.constants.error_response import ErrorResponse
from quick_chat_api.core.controllers import ingestion_controller
from quick_chat_api.core.controllers.ingestion_controller import IngestionController
from quick_chat_api.core.schemas.ingestion import (
    CaseIndexDeleteResponse,
    CaseIngestionResponse,
)
from quick_chat_api.utils.dependencies import get_agency_header

router = APIRouter(
    prefix="/cases/{case_id}/index",
    tags=["ai-knowledge-index"],
    dependencies=[Depends(get_agency_header)],
)


@router.post("/reindex", response_model=CaseIngestionResponse)
async def reindex_case(
    case_id: UUID,
    controller: Annotated[IngestionController, Depends()],
    force: bool = Query(
        False,
        description="Re-embed every entity even if content/model/chunking are unchanged",
    ),
) -> CaseIngestionResponse:
    try:
        result = await controller.reindex_case(case_id, force=force)
    except ingestion_controller.CaseNotFoundControllerError as exc:
        raise HTTPException(status_code=404, detail=ErrorResponse.CASE_NOT_FOUND) from exc
    return CaseIngestionResponse.from_result(result)


@router.delete("", response_model=CaseIndexDeleteResponse)
async def delete_case_index(
    case_id: UUID,
    controller: Annotated[IngestionController, Depends()],
) -> CaseIndexDeleteResponse:
    deleted = await controller.delete_case_index(case_id)
    return CaseIndexDeleteResponse(case_id=case_id, deleted_sources=deleted)
