"""One-off backfill: run `CaseIngestionService.ingest_case()` over every
`CaseRecord` already loaded by `ingest_data.py`, for one agency schema.

Usage:
    uv run python -m data_ingestion.backfill_embeddings --agency <schema_name>
    uv run python -m data_ingestion.backfill_embeddings --agency <schema_name> --case-id <uuid>
    uv run python -m data_ingestion.backfill_embeddings --agency <schema_name> --force

`--agency` is required rather than assumed: schema names must never be
hardcoded (`CLAUDE.md` §8), and `data_ingestion/create_tables.py`'s own
`AgencyBase.metadata.schema` is `None` at the model level -- the real
schema is only known at the DB/environment level.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from quick_chat_api.core.database.connections import get_async_engine
from quick_chat_api.core.database.session_context_manager import session_context
from quick_chat_api.core.models.agency.agency import CaseRecord
from quick_chat_api.modules.embedding.ingestion_service import CaseIngestionService
from quick_chat_api.utils.common.logger import logger


async def _case_ids(agency: str) -> list[UUID]:
    engine = get_async_engine()
    async with session_context(engine, agency) as session:
        result = await session.execute(select(CaseRecord.id))
        return list(result.scalars().all())


async def _run(agency: str, case_id: UUID | None, force: bool) -> None:
    engine = get_async_engine()
    service = CaseIngestionService(engine, agency)
    case_ids = [case_id] if case_id is not None else await _case_ids(agency)

    if not case_ids:
        print(f"No cases found for agency '{agency}'.")
        return

    for cid in case_ids:
        result = (
            await service.reindex_case(cid) if force else await service.ingest_case(cid)
        )
        print(
            f"case={cid} embedded={result.embedded} "
            f"skipped={result.skipped} failed={result.failed}"
        )
        for outcome in result.outcomes:
            if outcome.error is not None:
                logger.error(
                    "backfill entity failure",
                    extra={
                        "case_id": str(cid),
                        "source_type": outcome.source_type,
                        "source_id": outcome.source_id,
                        "error": outcome.error,
                    },
                )

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agency", required=True, help="Agency schema to backfill")
    parser.add_argument(
        "--case-id", type=UUID, default=None, help="Backfill a single case only"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed every entity, ignoring content_hash/indexing_key skip logic",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.agency, args.case_id, args.force))


if __name__ == "__main__":
    main()
