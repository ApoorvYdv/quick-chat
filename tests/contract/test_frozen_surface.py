"""`data_ingestion/` must keep working without edits.

Pins the `src/` surface those scripts import. If one of these fails, either
restore the contract or consciously update the script and this test together.
"""

import importlib
import inspect

import pytest

from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionResult,
    CaseIngestionService,
    EntityIngestionOutcome,
)

SCRIPTS = [
    "data_ingestion.create_tables",
    "data_ingestion.ingest_data",
    "data_ingestion.backfill_embeddings",
]


@pytest.mark.parametrize("module", SCRIPTS)
def test_scripts_import(module: str) -> None:
    importlib.import_module(module)


def test_ingest_data_models_and_columns_exist() -> None:
    ingest = importlib.import_module("data_ingestion.ingest_data")
    for table in ingest.TABLE_ORDER:
        assert ingest.MODEL_BY_TABLE[table].__tablename__ == table


def test_ingestion_service_signature() -> None:
    assert list(inspect.signature(CaseIngestionService).parameters) == [
        "engine",
        "agency",
    ]
    for method in ("ingest_case", "reindex_case"):
        params = inspect.signature(getattr(CaseIngestionService, method)).parameters
        assert list(params) == ["self", "case_id"]
        assert inspect.iscoroutinefunction(getattr(CaseIngestionService, method))


def test_ingestion_result_surface() -> None:
    result_props = {"embedded", "skipped", "failed", "outcomes"}
    assert result_props <= set(dir(CaseIngestionResult)) | set(
        CaseIngestionResult.__dataclass_fields__
    )
    assert {"source_type", "source_id", "error"} <= set(
        EntityIngestionOutcome.__dataclass_fields__
    )


def test_logger_accepts_extra() -> None:
    from quick_chat_api.utils.common.logger import logger

    logger.error("contract check", extra={"case_id": "x"})


def test_session_context_and_engine_entry_points() -> None:
    from quick_chat_api.core.database.connections import get_async_engine
    from quick_chat_api.core.database.session_context_manager import session_context

    assert callable(get_async_engine)
    assert list(inspect.signature(session_context).parameters) == ["engine", "agency"]
