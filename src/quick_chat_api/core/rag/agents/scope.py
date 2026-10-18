"""Case-id scope: the resolved set every per-case tool call is checked against."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID


class CaseScopeViolation(ValueError):
    """A tool call named case ids outside the resolved set."""

    def __init__(self, rejected: list[UUID]) -> None:
        super().__init__("case id outside the resolved scope")
        self.rejected = rejected


@dataclass(frozen=True)
class CaseScope:
    """`ids=None` means no case was resolved (agency-wide); tenancy is enforced by the DB schema and Qdrant collection."""

    ids: frozenset[UUID] | None = None

    @classmethod
    def of(cls, ids: Iterable[UUID]) -> CaseScope:
        resolved = frozenset(ids)
        return cls(resolved or None)

    def require(self, case_ids: Iterable[UUID]) -> list[UUID]:
        requested = list(dict.fromkeys(case_ids))
        if self.ids is not None and not self.ids.issuperset(requested):
            raise CaseScopeViolation([i for i in requested if i not in self.ids])
        return requested
