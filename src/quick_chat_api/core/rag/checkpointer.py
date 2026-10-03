"""LangGraph checkpointer bound to one agency schema, on the app's own pool.

A connection is borrowed from the shared SQLAlchemy engine pool (no second
pool), `search_path` is pinned to the agency schema for the duration of the
run, and every connection setting is restored before it goes back to the pool.
`agency` is the already-validated tenant from `RequestContext`, quoted as an
identifier, never interpolated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.ext.asyncio import AsyncEngine

# Tables are created once per agency per process; setup() itself is idempotent.
_ready_agencies: set[str] = set()


@asynccontextmanager
async def agency_checkpointer(
    engine: AsyncEngine, agency: str
) -> AsyncIterator[AsyncPostgresSaver]:
    async with engine.connect() as sa_conn:
        raw = await sa_conn.get_raw_connection()
        conn: psycopg.AsyncConnection = raw.driver_connection  # type: ignore[assignment]
        previous_row_factory = conn.row_factory
        await conn.rollback()
        await conn.set_autocommit(True)
        conn.row_factory = dict_row  # type: ignore[assignment]
        try:
            await conn.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(agency))
            )
            saver = AsyncPostgresSaver(conn)  # type: ignore[arg-type]
            if agency not in _ready_agencies:
                await saver.setup()
                _ready_agencies.add(agency)
            yield saver
        finally:
            try:
                await conn.execute("RESET search_path")
                conn.row_factory = previous_row_factory
                await conn.set_autocommit(False)
            except psycopg.Error:
                # Unknown connection state: drop it rather than pool it.
                await sa_conn.invalidate()
