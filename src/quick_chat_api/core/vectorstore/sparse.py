"""Stdlib BM25-style sparse encoder for Qdrant's IDF-modified sparse vectors.

Qdrant applies IDF server-side (`Modifier.IDF`), so the client only supplies
saturated term frequencies. Tokens are hashed to u32 indices with crc32, which
is stable across processes (unlike `hash()`), so documents and queries agree.
"""

from __future__ import annotations

import re
import zlib
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_K1 = 1.2


def _indices(text: str) -> Counter[int]:
    return Counter(zlib.crc32(t.encode()) for t in _TOKEN.findall(text.lower()))


def encode_document(text: str) -> tuple[list[int], list[float]]:
    """Sparse vector of BM25 term-frequency saturation (length norm omitted)."""
    counts = _indices(text)
    return list(counts), [tf * (_K1 + 1) / (tf + _K1) for tf in counts.values()]


def encode_query(text: str) -> tuple[list[int], list[float]]:
    """Each distinct query term weighs 1; IDF is applied by Qdrant."""
    counts = _indices(text)
    return list(counts), [1.0] * len(counts)
