"""Exceptions raised by the projector subsystem."""

from __future__ import annotations


class ProjectorError(RuntimeError):
    """Base class for all projector errors."""


class UnknownProjectorError(ProjectorError):
    """`source_type` does not match any registered projector."""
