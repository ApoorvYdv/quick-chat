from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

from tests.fakes import FakeEmbeddingProvider, FakeVectorStore

if TYPE_CHECKING:
    from testcontainers.community.postgres import PostgresContainer

# Same image as docker-compose: PG18 (uuidv7()) + pg_trgm.
POSTGRES_IMAGE = "timescale/timescaledb-ha:pg18-oss"


@pytest.fixture
def fake_embedding() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresContainer]:
    """Throwaway Postgres for `@pytest.mark.integration` tests (needs Docker)."""
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="psycopg") as container:
        yield container


@pytest.fixture(scope="session")
def db_env(postgres: PostgresContainer) -> dict[str, str]:
    """Environment that points the app's Settings at the container only."""
    return {
        "DB_HOST": postgres.get_container_host_ip(),
        "DB_PORT": str(postgres.get_exposed_port(5432)),
        "DB_USERNAME": postgres.username,
        "DB_PASSWORD": postgres.password,
        "DB_NAME": postgres.dbname,
        "AWS_S3_BUCKET": "test-bucket",
    }
