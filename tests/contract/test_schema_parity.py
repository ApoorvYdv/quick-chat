"""`metadata.create_all` and the Alembic migrations must yield the same schema."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from quick_chat_api.core.models.agency.agency import AgencyBase

pytestmark = pytest.mark.integration

MIGRATIONS = Path(__file__).parents[2] / "src/quick_chat_api/migrations"
ALEMBIC_AGENCY = "parity_alembic"
MODELS_AGENCY = "parity_models"


def _alembic(kind: str, env: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(MIGRATIONS / kind / "alembic.ini"),
            "upgrade",
            "head",
        ],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr


def _shape(conn, schema: str) -> dict:
    insp = inspect(conn)
    return {
        table: {
            "columns": {
                c["name"]: (str(c["type"]), c["nullable"])
                for c in insp.get_columns(table, schema=schema)
            },
            "indexes": {
                (tuple(i["column_names"]), i["unique"])
                for i in insp.get_indexes(table, schema=schema)
            },
        }
        for table in insp.get_table_names(schema=schema)
        if table != "alembic_version"
    }


def test_create_all_matches_alembic(postgres, db_env) -> None:
    _alembic("config", db_env)

    engine = create_engine(postgres.get_connection_url())
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO config.agencies (name, abbr, app_name, code, is_active,"
                " created_on, modified_on) VALUES (:n, 'pa', 'pa', 'pa', true,"
                " now(), now())"
            ),
            {"n": ALEMBIC_AGENCY},
        )
    _alembic("agency", db_env)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {MODELS_AGENCY}"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        scoped = conn.execution_options(schema_translate_map={None: MODELS_AGENCY})
        AgencyBase.metadata.create_all(scoped)

        assert _shape(conn, MODELS_AGENCY) == _shape(conn, ALEMBIC_AGENCY)
