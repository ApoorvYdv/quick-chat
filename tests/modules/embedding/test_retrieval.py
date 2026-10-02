from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from quick_chat_api.core.vectorstore.base import VectorSearchResult
from quick_chat_api.modules.embedding.retrieval import retrieve


def _chunk(chunk_id, source_type="charge", source_table="case_charge", source_id="1"):
    document = MagicMock()
    document.source_type = source_type
    document.source_table = source_table
    document.source_id = source_id

    chunk = MagicMock()
    chunk.id = chunk_id
    chunk.content = f"content-{chunk_id}"
    chunk.document = document
    chunk.case_record_id = uuid4()
    chunk.document_id = uuid4()
    chunk.chunk_index = 0
    chunk.metadata_ = {}
    return chunk


def _session_with_chunks(chunks: list) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = chunks
    session = AsyncMock()
    session.execute.return_value = result
    return session


def test_retrieve_returns_empty_without_querying_postgres_when_no_hits():
    session = AsyncMock()
    with (
        patch("quick_chat_api.modules.embedding.retrieval.get_embedding_provider") as get_provider,
        patch("quick_chat_api.modules.embedding.retrieval.get_vector_store") as get_store,
    ):
        get_provider.return_value.embed_query.return_value = [0.1]
        get_store.return_value.search.return_value = []

        result = asyncio.run(retrieve(session, "acme", "what happened"))

    assert result == []
    session.execute.assert_not_called()


def test_retrieve_hydrates_and_preserves_qdrant_ranking_order():
    first_id, second_id = uuid4(), uuid4()
    hits = [
        VectorSearchResult(id=first_id, score=0.9, payload={}),
        VectorSearchResult(id=second_id, score=0.5, payload={}),
    ]
    # Postgres returns them out of ranking order; retrieve() must re-sort by hit order.
    session = _session_with_chunks([_chunk(second_id), _chunk(first_id)])

    with (
        patch("quick_chat_api.modules.embedding.retrieval.get_embedding_provider") as get_provider,
        patch("quick_chat_api.modules.embedding.retrieval.get_vector_store") as get_store,
    ):
        get_provider.return_value.embed_query.return_value = [0.1]
        get_store.return_value.search.return_value = hits

        result = asyncio.run(retrieve(session, "acme", "what happened"))

    assert [chunk.id for chunk in result] == [first_id, second_id]
    assert result[0].score == 0.9
    assert result[0].source_type == "charge"


def test_retrieve_drops_hits_missing_from_postgres():
    hit_id = uuid4()
    hits = [VectorSearchResult(id=hit_id, score=0.9, payload={})]
    session = _session_with_chunks([])

    with (
        patch("quick_chat_api.modules.embedding.retrieval.get_embedding_provider") as get_provider,
        patch("quick_chat_api.modules.embedding.retrieval.get_vector_store") as get_store,
    ):
        get_provider.return_value.embed_query.return_value = [0.1]
        get_store.return_value.search.return_value = hits

        result = asyncio.run(retrieve(session, "acme", "what happened"))

    assert result == []
