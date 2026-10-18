from __future__ import annotations

from itertools import pairwise

import pytest

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.modules.embedding.chunking.base import SplitReason
from quick_chat_api.modules.embedding.chunking.exceptions import UnknownChunkerError
from quick_chat_api.modules.embedding.chunking.factory import get_chunker
from quick_chat_api.modules.embedding.chunking.providers.structured import (
    StructuredFieldChunker,
)
from quick_chat_api.modules.embedding.chunking.registry import build_chunker
from quick_chat_api.settings.config import settings


class FakeEmbeddingProvider(EmbeddingProvider):
    """Word-count tokenizer stand-in -- predictable, no model download."""

    def __init__(self, max_tokens: int = 10) -> None:
        self._max_tokens = max_tokens

    @property
    def dimension(self) -> int:
        return 8

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    async def ensure_ready(self) -> None:
        return None

    async def count_tokens_batch(self, texts: list[str]) -> list[int]:
        return [len(t.split()) for t in texts]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimension


@pytest.fixture
def chunker() -> StructuredFieldChunker:
    return StructuredFieldChunker()


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(max_tokens=10)  # budget = 9 at default 0.9 margin


async def test_document_under_budget_is_a_single_chunk(chunker, provider):
    content = "Case Number: 123\nCase Status: OPEN"
    chunks = await chunker.chunk(content, {"case_number": "123"}, provider)

    assert len(chunks) == 1
    assert chunks[0].content == content
    assert chunks[0].index == 0
    assert chunks[0].metadata["split_reason"] == SplitReason.SINGLE_CHUNK.value
    assert chunks[0].metadata["total_chunks"] == 1


async def test_document_over_budget_packs_whole_lines_per_chunk(chunker, provider):
    lines = [
        "Field1: aaa bbb ccc",  # 4 tokens
        "Field2: ddd eee fff",  # 4 tokens
        "Field3: ggg hhh iii",  # 4 tokens
    ]
    content = "\n".join(lines)

    chunks = await chunker.chunk(content, {}, provider)

    assert len(chunks) == 2
    assert chunks[0].content == "\n".join(lines[:2])
    assert chunks[1].content == lines[2]
    assert all(
        c.metadata["split_reason"] == SplitReason.FIELD_PACKED.value for c in chunks
    )
    assert all(c.metadata["total_chunks"] == 2 for c in chunks)
    # No line was ever cut mid-way.
    for chunk, source_line in zip(chunks, [lines[:2], lines[2:]], strict=True):
        for line in source_line:
            assert line in chunk.content


async def test_oversized_single_line_falls_back_to_overlapping_token_windows(
    chunker, provider
):
    words = [f"w{i}" for i in range(30)]
    content = " ".join(words)  # 30 tokens, budget is 9 -> must split further

    chunks = await chunker.chunk(content, {}, provider)

    assert len(chunks) > 1
    assert all(
        c.metadata["split_reason"] == SplitReason.TOKEN_WINDOW_FALLBACK.value
        for c in chunks
    )
    for c in chunks:
        assert c.token_count <= provider.max_tokens

    # Consecutive windows overlap by at least one word.
    for earlier, later in pairwise(chunks):
        earlier_words = earlier.content.split()
        later_words = later.content.split()
        assert set(earlier_words) & set(later_words)

    # Every original word survives somewhere in the output.
    covered = set()
    for c in chunks:
        covered.update(c.content.split())
    assert covered == set(words)


async def test_many_single_word_lines_that_each_exceed_budget_terminates(
    chunker, provider
):
    # Degenerate case: every "word" alone exceeds the budget, so each
    # window is a single word -- must not infinite-loop on overlap math.
    content = " ".join(f"w{i}" for i in range(5))
    tiny_provider = FakeEmbeddingProvider(max_tokens=1)  # budget rounds to 1 (min)

    assert await tiny_provider.count_tokens_batch(["w0"]) == [1]  # 1 token per word

    result = await chunker.chunk(content, {}, tiny_provider)

    assert len(result) == 5
    assert [c.content for c in result] == [f"w{i}" for i in range(5)]


async def test_document_metadata_is_merged_into_every_chunk(chunker, provider):
    chunks = await chunker.chunk(
        "Case Number: 123", {"case_number": "123", "source_type": "case"}, provider
    )

    assert chunks[0].metadata["case_number"] == "123"
    assert chunks[0].metadata["source_type"] == "case"
    assert chunks[0].metadata["chunking_strategy"] == "structured"
    assert "chunking_version" in chunks[0].metadata


async def test_empty_content_produces_no_chunks(chunker, provider):
    assert await chunker.chunk("", {}, provider) == []


def test_registry_raises_on_unknown_strategy():
    with pytest.raises(UnknownChunkerError, match="unknown"):
        build_chunker("unknown")


def test_factory_returns_cached_structured_chunker():
    first = get_chunker()
    second = get_chunker()

    assert first is second
    assert isinstance(first, StructuredFieldChunker)


async def test_oversized_line_windows_match_linear_scan(chunker, provider):
    # Binary-search window ends must equal the original word-by-word scan.
    words = [f"w{i}" for i in range(37)]
    chunks = await chunker.chunk(" ".join(words), {}, provider)
    budget = int(provider.max_tokens * settings.CHUNK_TOKEN_SAFETY_MARGIN)
    assert all(c.token_count <= budget for c in chunks)
    assert chunks[0].content.split() == words[:budget]
