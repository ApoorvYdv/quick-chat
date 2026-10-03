"""Run the real `data_ingestion` scripts against a throwaway schema."""

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

AGENCY = "contract_scratch"


def _run(module: str, env: dict[str, str]) -> str:
    import os

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", module, "--agency", AGENCY],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_create_tables_then_ingest_is_idempotent(postgres, db_env) -> None:
    _run("data_ingestion.create_tables", db_env)

    first = _run("data_ingestion.ingest_data", db_env)
    assert "case_record: 100 inserted, 0 skipped" in first

    second = _run("data_ingestion.ingest_data", db_env)
    assert "case_record: 0 inserted, 100 skipped" in second

    engine = create_engine(postgres.get_connection_url())
    with engine.connect() as conn:
        count = conn.execute(
            text(f'SELECT count(*) FROM "{AGENCY}".case_record')  # noqa: S608  (test constant)
        ).scalar()
    assert count == 100
