from __future__ import annotations

import sys
import types

import pytest

from quick_chat_api.core.llm.embedding.exceptions import (
    EmbeddingDimensionMismatchError,
)


class _FakeTokenizer:
    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        # +2 for the special tokens a real tokenizer would add.
        return list(range(len(text.split()) + (2 if add_special_tokens else 0)))


class _FakeSentenceTransformer:
    """Stand-in for `sentence_transformers.SentenceTransformer` -- no model download."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        self.tokenizer = _FakeTokenizer()

    def get_embedding_dimension(self) -> int:
        return 768

    def get_max_seq_length(self) -> int:
        return 384

    def encode(self, texts, **kwargs):
        import numpy as np

        if isinstance(texts, str):
            return np.zeros(768)
        return np.zeros((len(texts), 768))


@pytest.fixture
def local_provider(monkeypatch):
    fake_module = types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    from quick_chat_api.core.llm.embedding.providers.local_sentence_transformer import (
        LocalSentenceTransformerProvider,
    )

    return LocalSentenceTransformerProvider(
        model_name="fake-model", expected_dimension=768
    )


def test_max_tokens_reflects_model_seq_length(local_provider):
    assert local_provider.max_tokens == 384


def test_count_tokens_uses_the_real_tokenizer(local_provider):
    assert local_provider.count_tokens("hello world") == 4  # 2 words + 2 specials


def test_dimension_mismatch_raises(monkeypatch):
    fake_module = types.SimpleNamespace(SentenceTransformer=_FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    from quick_chat_api.core.llm.embedding.providers.local_sentence_transformer import (
        LocalSentenceTransformerProvider,
    )

    with pytest.raises(EmbeddingDimensionMismatchError):
        LocalSentenceTransformerProvider(model_name="fake-model", expected_dimension=1536)
