import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from data_ingestion.db import engine
from data_ingestion.models import AgencyBase

SCHEMA_NAME = AgencyBase.metadata.schema


async def create_schema(conn: AsyncConnection) -> None:
    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA_NAME}"'))
    # Required for the GIN trigram indexes on party_detail (name search).
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))


async def create_all() -> None:
    async with engine.begin() as conn:
        await create_schema(conn)
        await conn.run_sync(AgencyBase.metadata.create_all)


async def main() -> None:
    await create_all()
    await engine.dispose()
    print(f'Created schema "{SCHEMA_NAME}" and all tables on TigerCloud.')


if __name__ == "__main__":
    asyncio.run(main())
