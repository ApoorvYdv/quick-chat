"""Create the agency schema and all agency tables for one tenant.

Usage:
    uv run python -m data_ingestion.create_tables --agency <schema_name>

`--agency` is required rather than assumed: schema names must never be
hardcoded (`CLAUDE.md` §8), and `AgencyBase.metadata.schema` is `None` at
the model level -- the real schema is only known at the DB/environment
level (see `data_ingestion/backfill_embeddings.py`).
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.models.agency.agency import AgencyBase


async def create_schema(conn: AsyncConnection, agency: str) -> None:
    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{agency}"'))
    # Required for the GIN trigram indexes on party_detail (name search).
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))


async def create_all(agency: str) -> None:
    engine = get_async_engine()
    option_engine = engine.execution_options(schema_translate_map={None: agency})
    async with option_engine.begin() as conn:
        await create_schema(conn, agency)
        await conn.run_sync(AgencyBase.metadata.create_all)


async def main(agency: str) -> None:
    await create_all(agency)
    await get_async_engine().dispose()
    print(f'Created schema "{agency}" and all tables on TigerCloud.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agency", required=True, help="Agency schema to create")
    args = parser.parse_args()
    asyncio.run(main(args.agency))
