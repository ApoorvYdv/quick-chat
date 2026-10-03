from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from starlette_context import context


class UserDetails(BaseModel):
    name: str = ""
    email: str = ""
    username: str = ""
    cognito_id: str = ""
    is_super_admin: bool = False
    roles: list[str] = Field(default_factory=list)
    permissions: set[str] = Field(default_factory=set)
    agency_user_id: UUID | None = None


class _RequestContext:
    """
    Typed, property-based wrapper around starlette_context.

    This is a stateless facade — all data lives in the per-request
    ContextVar managed by starlette_context middleware, so concurrent
    requests never interfere with each other.

    Usage::

        from quick_chat_api.utils.context.request_context import RequestContext

        # Reading
        agency = RequestContext.agency
        user   = RequestContext.user_details

        # Writing (typically in dependencies)
        RequestContext.agency = "some_agency"
    """

    # ── agency ──────────────────────────────────────────────────────

    @property
    def agency(self) -> str:
        return context.get("agency", "") if context.exists() else ""

    @agency.setter
    def agency(self, value: str) -> None:
        context.update({"agency": value})

    # ── user_details ────────────────────────────────────────────────

    @property
    def user_details(self) -> UserDetails:
        stored = context.get("user_details") if context.exists() else None
        raw: dict[str, Any] = stored or {}
        return UserDetails(**raw)

    @user_details.setter
    def user_details(self, value: UserDetails) -> None:
        context.update({"user_details": value.model_dump()})

    # ── timezone ────────────────────────────────────────────────────

    @property
    def timezone(self) -> str | None:
        return context.get("timezone") if context.exists() else None

    @timezone.setter
    def timezone(self, value: str | None) -> None:
        context.update({"timezone": value})


RequestContext = _RequestContext()
