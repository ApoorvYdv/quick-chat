from zoneinfo import ZoneInfo

from starlette_context import request_cycle_context

from quick_chat_api.settings.config import settings
from quick_chat_api.utils.context import RequestContext
from quick_chat_api.utils.helper import get_client_timezone


def test_outside_a_request_uses_default_and_getters_do_not_raise() -> None:
    assert RequestContext.agency == ""
    assert RequestContext.timezone is None
    assert RequestContext.user_details.agency_user_id is None
    assert get_client_timezone() == ZoneInfo(settings.DEFAULT_TIMEZONE)


def test_agency_timezone_overrides_default() -> None:
    with request_cycle_context({"timezone": "Asia/Kolkata"}):
        assert get_client_timezone() == ZoneInfo("Asia/Kolkata")


def test_unknown_timezone_falls_back_to_utc() -> None:
    with request_cycle_context({"timezone": "Not/AZone"}):
        assert get_client_timezone() == ZoneInfo("UTC")
