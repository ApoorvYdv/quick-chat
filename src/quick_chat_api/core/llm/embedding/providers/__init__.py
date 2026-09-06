"""Concrete `EmbeddingProvider` implementations.

Importing this package registers every provider with the registry
(`quick_chat_api.core.llm.embedding.registry`) via each module's
`@register_provider(...)` decorator. Add a new provider by:

1. Creating `providers/<name>.py` with a class + a `@register_provider("<name>")`
   builder function (see `local_sentence_transformer.py` for the pattern).
2. Importing that module below.

No other file needs to change.
"""

from quick_chat_api.core.llm.embedding.providers import (
    local_sentence_transformer as _local_sentence_transformer,
)

__all__: list[str] = []

# Referenced only for its import side effect (provider self-registration).
_ = _local_sentence_transformer
