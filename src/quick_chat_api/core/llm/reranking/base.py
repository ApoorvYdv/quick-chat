"""Reranker interface.

Callers depend only on this contract; the backend is chosen by
`RERANK_PROVIDER`. A reranker never widens scope: every returned id is one of
the candidate ids it was given.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RerankCandidate:
    id: str
    text: str


@dataclass(frozen=True)
class RerankResult:
    id: str
    score: float


class RerankProvider(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, candidates: list[RerankCandidate]
    ) -> list[RerankResult]:
        """Return the kept candidates, best first. May be fewer than given."""
