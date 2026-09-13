import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.sql.dml import Insert

from quick_chat_api.core.constants.constants import AIKnowledgeStatus
from quick_chat_api.modules.embedding import ingestion_service as svc
from quick_chat_api.modules.embedding.chunking.base import Chunk
from quick_chat_api.modules.embedding.chunking.exceptions import ChunkingError
from quick_chat_api.modules.embedding.db_adapters import DiscoveredEntity
from quick_chat_api.modules.embedding.ingestion_service import (
    CaseIngestionService,
    IngestionOutcomeKind,
)
from quick_chat_api.modules.embedding.projectors.base import ProjectedDocument


class _FakeNested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _existing_row(entity: DiscoveredEntity, content_hash: str, indexing_key: str):
    row = MagicMock()
    row.source_table = entity.source_table
    row.source_id = entity.source_id
    row.source_type = entity.source_type
    row.content_hash = content_hash
    row.source_metadata = {"indexing_key": indexing_key}
    row.status = AIKnowledgeStatus.COMPLETED.value
    return row


def _read_session(existing_rows: list) -> AsyncMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = existing_rows
    session = AsyncMock()
    session.execute.return_value = result
    return session


def _write_session() -> AsyncMock:
    session = AsyncMock()

    async def _execute(stmt, *a, **kw):
        result = MagicMock()
        if isinstance(stmt, Insert):
            result.scalar_one.return_value = uuid4()
        return result

    session.execute = AsyncMock(side_effect=_execute)
    session.add_all = MagicMock()
    session.begin_nested = MagicMock(return_value=_FakeNested())
    session.commit = AsyncMock()
    return session


def _entity(case_id: UUID, source_id: str, content: str = "Case Number: CR-1") -> DiscoveredEntity:
    return DiscoveredEntity(
        source_type="case",
        source_table="case_record",
        source_id=source_id,
        case_record_id=case_id,
        document=ProjectedDocument(content=content, title="Case", metadata={"case_id": source_id}),
    )


def _patch_pipeline(monkeypatch, discovered, existing_rows, read_session=None, write_session=None):
    read_session = read_session or _read_session(existing_rows)
    write_session = write_session or _write_session()
    contexts = iter([read_session, write_session])

    def fake_session_context(engine, agency=None):
        return _FakeSessionCtx(next(contexts))

    fake_adapter = MagicMock()
    fake_adapter.discover_all = AsyncMock(return_value=discovered)

    monkeypatch.setattr(svc, "session_context", fake_session_context)
    monkeypatch.setattr(svc, "CaseKnowledgeSourceAdapter", MagicMock(return_value=fake_adapter))

    provider = MagicMock()
    provider.embed_documents.side_effect = lambda texts: [[0.1, 0.2] for _ in texts]
    monkeypatch.setattr(svc, "get_embedding_provider", MagicMock(return_value=provider))

    chunker = MagicMock()
    chunker.chunk.side_effect = lambda content, metadata, provider: [
        Chunk(content=content, index=0, token_count=3, metadata={"total_chunks": 1})
    ]
    monkeypatch.setattr(svc, "get_chunker", MagicMock(return_value=chunker))

    return chunker, provider, write_session


class TestIngestCase:
    def test_skips_unchanged_entity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        case_id = uuid4()
        entity = _entity(case_id, "1")
        content_hash = svc._content_hash(entity.document.content)
        indexing_key = "|".join(
            [
                svc.settings.EMBEDDING_PROVIDER,
                svc.settings.EMBEDDING_MODEL,
                svc.settings.EMBEDDING_VERSION,
                svc.settings.CHUNKING_STRATEGY,
                svc.settings.CHUNKING_VERSION,
            ]
        )
        existing = [_existing_row(entity, content_hash, indexing_key)]
        chunker, provider, _ = _patch_pipeline(monkeypatch, [entity], existing)

        service = CaseIngestionService(engine=MagicMock(), agency="test_agency")
        result = asyncio.run(service.ingest_case(case_id))

        assert result.skipped == 1
        assert result.embedded == 0
        assert result.failed == 0
        chunker.chunk.assert_not_called()
        provider.embed_documents.assert_not_called()

    def test_embeds_new_entity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        case_id = uuid4()
        entity = _entity(case_id, "1")
        chunker, provider, write_session = _patch_pipeline(monkeypatch, [entity], [])

        service = CaseIngestionService(engine=MagicMock(), agency="test_agency")
        result = asyncio.run(service.ingest_case(case_id))

        assert result.embedded == 1
        assert result.skipped == 0
        assert result.failed == 0
        chunker.chunk.assert_called_once()
        provider.embed_documents.assert_called_once()
        write_session.commit.assert_awaited_once()

    def test_force_reembeds_unchanged_entity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        case_id = uuid4()
        entity = _entity(case_id, "1")
        content_hash = svc._content_hash(entity.document.content)
        indexing_key = "|".join(
            [
                svc.settings.EMBEDDING_PROVIDER,
                svc.settings.EMBEDDING_MODEL,
                svc.settings.EMBEDDING_VERSION,
                svc.settings.CHUNKING_STRATEGY,
                svc.settings.CHUNKING_VERSION,
            ]
        )
        existing = [_existing_row(entity, content_hash, indexing_key)]
        chunker, provider, _ = _patch_pipeline(monkeypatch, [entity], existing)

        service = CaseIngestionService(engine=MagicMock(), agency="test_agency")
        result = asyncio.run(service.reindex_case(case_id))

        assert result.embedded == 1
        assert result.skipped == 0
        chunker.chunk.assert_called_once()

    def test_isolates_chunking_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        case_id = uuid4()
        good = _entity(case_id, "1", content="Case Number: CR-1")
        bad = _entity(case_id, "2", content="Case Number: CR-2")

        chunker, provider, write_session = _patch_pipeline(monkeypatch, [good, bad], [])

        def chunk_side_effect(content, metadata, prov):
            if "CR-2" in content:
                raise ChunkingError("boom")
            return [Chunk(content=content, index=0, token_count=3, metadata={"total_chunks": 1})]

        chunker.chunk.side_effect = chunk_side_effect

        service = CaseIngestionService(engine=MagicMock(), agency="test_agency")
        result = asyncio.run(service.ingest_case(case_id))

        assert result.embedded == 1
        assert result.failed == 1
        failed_outcome = next(
            o for o in result.outcomes if o.kind is IngestionOutcomeKind.FAILED
        )
        assert failed_outcome.source_id == "2"
        assert "boom" in failed_outcome.error
        write_session.commit.assert_awaited_once()


class TestDeleteCaseIndex:
    def test_soft_deletes_all_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        case_id = uuid4()
        source = MagicMock()
        source.chunks = MagicMock()

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [source]
        session = AsyncMock()
        session.execute.return_value = result_mock
        session.commit = AsyncMock()

        monkeypatch.setattr(
            svc, "session_context", lambda engine, agency=None: _FakeSessionCtx(session)
        )

        service = CaseIngestionService(engine=MagicMock(), agency="test_agency")
        deleted = asyncio.run(service.delete_case_index(case_id))

        assert deleted == 1
        assert source.status == AIKnowledgeStatus.DELETED.value
        assert source.is_active is False
        source.chunks.clear.assert_called_once()
        session.commit.assert_awaited_once()
