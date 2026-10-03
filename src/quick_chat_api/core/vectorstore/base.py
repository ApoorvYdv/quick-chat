"""Vector store interface.

Separates "compute the embedding" (`core/llm/embedding/`) from "store/query
the vector" (this package). Callers (ingestion, retrieval) must depend only
on this interface, never on a concrete provider, so a store swap is a config
change (`VECTOR_STORE_PROVIDER`), not a code change at call sites.

Multi-tenancy is **collection-per-agency**: every method takes `agency`
explicitly and the provider resolves it to a dedicated collection, so one
tenant's vectors live in physically separate storage/index structures from
another's -- not merely a payload filter on a shared collection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class VectorPoint:
    """One vector + its filterable payload, keyed by the same id as its
    deterministic per entity chunk."""

    id: UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchResult:
    """One search hit: the point id, its similarity score, and its payload."""

    id: UUID
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class StoredPoint:
    """A stored point's id and payload, without its vector."""

    id: UUID
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorFilter:
    """Payload-equality filter applied server-side alongside the ANN search,
    scoped within a single agency's collection (see `agency` on each method
    below for how the collection itself is selected)."""

    case_record_id: UUID | None = None
    source_types: list[str] | None = None


class VectorStore(ABC):
    """Stores and queries embedding vectors, scoped per agency (tenant)."""

    @abstractmethod
    def upsert_points(self, agency: str, points: list[VectorPoint]) -> None:
        """Insert or replace points by id in `agency`'s collection. Batch, never one-by-one."""

    @abstractmethod
    def delete_points(self, agency: str, ids: list[UUID]) -> None:
        """Delete points by id from `agency`'s collection."""

    @abstractmethod
    def delete_by_filter(self, agency: str, filter_: VectorFilter) -> None:
        """Delete every point in `agency`'s collection matching `filter_`."""

    @abstractmethod
    def list_points(self, agency: str, filter_: VectorFilter) -> list[StoredPoint]:
        """Return every point (id + payload, no vector) in `agency`'s collection
        matching `filter_`, filtered server-side."""

    @abstractmethod
    def search(
        self,
        agency: str,
        query_vector: list[float],
        filter_: VectorFilter,
        top_k: int,
    ) -> list[VectorSearchResult]:
        """Return the `top_k` nearest points in `agency`'s collection to
        `query_vector` matching `filter_`.

        Filtering must happen server-side, scoped by `filter_`, never as a
        global unfiltered search followed by a Python-side filter. Tenant
        isolation itself comes from `agency` selecting a dedicated
        collection -- never from a payload condition alone.
        """

    @abstractmethod
    def ping(self) -> None:
        """Raise `VectorStoreError` if the backend is unreachable."""
