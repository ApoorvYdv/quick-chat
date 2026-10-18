"""Rerank providers: cross-encoder selection, passthrough, and remote via the real app."""

from __future__ import annotations

import httpx
import pytest

from quick_chat_api.core.llm.reranking.base import RerankCandidate
from quick_chat_api.core.llm.reranking.exceptions import RerankProviderError
from quick_chat_api.core.llm.reranking.providers.cross_encoder import (
    CrossEncoderReranker,
)
from quick_chat_api.core.llm.reranking.providers.none import NoopReranker
from quick_chat_api.core.llm.reranking.providers.remote import RemoteReranker
from quick_chat_inference import main


class FakeCrossEncoder:
    """Score = number in the text, so ordering is predictable."""

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(t) for _, t in pairs]


CANDIDATES = [RerankCandidate(f"c{i}", str(s)) for i, s in enumerate(range(-3, 7))]


def _ce(top_n: int = 5, min_score: float = 0.0) -> CrossEncoderReranker:
    return CrossEncoderReranker("m", "cpu", top_n, min_score, model=FakeCrossEncoder())


async def test_top_n_ordered_and_subset() -> None:
    results = await _ce().rerank("q", CANDIDATES)
    assert [r.score for r in results] == [6.0, 5.0, 4.0, 3.0, 2.0]
    assert {r.id for r in results} <= {c.id for c in CANDIDATES}


async def test_threshold_drops_below_min_and_may_return_fewer() -> None:
    results = await _ce(min_score=5.0).rerank("q", CANDIDATES)
    assert [r.score for r in results] == [6.0, 5.0]
    assert await _ce().rerank("q", []) == []


async def test_none_is_passthrough_first_n() -> None:
    results = await NoopReranker(5).rerank("q", CANDIDATES)
    assert [r.id for r in results] == ["c0", "c1", "c2", "c3", "c4"]


def _remote(reranker: object | None) -> RemoteReranker:
    main.app.state.reranker = reranker
    transport = httpx.ASGITransport(app=main.app)
    return RemoteReranker(
        "", 5, client=httpx.AsyncClient(transport=transport, base_url="http://inf")
    )


async def test_remote_matches_local_through_service() -> None:
    remote = _remote(_ce())
    assert await remote.rerank("q", CANDIDATES) == await _ce().rerank("q", CANDIDATES)
    assert await remote.rerank("q", []) == []


async def test_remote_drops_ids_outside_input() -> None:
    class Rogue:
        async def rerank(self, query, candidates):
            from quick_chat_api.core.llm.reranking.base import RerankResult

            return [RerankResult("evil", 9.0), RerankResult(candidates[0].id, 1.0)]

    results = await _remote(Rogue()).rerank("q", CANDIDATES)
    assert [r.id for r in results] == ["c0"]


async def test_remote_outage_raises_typed_error() -> None:
    down = httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=1)
    with pytest.raises(RerankProviderError):
        await RemoteReranker("", 1, client=down).rerank("q", CANDIDATES)
