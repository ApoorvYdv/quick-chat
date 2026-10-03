"""Readiness checks. Failure details are logged, never returned to clients."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.vectorstore.exceptions import VectorStoreError
from quick_chat_api.core.vectorstore.factory import get_vector_store
from quick_chat_api.utils.common.logger import logger


class HealthController:
    def __init__(self, engine: Annotated[AsyncEngine, Depends(get_async_engine)]):
        self.engine = engine

    async def is_ready(self) -> bool:
        postgres_ok = await self._check_postgres()
        vector_store_ok = await self._check_vector_store()
        return postgres_ok and vector_store_ok

    async def _check_postgres(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError) as exc:
            logger.error(
                "readiness: postgres unavailable", extra={"error": type(exc).__name__}
            )
            return False
        return True

    async def _check_vector_store(self) -> bool:
        try:
            await asyncio.to_thread(get_vector_store().ping)
        except VectorStoreError as exc:
            logger.error(
                "readiness: vector store unavailable",
                extra={"error": type(exc).__name__},
            )
            return False
        return True
