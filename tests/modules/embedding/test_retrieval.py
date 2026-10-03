from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from quick_chat_api.core.vectorstore.base import VectorPoint
from quick_chat_api.modules.embedding import retrieval
from quick_chat_api.modules.embedding.retrieval import retrieve
from tests.fakes import FakeEmbeddingProvider


def _point(
    case_id: UUID, text: str, embedding: FakeEmbeddingProvider, source_type="charge"
):
    return VectorPoint(
        id=uuid4(),
        vector=embedding.embed_query(text),
        payload={
            "content": text,
            "source_type": source_type,
            "source_table": "case_charge",
            "source_id": text,
            "case_record_id": str(case_id),
            "chunk_index": 0,
            "chunk_metadata": {"k": "v"},
        },
    )


@pytest.fixture(autouse=True)
def _wire(monkeypatch, fake_embedding, fake_vector_store):
    monkeypatch.setattr(retrieval, "get_embedding_provider", lambda: fake_embedding)
    monkeypatch.setattr(retrieval, "get_vector_store", lambda: fake_vector_store)


def test_returns_payload_content_ranked_by_similarity(
    fake_embedding, fake_vector_store
) -> None:
    case_id = uuid4()
    fake_vector_store.upsert_points(
        "acme", [_point(case_id, t, fake_embedding) for t in ("alpha", "beta", "gamma")]
    )

    hits = asyncio.run(retrieve("acme", "beta", top_k=3))

    assert hits[0].content == "beta"
    assert hits[0].case_record_id == case_id
    assert hits[0].metadata == {"k": "v"}
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_empty_when_no_hits() -> None:
    assert asyncio.run(retrieve("acme", "anything")) == []


def test_case_filter_applies_server_side(fake_embedding, fake_vector_store) -> None:
    mine, other = uuid4(), uuid4()
    fake_vector_store.upsert_points(
        "acme",
        [_point(mine, "mine", fake_embedding), _point(other, "other", fake_embedding)],
    )

    hits = asyncio.run(retrieve("acme", "mine", case_record_id=mine))

    assert {h.content for h in hits} == {"mine"}


def test_other_agency_never_sees_hits(fake_embedding, fake_vector_store) -> None:
    fake_vector_store.upsert_points("acme", [_point(uuid4(), "secret", fake_embedding)])

    assert asyncio.run(retrieve("globex", "secret")) == []
