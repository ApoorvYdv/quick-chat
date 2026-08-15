from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from dateutil.parser import parse


def get_datetime_localization() -> dict:
    return {
        "timezone": "America/Denver",
        "datetime_format": "%m/%d/%Y %I:%M %p",
        "date_format": "%m/%d/%Y",
        "time_format": "%I:%M %p",
    }


def get_client_timezone() -> ZoneInfo:
    timezone_name = get_datetime_localization().get("timezone", "UTC")
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def get_datetime_format() -> str:
    return get_datetime_localization().get("datetime_format", "%Y/%m/%d %I:%M %p")


def get_date_format() -> str:
    return get_datetime_localization().get("date_format", "%Y/%m/%d")


def get_time_format() -> str:
    return get_datetime_localization().get("time_format", "%I:%M %p")


def _normalize_datetime(value: datetime | str | None) -> datetime | None:
    if not value:
        return None

    if isinstance(value, str):
        value = parse(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(get_client_timezone())


def time_now() -> datetime:
    return datetime.now(UTC)


def formatted_localized_time_now_date() -> str:
    value = _normalize_datetime(time_now())
    return format_date(value.date())  # type: ignore


def formatted_time_now() -> str:
    return time_now().strftime(
        "%Y-%m-%d_%H-%M-%S_UTC"
    )  # Used only for s3 keys and does not fit the standard formatting pattern


def localize_datetime(value: datetime | str | None) -> str | None:
    value = _normalize_datetime(value)
    if value is None:
        return None

    return value.replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


def format_localized_datetime(value: datetime | str | None) -> str | None:
    value = _normalize_datetime(value)
    if value is None:
        return None

    return value.strftime(get_datetime_format())


def format_date(value: date | None) -> str | None:
    if value is None:
        return None

    return value.strftime(get_date_format())


def format_time(value: time | None) -> str | None:
    if value is None:
        return None

    return value.strftime(get_time_format())


def date_to_localized_start_of_day(d: date) -> datetime:
    """
    Convert a plain date (as sent by the client) to a UTC-aware datetime
    representing midnight (00:00:00) at the **start** of that date in the
    client's configured timezone.

    Use this as the lower bound when filtering a timestamptz column so that
    records created on that calendar day in the client's timezone are included.
    """
    tz = get_client_timezone()
    local_start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tz)
    return local_start.astimezone(UTC)


def date_to_localized_end_of_day(d: date) -> datetime:
    """
    Convert a plain date (as sent by the client) to a UTC-aware datetime
    representing the last microsecond (23:59:59.999999) of that date in the
    client's configured timezone.

    Use this as the upper bound when filtering a timestamptz column so that
    all records created during that calendar day in the client's timezone are
    included and no records from the *next* day leak through.
    """
    tz = get_client_timezone()
    local_end = datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=tz)
    return local_end.astimezone(UTC)
