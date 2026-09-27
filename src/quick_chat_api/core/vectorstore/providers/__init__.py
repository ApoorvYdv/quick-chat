"""Concrete `VectorStore` implementations.

Importing this package registers every provider with the registry
(`quick_chat_api.core.vectorstore.registry`) via each module's
`@register_store(...)` decorator. Add a new provider by:

1. Creating `providers/<name>.py` with a class + a `@register_store("<name>")`
   builder function (see `qdrant.py` for the pattern).
2. Importing that module below.

No other file needs to change.
"""

from quick_chat_api.core.vectorstore.providers import qdrant as _qdrant

__all__: list[str] = []

# Referenced only for its import side effect (provider self-registration).
_ = _qdrant
