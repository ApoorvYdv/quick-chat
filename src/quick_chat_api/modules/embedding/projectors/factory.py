"""Factory for process-wide `Projector` instances, one per `source_type`.

Projectors are stateless and cheap to construct, but callers should still
go through `get_projector()` rather than instantiating a concrete class
directly, so a projector swap is a registry change, not a call-site change.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

# Import side effect: registers all built-in projectors.
from quick_chat_api.modules.embedding.projectors import (
    providers as _providers,  # noqa: F401
)
from quick_chat_api.modules.embedding.projectors.base import Projector
from quick_chat_api.modules.embedding.projectors.registry import build_projector


@lru_cache
def get_projector(source_type: str) -> Projector[Any]:
    """Return the cached projector registered for `source_type`."""
    return build_projector(source_type)
