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
    with TestClient(main.app, base_url="http://inference") as c:
        yield c


def _remote(client: TestClient, model: str | None = None, dim: int = 8):
    return RemoteEmbeddingProvider(
        "http://inference", model or settings.EMBEDDING_MODEL, dim, 5, client=client
    )


def test_matches_local_provider(client: TestClient) -> None:
    remote, fake = _remote(client), FakeEmbeddingProvider(8)
    assert remote.dimension == 8 and remote.max_tokens == 512
    assert remote.embed_documents(["a b", "c"]) == fake.embed_documents(["a b", "c"])
    assert remote.embed_query("a b") == fake.embed_query("a b")
    assert remote.count_tokens("a b c") == 3
    assert remote.embed_documents([]) == []


def test_readyz_ok(client: TestClient) -> None:
    assert client.get("/readyz").status_code == 200


def test_mismatch_and_outage(client: TestClient) -> None:
    with pytest.raises(EmbeddingDimensionMismatchError):
        _remote(client, dim=768)
    with pytest.raises(EmbeddingProviderError):
        _remote(client, model="other-model")
    down = httpx.Client(base_url="http://127.0.0.1:1", timeout=1)
    with pytest.raises(EmbeddingProviderError):
        RemoteEmbeddingProvider("", "m", 8, 1, client=down)
