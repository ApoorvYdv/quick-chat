"""Concrete `RerankProvider` implementations.

Importing this package registers every provider. Add one by creating
`providers/<name>.py` with a `@register_reranker("<name>")` builder and
importing it below.
"""

from quick_chat_api.core.llm.reranking.providers import cross_encoder as _cross_encoder
from quick_chat_api.core.llm.reranking.providers import none as _none
from quick_chat_api.core.llm.reranking.providers import remote as _remote

__all__: list[str] = []

# Referenced only for its import side effect (provider self-registration).
_ = (_cross_encoder, _none, _remote)
