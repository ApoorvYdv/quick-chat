"""Projector registry.

Decouples the factory from concrete projector implementations: each
projector module registers itself under a `source_type` name via
`@register_projector(...)`. Adding a projector for a new entity never
requires editing this file or the factory -- only adding a new module
under `providers/` and importing it in `providers/__init__.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from quick_chat_api.modules.embedding.projectors.exceptions import (
    UnknownProjectorError,
)

if TYPE_CHECKING:
    from quick_chat_api.modules.embedding.projectors.base import Projector

ProjectorBuilder = Callable[[], "Projector[Any]"]

_REGISTRY: dict[str, ProjectorBuilder] = {}


def register_projector(
    source_type: str,
) -> Callable[[ProjectorBuilder], ProjectorBuilder]:
    """Class/function decorator that registers a builder under `source_type`."""

    def decorator(builder: ProjectorBuilder) -> ProjectorBuilder:
        _REGISTRY[source_type] = builder
        return builder

    return decorator


def build_projector(source_type: str) -> Projector[Any]:
    """Look up and construct the projector registered under `source_type`."""
    try:
        builder = _REGISTRY[source_type]
    except KeyError:
        available = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise UnknownProjectorError(
            f"source_type='{source_type}' has no registered projector. "
            f"Available projectors: {available}."
        ) from None
    return builder()
