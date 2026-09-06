"""Concrete `Projector` implementations.

Importing this package registers every projector with the registry
(`quick_chat_api.modules.embedding.projectors.registry`) via each module's
`@register_projector(...)` decorator. Add a projector for a new entity by:

1. Creating `providers/<entity>.py` with a class + a
   `@register_projector(<source_type>)` builder function (see `case.py`
   for the pattern).
2. Adding the new `source_type` to `AIKnowledgeSourceType`
   (`core/constants/constants.py`).
3. Importing that module below.

No other file needs to change.
"""

from quick_chat_api.modules.embedding.projectors.providers import (
    appearance as _appearance,
)
from quick_chat_api.modules.embedding.projectors.providers import case as _case
from quick_chat_api.modules.embedding.projectors.providers import (
    case_summary as _case_summary,
)
from quick_chat_api.modules.embedding.projectors.providers import charge as _charge
from quick_chat_api.modules.embedding.projectors.providers import party as _party

__all__: list[str] = []

# Referenced only for import side effects (projector self-registration).
_ = (_case, _case_summary, _party, _charge, _appearance)
