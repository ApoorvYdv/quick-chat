import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from quick_chat_api.core.vectorstore.base import VectorFilter
from quick_chat_api.modules.embedding import ingestion_service as svc
from quick_chat_api.modules.embedding.chunking.base import Chunk
from quick_chat_api.modules.embedding.chunking.exceptions import ChunkingError
from quick_chat_api.modules.embedding.db_adapters import DiscoveredEntity
from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionService,
    IngestionOutcomeKind,
)
from quick_chat_api.modules.embedding.projectors.base import ProjectedDocument
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore

AGENCY = "test_agency"


class _FakeSessionCtx:
    async def __aenter__(self):
        return AsyncMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _entity(
    case_id: UUID, source_id: str, content: str = "Case Number: CR-1"
) -> DiscoveredEntity:
    return DiscoveredEntity(
        source_type="case",
        source_table="case_record",
        source_id=source_id,
        case_record_id=case_id,
        document=ProjectedDocument(
            content=content, title="Case", metadata={"case_id": source_id}
        ),
    )


def _chunker(chunks_per_entity: int = 1) -> MagicMock:
    chunker = MagicMock()
    chunker.chunk.side_effect = lambda content, metadata, provider: [
        Chunk(content=f"{content}#{i}", index=i, token_count=3, metadata={"i": i})
        for i in range(chunks_per_entity)
    ]
    return chunker


@pytest.fixture
def pipeline(
    monkeypatch,
    fake_embedding: FakeEmbeddingProvider,
    fake_vector_store: FakeVectorStore,
):
    state = {"discovered": [], "chunker": _chunker()}
    adapter = MagicMock()
    adapter.discover_all = AsyncMock(side_effect=lambda _: state["discovered"])

    monkeypatch.setattr(svc, "session_context", lambda *a, **k: _FakeSessionCtx())
    monkeypatch.setattr(
        svc, "CaseKnowledgeSourceAdapter", MagicMock(return_value=adapter)
    )
    monkeypatch.setattr(svc, "get_vector_store", lambda: fake_vector_store)
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: fake_embedding)
    monkeypatch.setattr(svc, "get_chunker", lambda: state["chunker"])
    return state


def _service() -> CaseIngestionService:
    return CaseIngestionService(engine=MagicMock(), agency=AGENCY)


class TestIngestCase:
    def test_embeds_new_entity_into_vector_store(
        self, pipeline, fake_vector_store: FakeVectorStore
    ) -> None:
        case_id = uuid4()
        pipeline["discovered"] = [_entity(case_id, "1")]

        result = asyncio.run(_service().ingest_case(case_id))

        assert (result.embedded, result.skipped, result.failed) == (1, 0, 0)
        (point,) = fake_vector_store.collections[AGENCY].values()
        assert point.payload["content"] == "Case Number: CR-1#0"
        assert point.payload["case_record_id"] == str(case_id)
        assert point.payload["chunk_count"] == 1

    def test_skips_unchanged_entity(self, pipeline) -> None:
        case_id = uuid4()
        pipeline["discovered"] = [_entity(case_id, "1")]
        asyncio.run(_service().ingest_case(case_id))
        pipeline["chunker"].chunk.reset_mock()

        result = asyncio.run(_service().ingest_case(case_id))

        assert (result.embedded, result.skipped) == (0, 1)
        pipeline["chunker"].chunk.assert_not_called()

    def test_reembeds_when_content_changes(self, pipeline) -> None:
        case_id = uuid4()
        pipeline["discovered"] = [_entity(case_id, "1")]
        asyncio.run(_service().ingest_case(case_id))
        pipeline["discovered"] = [_entity(case_id, "1", content="Case Number: CR-2")]

        result = asyncio.run(_service().ingest_case(case_id))

        assert result.embedded == 1

    def test_retries_entity_with_missing_chunks(
        self, pipeline, fake_vector_store: FakeVectorStore
    ) -> None:
        case_id = uuid4()
        pipeline["chunker"] = _chunker(chunks_per_entity=2)
        pipeline["discovered"] = [_entity(case_id, "1")]
        asyncio.run(_service().ingest_case(case_id))
        # Simulate a crash that lost one chunk after the hash was written.
        points = fake_vector_store.collections[AGENCY]
        del points[next(iter(points))]

        result = asyncio.run(_service().ingest_case(case_id))

        assert result.embedded == 1
        assert len(points) == 2

    def test_force_reembeds_unchanged_entity(self, pipeline) -> None:
        case_id = uuid4()
        pipeline["discovered"] = [_entity(case_id, "1")]
        asyncio.run(_service().ingest_case(case_id))

        result = asyncio.run(_service().reindex_case(case_id))

        assert (result.embedded, result.skipped) == (1, 0)

    def test_shrinking_split_deletes_stale_trailing_chunks(
        self, pipeline, fake_vector_store: FakeVectorStore
    ) -> None:
        case_id = uuid4()
        pipeline["chunker"] = _chunker(chunks_per_entity=3)
        pipeline["discovered"] = [_entity(case_id, "1")]
        asyncio.run(_service().ingest_case(case_id))
        pipeline["chunker"] = _chunker(chunks_per_entity=1)

        asyncio.run(_service().reindex_case(case_id))

        assert len(fake_vector_store.collections[AGENCY]) == 1

    def test_one_entity_failing_does_not_abort_the_rest(self, pipeline) -> None:
        case_id = uuid4()
        good = _entity(case_id, "1")
        bad = _entity(case_id, "2", content="Case Number: CR-2")
        pipeline["discovered"] = [good, bad]
        real = pipeline["chunker"].chunk.side_effect

        def chunk(content, metadata, provider):
            if content == bad.document.content:
                raise ChunkingError("cannot chunk")
            return real(content, metadata, provider)

        pipeline["chunker"].chunk.side_effect = chunk

        result = asyncio.run(_service().ingest_case(case_id))

        assert (result.embedded, result.failed) == (1, 1)
        failed = next(
            o for o in result.outcomes if o.kind is IngestionOutcomeKind.FAILED
        )
        assert failed.error == "cannot chunk"
        assert "CR-2" not in failed.error

    def test_vector_store_write_failure_is_reported_not_raised(
        self, pipeline, fake_vector_store: FakeVectorStore, monkeypatch
    ) -> None:
        from quick_chat_api.core.vectorstore.exceptions import VectorStoreOperationError

        case_id = uuid4()
        pipeline["discovered"] = [_entity(case_id, "1")]
        monkeypatch.setattr(
            fake_vector_store,
            "upsert_points",
            MagicMock(side_effect=VectorStoreOperationError("down")),
        )

        result = asyncio.run(_service().ingest_case(case_id))

        assert (result.embedded, result.failed) == (0, 1)


class TestDeleteCaseIndex:
    def test_deletes_only_this_cases_points_and_counts_entities(
        self, pipeline, fake_vector_store: FakeVectorStore
    ) -> None:
        case_a, case_b = uuid4(), uuid4()
        pipeline["discovered"] = [_entity(case_a, "1"), _entity(case_a, "2")]
        asyncio.run(_service().ingest_case(case_a))
        pipeline["discovered"] = [_entity(case_b, "3")]
        asyncio.run(_service().ingest_case(case_b))

        deleted = asyncio.run(_service().delete_case_index(case_a))

        assert deleted == 2
        remaining = fake_vector_store.list_points(
            AGENCY, VectorFilter(case_record_id=case_b)
        )
        assert len(remaining) == 1
        assert not fake_vector_store.list_points(
            AGENCY, VectorFilter(case_record_id=case_a)
        )
