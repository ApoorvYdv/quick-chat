"""Semantic projector interface.

Every entity that becomes retrievable knowledge (a `CaseRecord`, a
`PartyDetail`, a `CaseCharge`, a `CaseAppearance`, ...) is turned into an
embeddable natural-language document by a `Projector`, never serialized
directly from its SQLAlchemy model. Callers (DB source adapters, the
ingestion service) depend only on this interface via `get_projector(...)`,
never on a concrete projector class, so adding a projector for a new
entity is a registry addition, not a call-site change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, TypeVar

EntityT = TypeVar("EntityT")


@dataclass(frozen=True)
class ProjectedDocument:
    """Embeddable text plus traceable, filterable source metadata.

    `metadata` carries business-context fields useful for retrieval
    filtering (e.g. case number, party type) -- per `.claude/rules/rag.md`,
    prefer metadata filtering over relying on the embedding to carry
    identifiers. It is not the DB identity of the source row; the caller
    (a DB source adapter) owns `source_table`/`source_id`.
    """

    content: str
    title: str | None = None
    metadata: dict = field(default_factory=dict)


class Projector(ABC, Generic[EntityT]):
    """Turns one domain entity into a `ProjectedDocument`."""

    @abstractmethod
    def project(self, entity: EntityT) -> ProjectedDocument:
        """Build the embeddable document for `entity`."""
