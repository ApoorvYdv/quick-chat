from typing import Any

from pydantic import BaseModel, Field
from starlette_context import context

from quick_chat_api.core.constants.constants import CaseTypes


class UserDetails(BaseModel):
    name: str = ""
    email: str = ""
    username: str = ""
    cognito_id: str = ""
    is_super_admin: bool = False
    roles: list[str] = Field(default_factory=list)
    permissions: set[str] = Field(default_factory=set)
    agency_user_id: int | None = None


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
        cfg    = RequestContext.config

        # Writing (typically in dependencies)
        RequestContext.agency = "some_agency"
    """

    # ── agency ──────────────────────────────────────────────────────

    @property
    def agency(self) -> str:
        return context.get("agency", "")

    @agency.setter
    def agency(self, value: str) -> None:
        context.update({"agency": value})

    # ── config ──────────────────────────────────────────────────────

    @property
    def config(self) -> dict[str, dict[str, Any]]:
        return context.get("config") or {}

    @config.setter
    def config(self, value: dict[str, dict[str, Any]]) -> None:
        context.update({"config": value})

    # ── user_details ────────────────────────────────────────────────

    @property
    def user_details(self) -> UserDetails:
        raw: dict[str, Any] = context.get("user_details") or {}
        return UserDetails(**raw)

    @user_details.setter
    def user_details(self, value: UserDetails) -> None:
        context.update({"user_details": value.model_dump()})

    # ── case_types ──────────────────────────────────────────────────

    @property
    def case_types(self) -> list[CaseTypes] | None:
        return context.get("case_types")

    @case_types.setter
    def case_types(self, value: list[CaseTypes] | None) -> None:
        context.update({"case_types": value})


RequestContext = _RequestContext()
