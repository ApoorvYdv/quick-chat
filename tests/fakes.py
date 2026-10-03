"""Deterministic in-memory fakes for the external services the app depends on."""

from __future__ import annotations

import hashlib
import math
from uuid import UUID

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.vectorstore.base import (
    StoredPoint,
    VectorFilter,
    VectorPoint,
    VectorSearchResult,
    VectorStore,
)


class FakeEmbeddingProvider(EmbeddingProvider):
    """Hash-based embeddings: equal text -> equal vector, no model download."""

    def __init__(self, dimension: int = 8) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_tokens(self) -> int:
        return 512

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        raw = [digest[i % len(digest)] / 255 for i in range(self._dimension)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


class FakeVectorStore(VectorStore):
    """Collection-per-agency store held in dicts; cosine similarity on read."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[UUID, VectorPoint]] = {}
        self.healthy = True

    def ping(self) -> None:
        if not self.healthy:
            from quick_chat_api.core.vectorstore.exceptions import (
                VectorStoreOperationError,
            )

            raise VectorStoreOperationError("fake store down")

    def upsert_points(self, agency: str, points: list[VectorPoint]) -> None:
        collection = self.collections.setdefault(agency, {})
        collection.update({p.id: p for p in points})

    def delete_points(self, agency: str, ids: list[UUID]) -> None:
        for id_ in ids:
            self.collections.get(agency, {}).pop(id_, None)

    def delete_by_filter(self, agency: str, filter_: VectorFilter) -> None:
        collection = self.collections.get(agency, {})
        for id_ in [i for i, p in collection.items() if _matches(p, filter_)]:
            del collection[id_]

    def list_points(self, agency: str, filter_: VectorFilter) -> list[StoredPoint]:
        return [
            StoredPoint(id=p.id, payload=p.payload)
            for p in self.collections.get(agency, {}).values()
            if _matches(p, filter_)
        ]

    def search(
        self,
        agency: str,
        query_vector: list[float],
        filter_: VectorFilter,
        top_k: int,
    ) -> list[VectorSearchResult]:
        hits = [
            VectorSearchResult(
                id=p.id, score=_dot(query_vector, p.vector), payload=p.payload
            )
            for p in self.collections.get(agency, {}).values()
            if _matches(p, filter_)
        ]
        return sorted(hits, key=lambda h: h.score, reverse=True)[:top_k]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _matches(point: VectorPoint, filter_: VectorFilter) -> bool:
    payload = point.payload
    if filter_.case_record_id is not None and payload.get("case_record_id") != str(
        filter_.case_record_id
    ):
        return False
    return not (
        filter_.source_types and payload.get("source_type") not in filter_.source_types
    )
