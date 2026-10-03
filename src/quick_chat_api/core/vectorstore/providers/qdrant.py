"""Qdrant-backed vector store, collection-per-agency.

One Qdrant collection per agency (`<QDRANT_COLLECTION_PREFIX>__<agency>`),
not a single shared collection with a payload filter -- physical isolation
at the storage/index level is worth the operational overhead here given the
expected number of agencies is high enough that a payload filter's shared
HNSW graph would still work, but per-tenant collections make delete/backup/
resize operations trivial and rule out a forgotten-filter cross-tenant leak
by construction. Every point's own metadata (case, source, status, ...) is
still filtered server-side via payload conditions within that collection
(`.claude/rules/rag.md` -- never a global unfiltered search followed by a
Python-side filter).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

from quick_chat_api.core.vectorstore.base import (
    StoredPoint,
    VectorFilter,
    VectorPoint,
    VectorSearchResult,
    VectorStore,
)
from quick_chat_api.core.vectorstore.exceptions import VectorStoreOperationError
from quick_chat_api.core.vectorstore.registry import register_store
from quick_chat_api.settings.config import Settings

logger = logging.getLogger(__name__)

# Payload fields (everything except tenant, which is the collection itself)
# that must support server-side filtering.
_INDEXED_PAYLOAD_FIELDS = (
    "case_record_id",
    "source_type",
    "source_table",
    "source_id",
    "chunk_index",
    "embedding_model",
    "embedding_version",
    "chunking_strategy",
    "chunking_version",
)

_SCROLL_PAGE_SIZE = 256

_NON_COLLECTION_CHARS = re.compile(r"[^a-z0-9_-]+")


class QdrantVectorStore(VectorStore):
    """`VectorStore` implementation backed by one Qdrant collection per agency."""

    def __init__(
        self,
        url: str,
        collection_prefix: str,
        vector_size: int,
        api_key: str | None = None,
    ) -> None:
        # Imported lazily so importing this module never pulls in the
        # qdrant_client SDK unless this provider is actually selected.
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as qmodels

        self._models = qmodels
        self._collection_prefix = collection_prefix
        self._vector_size = vector_size
        self._client = QdrantClient(url=url, api_key=api_key)
        self._ensured_collections: set[str] = set()

    def _collection_name(self, agency: str) -> str:
        safe_agency = _NON_COLLECTION_CHARS.sub("_", agency.lower()).strip("_")
        return f"{self._collection_prefix}__{safe_agency}"

    def _ensure_collection(self, collection: str) -> None:
        if collection in self._ensured_collections:
            return
        qmodels = self._models
        if not self._client.collection_exists(collection):
            logger.info(
                "creating qdrant collection",
                extra={"collection": collection, "vector_size": self._vector_size},
            )
            self._client.create_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(
                    size=self._vector_size, distance=qmodels.Distance.COSINE
                ),
            )
            for field_name in _INDEXED_PAYLOAD_FIELDS:
                self._client.create_payload_index(
                    collection_name=collection,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
        self._ensured_collections.add(collection)

    def _resolve_collection(self, agency: str) -> str:
        collection = self._collection_name(agency)
        self._ensure_collection(collection)
        return collection

    def _build_filter(self, filter_: VectorFilter) -> Any:
        qmodels = self._models
        must: list[Any] = []
        if filter_.case_record_id is not None:
            must.append(
                qmodels.FieldCondition(
                    key="case_record_id",
                    match=qmodels.MatchValue(value=str(filter_.case_record_id)),
                )
            )
        if filter_.source_types:
            must.append(
                qmodels.FieldCondition(
                    key="source_type", match=qmodels.MatchAny(any=filter_.source_types)
                )
            )
        return qmodels.Filter(must=must)

    def ping(self) -> None:
        try:
            self._client.get_collections()
        except Exception as exc:
            raise VectorStoreOperationError(f"Qdrant ping failed: {exc}") from exc

    def upsert_points(self, agency: str, points: list[VectorPoint]) -> None:
        if not points:
            return
        collection = self._resolve_collection(agency)
        qmodels = self._models
        try:
            self._client.upsert(
                collection_name=collection,
                points=[
                    qmodels.PointStruct(
                        id=str(point.id), vector=point.vector, payload=point.payload
                    )
                    for point in points
                ],
            )
        except Exception as exc:
            raise VectorStoreOperationError(f"Qdrant upsert failed: {exc}") from exc

    def delete_points(self, agency: str, ids: list[UUID]) -> None:
        if not ids:
            return
        collection = self._resolve_collection(agency)
        try:
            self._client.delete(
                collection_name=collection,
                points_selector=[str(id_) for id_ in ids],
            )
        except Exception as exc:
            raise VectorStoreOperationError(f"Qdrant delete failed: {exc}") from exc

    def delete_by_filter(self, agency: str, filter_: VectorFilter) -> None:
        collection = self._resolve_collection(agency)
        qmodels = self._models
        try:
            self._client.delete(
                collection_name=collection,
                points_selector=qmodels.FilterSelector(
                    filter=self._build_filter(filter_)
                ),
            )
        except Exception as exc:
            raise VectorStoreOperationError(
                f"Qdrant filtered delete failed: {exc}"
            ) from exc

    def list_points(self, agency: str, filter_: VectorFilter) -> list[StoredPoint]:
        collection = self._resolve_collection(agency)
        points: list[StoredPoint] = []
        offset = None
        try:
            while True:
                records, offset = self._client.scroll(
                    collection_name=collection,
                    scroll_filter=self._build_filter(filter_),
                    limit=_SCROLL_PAGE_SIZE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                points.extend(
                    StoredPoint(id=UUID(str(r.id)), payload=r.payload or {})
                    for r in records
                )
                if offset is None:
                    return points
        except Exception as exc:
            raise VectorStoreOperationError(f"Qdrant scroll failed: {exc}") from exc

    def search(
        self,
        agency: str,
        query_vector: list[float],
        filter_: VectorFilter,
        top_k: int,
    ) -> list[VectorSearchResult]:
        collection = self._resolve_collection(agency)
        try:
            hits = self._client.query_points(
                collection_name=collection,
                query=query_vector,
                query_filter=self._build_filter(filter_),
                limit=top_k,
                with_payload=True,
            ).points
        except Exception as exc:
            raise VectorStoreOperationError(f"Qdrant search failed: {exc}") from exc
        return [
            VectorSearchResult(
                id=UUID(str(hit.id)), score=hit.score, payload=hit.payload or {}
            )
            for hit in hits
        ]


@register_store("qdrant")
def _build_qdrant_store(config: Settings) -> QdrantVectorStore:
    return QdrantVectorStore(
        url=config.QDRANT_URL,
        collection_prefix=config.QDRANT_COLLECTION_PREFIX,
        vector_size=config.EMBEDDING_DIM,
        api_key=config.QDRANT_API_KEY,
    )
