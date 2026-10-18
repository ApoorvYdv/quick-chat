"""Remote provider against the real inference app, backed by the fake provider."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from quick_chat_api.core.llm.embedding.exceptions import (
    EmbeddingDimensionMismatchError,
    EmbeddingProviderError,
)
from quick_chat_api.core.llm.embedding.providers.remote import RemoteEmbeddingProvider
from quick_chat_api.settings.config import settings
from quick_chat_inference import main
from tests.fakes import FakeEmbeddingProvider


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(main, "build_provider", lambda *_: FakeEmbeddingProvider(8))
    monkeypatch.setattr(main, "build_reranker", lambda *_: object())
    with TestClient(main.app, base_url="http://inference") as c:
        yield c


def _remote(client: TestClient, model: str | None = None, dim: int = 8):
    # TestClient drives the ASGI app on its own loop; route the provider's
    # async calls to it through an in-process transport on that app.
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://inference"
    )
    return RemoteEmbeddingProvider(
        "http://inference", model or settings.EMBEDDING_MODEL, dim, 5, client=http
    )


async def test_matches_local_provider(client: TestClient) -> None:
    remote, fake = _remote(client), FakeEmbeddingProvider(8)
    with pytest.raises(EmbeddingProviderError):
        remote.dimension  # noqa: B018 -- must not be read before ensure_ready
    await remote.ensure_ready()
    assert remote.dimension == 8 and remote.max_tokens == 512
    docs = await remote.embed_documents(["a b", "c"])
    assert docs == await fake.embed_documents(["a b", "c"])
    assert await remote.embed_query("a b") == await fake.embed_query("a b")
    assert await remote.count_tokens_batch(["a b c", "d"]) == [3, 1]
    assert await remote.embed_documents([]) == []


def test_readyz_ok(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200


async def test_mismatch_and_outage(client: TestClient) -> None:
    with pytest.raises(EmbeddingDimensionMismatchError):
        await _remote(client, dim=768).ensure_ready()
    with pytest.raises(EmbeddingProviderError):
        await _remote(client, model="other-model").embed_query("x")
    down = httpx.AsyncClient(base_url="http://127.0.0.1:1", timeout=1)
    with pytest.raises(EmbeddingProviderError):
        await RemoteEmbeddingProvider("", "m", 8, 1, client=down).ensure_ready()
