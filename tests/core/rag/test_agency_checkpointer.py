"""Real Postgres: checkpoints live in the agency schema on the shared pool."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from quick_chat_api.core.rag import checkpointer as cp
from quick_chat_api.core.rag.graph import build_graph
from quick_chat_api.core.rag.state import initial_state
from quick_chat_api.core.schemas.chat import AskRequest

pytestmark = pytest.mark.integration

SESSION = uuid4()


def _turn(question: str) -> dict:
    request = AskRequest(question=question, session_id=SESSION)
    return initial_state(request, "x", None)


async def test_checkpoints_are_isolated_per_agency_schema(postgres, db_env) -> None:
    engine = create_async_engine(
        postgres.get_connection_url(), pool_size=1, max_overflow=0
    )
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ckpt_a"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS ckpt_b"))
    cp._ready_agencies.clear()
    config = {"configurable": {"thread_id": f"x:{SESSION}"}}

    async with cp.agency_checkpointer(engine, "ckpt_a") as saver:
        await build_graph(saver).ainvoke(_turn("only in a"), config)
    async with cp.agency_checkpointer(engine, "ckpt_a") as saver:
        again = await build_graph(saver).ainvoke(_turn("second"), config)
    async with cp.agency_checkpointer(engine, "ckpt_b") as saver:
        other = await build_graph(saver).ainvoke(_turn("in b"), config)

    assert [m.content for m in again["messages"]][::2] == ["only in a", "second"]
    assert [m.content for m in other["messages"]][::2] == ["in b"]

    # pool size 1: the same connection must come back clean.
    async with engine.connect() as conn:
        assert (await conn.execute(text("SHOW search_path"))).scalar() != "ckpt_a"
        tables = await conn.execute(
            text(
                "SELECT table_schema FROM information_schema.tables "
                "WHERE table_name = 'checkpoints' ORDER BY 1"
            )
        )
        assert [r[0] for r in tables] == ["ckpt_a", "ckpt_b"]
    await engine.dispose()
