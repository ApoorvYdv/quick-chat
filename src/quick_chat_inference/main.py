"""Shared inference service: hosts the local embedding model once for all API workers.

Internal-network only (no auth); runs the existing `local` provider.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel

# Import side effect: registers the built-in providers.
from quick_chat_api.core.llm.embedding import providers as _providers  # noqa: F401
from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.core.llm.embedding.registry import build_provider
from quick_chat_api.core.llm.reranking import (
    providers as _rerank_providers,  # noqa: F401
)
from quick_chat_api.core.llm.reranking.base import RerankCandidate, RerankProvider
from quick_chat_api.core.llm.reranking.registry import build_reranker
from quick_chat_api.settings.config import settings


class InfoResponse(BaseModel):
    model: str
    version: str
    dimension: int
    max_tokens: int


class EmbedRequest(BaseModel):
    texts: list[str]
    kind: Literal["document", "query"]


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]


class CountTokensRequest(BaseModel):
    texts: list[str]


class CountTokensResponse(BaseModel):
    counts: list[int]


class RerankCandidateIn(BaseModel):
    id: str
    text: str


class RerankRequest(BaseModel):
    query: str
    candidates: list[RerankCandidateIn]


class RerankResultOut(BaseModel):
    id: str
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResultOut]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.provider = build_provider("local", settings)
    app.state.reranker = build_reranker("cross_encoder", settings)
    yield


app = FastAPI(title="Quick Chat Inference", lifespan=lifespan)


def get_provider(request: Request) -> EmbeddingProvider:
    return request.app.state.provider


def get_reranker(request: Request) -> RerankProvider:
    return request.app.state.reranker


Provider = Annotated[EmbeddingProvider, Depends(get_provider)]
Reranker = Annotated[RerankProvider, Depends(get_reranker)]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, str]:
    state = request.app.state
    if (
        getattr(state, "provider", None) is None
        or getattr(state, "reranker", None) is None
    ):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"status": "ok"}


@app.get("/info", response_model=InfoResponse)
async def info(provider: Provider) -> InfoResponse:
    return InfoResponse(
        model=settings.EMBEDDING_MODEL,
        version=settings.EMBEDDING_VERSION,
        dimension=provider.dimension,
        max_tokens=provider.max_tokens,
    )


@app.post("/embed", response_model=EmbedResponse)
async def embed(body: EmbedRequest, provider: Provider) -> EmbedResponse:
    if body.kind == "query":
        return EmbedResponse(
            embeddings=[await provider.embed_query(t) for t in body.texts]
        )
    return EmbedResponse(embeddings=await provider.embed_documents(body.texts))


@app.post("/count_tokens", response_model=CountTokensResponse)
async def count_tokens(
    body: CountTokensRequest, provider: Provider
) -> CountTokensResponse:
    return CountTokensResponse(counts=await provider.count_tokens_batch(body.texts))


@app.post("/rerank", response_model=RerankResponse)
async def rerank(body: RerankRequest, reranker: Reranker) -> RerankResponse:
    results = await reranker.rerank(
        body.query, [RerankCandidate(c.id, c.text) for c in body.candidates]
    )
    return RerankResponse(
        results=[RerankResultOut(id=r.id, score=r.score) for r in results]
    )
