from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from testcontainers.qdrant import QdrantContainer

from quick_chat_api.core.vectorstore.base import VectorFilter, VectorPoint
from quick_chat_api.core.vectorstore.providers.qdrant import QdrantVectorStore

pytestmark = pytest.mark.integration

DIM = 4


@pytest.fixture(scope="module")
def store() -> Iterator[QdrantVectorStore]:
    with QdrantContainer("qdrant/qdrant:v1.19.1") as container:
        yield QdrantVectorStore(
            url=f"http://{container.get_container_host_ip()}:{container.exposed_rest_port}",
            collection_prefix="it",
            vector_size=DIM,
            prefetch_limit=50,
        )


def _point(case_id, text, vector, source_type="charge") -> VectorPoint:
    return VectorPoint(
        id=uuid4(),
        vector=vector,
        text=text,
        payload={
            "case_record_id": str(case_id),
            "source_type": source_type,
            "content": text,
        },
    )


def test_hybrid_query_is_scoped_by_agency_case_and_source_type(store) -> None:
    mine, other = uuid4(), uuid4()
    store.upsert_points(
        "acme",
        [
            _point(mine, "grand theft auto", [1, 0, 0, 0]),
            _point(mine, "probation order", [0, 1, 0, 0], "disposition"),
            _point(other, "grand theft auto", [1, 0, 0, 0]),
        ],
    )
    store.upsert_points("globex", [_point(mine, "grand theft auto", [1, 0, 0, 0])])

    hits = store.search(
        "acme",
        [1, 0, 0, 0],
        "theft",
        VectorFilter(case_record_ids=[mine], source_types=["charge"]),
        top_k=10,
    )

    assert len(hits) == 1
    assert hits[0].payload["case_record_id"] == str(mine)
    assert hits[0].payload["source_type"] == "charge"


def test_sparse_leg_finds_exact_term_the_dense_leg_misses(store) -> None:
    case_id = uuid4()
    store.upsert_points(
        "lexical",
        [
            _point(case_id, "case 24CR000123 filed", [0, 0, 1, 0]),
            _point(case_id, "unrelated narrative", [1, 0, 0, 0]),
        ],
    )

    hits = store.search("lexical", [1, 0, 0, 0], "24CR000123", VectorFilter(), top_k=1)

    assert "24CR000123" in hits[0].payload["content"]
