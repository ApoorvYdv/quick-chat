"""Controller for triggering AI-knowledge (re)indexing of a case.

Thin coordination layer between the router (HTTP concerns) and
`CaseIngestionService` (DB/embedding orchestration) -- per
`.claude/rules/architecture.md`, no DB queries or embedding logic live here.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionResult,
    CaseIngestionService,
    CaseNotFoundError,
)
from quick_chat_api.utils.context import RequestContext


class CaseNotFoundControllerError(RuntimeError):
    """Raised when the requested case does not exist in the resolved tenant."""


class IngestionController:
    def __init__(self, engine: Annotated[AsyncEngine, Depends(get_async_engine)]):
        self.engine = engine
        self.agency = RequestContext.agency

    async def reindex_case(
        self,
        case_id: UUID,
        *,
        force: bool,
    ) -> CaseIngestionResult:
        service = CaseIngestionService(self.engine, self.agency)
        try:
            if force:
                return await service.reindex_case(case_id)
            return await service.ingest_case(case_id)
        except CaseNotFoundError as exc:
            raise CaseNotFoundControllerError(str(exc)) from exc

    async def delete_case_index(self, case_id: UUID) -> int:
        service = CaseIngestionService(self.engine, self.agency)
        return await service.delete_case_index(case_id)
