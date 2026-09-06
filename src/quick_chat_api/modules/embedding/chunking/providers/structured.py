"""Structure-aware chunker for projected structured documents.

Projectors (`modules/embedding/projectors/`) render one field per line via
`_formatting.field_line`/`join_lines`. A field line is the natural
semantic unit for these documents -- splitting a case's "Disposition: ..."
line across two chunks is strictly worse for grounding than splitting
*between* two field lines, so this chunker packs whole lines greedily into
each chunk and only falls back to splitting a line's own text when that one
line alone exceeds the token budget (e.g. a long `additional_notes` field).
"""

from __future__ import annotations

from quick_chat_api.core.llm.embedding.base import EmbeddingProvider
from quick_chat_api.modules.embedding.chunking.base import Chunk, Chunker, SplitReason
from quick_chat_api.modules.embedding.chunking.registry import register_chunker
from quick_chat_api.settings.config import settings


class StructuredFieldChunker(Chunker):
    """Greedily packs field lines into chunks under a per-chunk token budget."""

    def chunk(
        self,
        content: str,
        document_metadata: dict,
        provider: EmbeddingProvider,
    ) -> list[Chunk]:
        budget = self._token_budget(provider)
        lines = [line for line in content.split("\n") if line]

        pieces = self._pack_lines(lines, provider, budget)
        return self._build_chunks(pieces, document_metadata, provider)

    def _token_budget(self, provider: EmbeddingProvider) -> int:
        return max(1, int(provider.max_tokens * settings.CHUNK_TOKEN_SAFETY_MARGIN))

    def _pack_lines(
        self,
        lines: list[str],
        provider: EmbeddingProvider,
        budget: int,
    ) -> list[tuple[str, SplitReason]]:
        pieces: list[tuple[str, SplitReason]] = []
        current_lines: list[str] = []
        current_tokens = 0

        def flush() -> None:
            if current_lines:
                pieces.append(("\n".join(current_lines), SplitReason.FIELD_PACKED))

        for line in lines:
            line_tokens = provider.count_tokens(line)

            if line_tokens > budget:
                flush()
                current_lines.clear()
                current_tokens = 0
                for window in self._split_oversized_line(line, provider, budget):
                    pieces.append((window, SplitReason.TOKEN_WINDOW_FALLBACK))
                continue

            if current_lines and current_tokens + line_tokens > budget:
                flush()
                current_lines = []
                current_tokens = 0

            current_lines.append(line)
            current_tokens += line_tokens

        flush()

        if len(pieces) == 1 and pieces[0][1] is SplitReason.FIELD_PACKED:
            piece_text, _ = pieces[0]
            pieces = [(piece_text, SplitReason.SINGLE_CHUNK)]

        return pieces

    def _split_oversized_line(
        self,
        line: str,
        provider: EmbeddingProvider,
        budget: int,
    ) -> list[str]:
        """Sliding token-window split, used only when one line alone exceeds `budget`.

        Rare path (a single unusually long free-text field): walks word by
        word rather than by token offsets, since the `EmbeddingProvider`
        interface exposes counting but not tokenizer offset mapping. This
        keeps the interface minimal at the cost of O(n) `count_tokens`
        calls per oversized line -- acceptable given how infrequently this
        branch runs.
        """
        words = line.split(" ")
        overlap_ratio = settings.CHUNK_OVERLAP_RATIO
        windows: list[str] = []
        start = 0

        while start < len(words):
            end = start + 1
            while (
                end < len(words)
                and provider.count_tokens(" ".join(words[start : end + 1])) <= budget
            ):
                end += 1
            windows.append(" ".join(words[start:end]))

            if end >= len(words):
                break

            overlap_words = max(1, int((end - start) * overlap_ratio))
            # Guarantee forward progress even for a single-word window
            # (e.g. one token-heavy word alone at/over budget), where
            # `end - overlap_words` could otherwise equal `start`.
            start = max(start + 1, end - overlap_words)

        return windows

    def _build_chunks(
        self,
        pieces: list[tuple[str, SplitReason]],
        document_metadata: dict,
        provider: EmbeddingProvider,
    ) -> list[Chunk]:
        total = len(pieces)
        chunks = []
        for index, (piece_text, reason) in enumerate(pieces):
            chunks.append(
                Chunk(
                    content=piece_text,
                    index=index,
                    token_count=provider.count_tokens(piece_text),
                    metadata={
                        **document_metadata,
                        "chunking_strategy": "structured",
                        "chunking_version": settings.CHUNKING_VERSION,
                        "split_reason": reason.value,
                        "total_chunks": total,
                    },
                )
            )
        return chunks


@register_chunker("structured")
def _build_structured_chunker() -> StructuredFieldChunker:
    return StructuredFieldChunker()
